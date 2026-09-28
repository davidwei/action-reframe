"""Audited model responses with actionable transport, truncation and format errors."""
import json
import copy
import socket
import time
import urllib.error
from pathlib import Path


class ModelResponseError(RuntimeError):
    def __init__(self,message,details):
        super().__init__(message)
        self.details=details


def fetch_response(api,url,payload,response_path,details):
    stage=details['stage']
    try:
        response=api(url) if payload is None else api(url,payload)
    except urllib.error.HTTPError as error:
        body=error.read().decode('utf-8',errors='replace')
        response_path.write_text(body)
        details.update(kind='http_error',http_status=error.code,response_excerpt=body[:1500])
        raise ModelResponseError(f'Model server HTTP {error.code} during {stage}: {body[:700] or error.reason}',details) from error
    except (TimeoutError,socket.timeout) as error:
        details.update(kind='timeout')
        raise ModelResponseError(f'Model request timed out during {stage}. Server load or a stalled request may be responsible; retry when capacity is available.',details) from error
    except json.JSONDecodeError as error:
        details.update(kind='invalid_response')
        raise ModelResponseError(f'Model server returned a non-JSON HTTP response during {stage}: {error}',details) from error
    except urllib.error.URLError as error:
        details.update(kind='connection_error')
        raise ModelResponseError(f'Cannot reach model server during {stage}: {error.reason}',details) from error
    response_path.write_text(json.dumps(response,indent=2))
    if isinstance(response,dict) and response.get('error'):
        details.update(kind='server_error',response_excerpt=str(response['error'])[:1500])
        raise ModelResponseError(f'Model server reported an error during {stage}: {str(response["error"])[:700]}',details)
    return response


def completion(api,url,payload,audit,stage,validator=None):
    """Save raw envelopes before parsing. Retry output truncation once with a concise-output instruction."""
    audit=Path(audit);audit.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(2):
        request=copy.deepcopy(payload)
        if attempt:
            request['max_tokens']=min(4096,request.get('max_tokens',1000)*2)
            instruction=('The previous generation exceeded its output limit. Answer the original task again from scratch, '
                         'concisely. Do not repeat observations or elaborate speculatively. '
                         'Preserve required fields and uncertainty; finish the complete answer within 250 words.')
            if validator is not None:instruction+=' Return only one complete JSON object, including its closing brace.'
            messages=request.setdefault('messages',[])
            if messages and messages[-1].get('role')=='user':
                content=messages[-1].get('content','')
                if isinstance(content,list):content.append({'type':'text','text':instruction})
                else:messages[-1]['content']=content+'\n'+instruction
            else:messages.append({'role':'user','content':instruction})
        if validator is not None:request['response_format']={'type':'json_object'}
        request_path=audit if attempt==0 else audit.with_name(audit.stem+'_retry.json')
        # Never duplicate base64 images in the audit; their source crops are kept separately.
        logged=json.loads(json.dumps(request))
        for message in logged.get('messages',[]):
            for part in message.get('content',[]) if isinstance(message.get('content'),list) else []:
                if part.get('type')=='image_url':part['image_url']={'url':'[image omitted; see crop/request audit]'}
        payload_path=request_path.with_name(request_path.stem+'_payload.json')
        payload_path.write_text(json.dumps(logged,indent=2))
        response_path=request_path.with_name(request_path.stem+'_raw_response.json')
        details={'stage':stage,'attempt':attempt+1,'max_tokens':request.get('max_tokens'),
                 'request_file':str(payload_path),'response_file':str(response_path)}
        started=time.monotonic()
        try:
            response=fetch_response(api,url,request,response_path,details)
            try:choice=response['choices'][0];raw=choice['message']['content']
            except (KeyError,IndexError,TypeError) as error:
                details.update(kind='invalid_response')
                raise ModelResponseError(f'Model server returned an invalid completion envelope during {stage}. See the saved response.',details) from error
            details.update(finish_reason=choice.get('finish_reason'),usage=response.get('usage'),
                           model=response.get('model'),request_id=response.get('id'),
                           response_excerpt=raw[:1500] if isinstance(raw,str) else repr(raw))
            if choice.get('finish_reason')=='length':
                details.update(kind='truncated_output')
                error=ModelResponseError(f'Model output was truncated during {stage}: output limit {request["max_tokens"]} tokens (finish_reason=length).',details)
                details['elapsed_seconds']=round(time.monotonic()-started,3)
                request_path.with_name(request_path.stem+'_error.json').write_text(json.dumps(dict(details,error=str(error)),indent=2))
                if not attempt:continue
                raise error
            if choice.get('finish_reason') in ('error','content_filter') or choice['message'].get('refusal'):
                details.update(kind='generation_error')
                raise ModelResponseError(f'Model did not produce an answer during {stage} (finish_reason={choice.get("finish_reason")}).',details)
            if not isinstance(raw,str) or not raw.strip():
                details.update(kind='empty_response')
                raise ModelResponseError(f'Model returned an empty answer during {stage} (finish_reason={choice.get("finish_reason")}).',details)
            if validator is None:return raw
            try:
                start=raw.find('{')
                if start<0:raise ValueError('no JSON object was returned')
                result,end=json.JSONDecoder().raw_decode(raw[start:])
                if not isinstance(result,dict):raise ValueError('expected a JSON object')
                validator(result)
            except (ValueError,TypeError,KeyError) as error:
                details.update(kind='invalid_json_or_schema')
                raise ModelResponseError(f'Model returned invalid structured output during {stage}: {error}. Finish reason: {choice.get("finish_reason","unknown")}. Response: {raw[:300]}',details) from error
            result.update(raw=raw,request_file=str(payload_path),response_file=str(response_path))
            return result
        except ModelResponseError as error:
            error.details['elapsed_seconds']=round(time.monotonic()-started,3)
            request_path.with_name(request_path.stem+'_error.json').write_text(json.dumps(dict(error.details,error=str(error)),indent=2))
            raise


def discover_model(api,url,audit):
    audit=Path(audit);audit.parent.mkdir(parents=True,exist_ok=True)
    response_path=audit.with_name(audit.stem+'_raw_response.json')
    details={'stage':'model discovery','response_file':str(response_path)}
    started=time.monotonic()
    try:
        response=fetch_response(api,url,None,response_path,details)
        try:model=response['data'][0]['id']
        except (KeyError,IndexError,TypeError) as error:
            details['kind']='invalid_response'
            raise ModelResponseError('Model server returned no usable model during model discovery.',details) from error
        if not isinstance(model,str) or not model:
            details['kind']='invalid_response'
            raise ModelResponseError('Model server returned an invalid model identifier.',details)
        return model
    except ModelResponseError as error:
        error.details['elapsed_seconds']=round(time.monotonic()-started,3)
        audit.with_name(audit.stem+'_error.json').write_text(json.dumps(dict(error.details,error=str(error)),indent=2))
        raise
