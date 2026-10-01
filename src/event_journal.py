"""Append scheduler events; checkpoints commit a durable journal prefix."""
import json
import os
import uuid
from pathlib import Path
from durable_json import sync_directory


class EventJournal:
    def __init__(self, folder, checkpoint=None):
        self.folder=Path(folder)
        marker=(checkpoint or {}).get('event_journal')
        if marker:
            name=marker['file']
            if Path(name).name!=name:raise ValueError('Invalid event journal filename')
            self.path=self.folder/name
            self.offset=int(marker['committed_bytes']);self.count=int(marker['count'])
            size=self.path.stat().st_size
            if size<self.offset:raise ValueError('Event journal is shorter than committed checkpoint')
            if size>self.offset:
                # A crash may leave events whose state was never checkpointed.
                # Preserve them for diagnosis, but do not replay them as committed work.
                with self.path.open('rb+') as stream:
                    stream.seek(self.offset)
                    archive=self.folder/('events_uncommitted_'+uuid.uuid4().hex+'.jsonl')
                    with archive.open('wb') as target:
                        while block:=stream.read(1024*1024):target.write(block)
                        target.flush();os.fsync(target.fileno())
                    sync_directory(self.folder)
                    stream.truncate(self.offset);stream.flush();os.fsync(stream.fileno())
        else:
            self.path=self.folder/('events_'+uuid.uuid4().hex+'.jsonl')
            self.path.touch();self.offset=0;self.count=0
            sync_directory(self.folder)

    def checkpoint(self, state, save, path):
        pending=state.get('events',[])
        with self.path.open('ab') as stream:
            for event in pending:
                stream.write((json.dumps(event,allow_nan=False,separators=(',',':'))+'\n').encode())
            stream.flush();os.fsync(stream.fileno())
            offset=stream.tell()
        marker=dict(version=1,file=self.path.name,committed_bytes=offset,count=self.count+len(pending))
        snapshot=dict(state,event_journal=marker);snapshot.pop('events',None)
        # Atomic checkpoint replacement commits the journal prefix. On save failure
        # the caller must abort; resume recovers from the old checkpoint boundary.
        save(path,snapshot)
        self.offset=offset;self.count=marker['count']
        state['event_journal']=marker;state['events']=[]
