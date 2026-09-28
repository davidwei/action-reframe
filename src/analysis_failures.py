"""Classify frame-local model output failures without hiding system failures."""
OUTPUT_KINDS={'truncated_output','invalid_json_or_schema','empty_response','generation_error','invalid_response'}


def output_failure(row):
    details=row.get('model_error',{})
    if details:return details.get('kind') in OUTPUT_KINDS
    return row.get('error_kind')=='invalid_response' or str(row.get('error','')).startswith((
        'Model output was truncated','Model returned invalid structured output','Model returned an empty answer','substring not found'))


def path_failures(candidates):
    failures=[]
    for path,row in candidates.items():
        evidence=row if row.get('error') else row.get('box_verification',{})
        if evidence.get('error'):
            if not output_failure(evidence):raise RuntimeError(evidence['error'])
            failures.append(dict(path=path,error=evidence['error'],model_error=evidence.get('model_error',{})))
            row['confidence']=0
    return failures
