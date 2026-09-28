"""Append-only saved/approved description revisions, separate from model drafts."""
import json
import time
import uuid


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS description_revisions (
        id TEXT PRIMARY KEY, project TEXT NOT NULL, description TEXT NOT NULL,
        kind TEXT NOT NULL, created REAL NOT NULL, input_revision TEXT,
        source TEXT NOT NULL UNIQUE)''')
    db.execute('CREATE INDEX IF NOT EXISTS description_revisions_project ON description_revisions(project,created)')


def append(db,project,description,kind,created=None,input_revision=None,source=None):
    identity=uuid.uuid4().hex
    db.execute('INSERT OR IGNORE INTO description_revisions VALUES(?,?,?,?,?,?,?)',
        (identity,project,description,kind,time.time() if created is None else created,input_revision,source or identity))
    return identity


def backfill(batch,db,project):
    schema(db)
    # Preserve the latest pre-history preparation before its next overwrite.
    if not db.execute('SELECT 1 FROM description_revisions WHERE project=? LIMIT 1',(project,)).fetchone():
        old=db.execute('SELECT payload FROM preparations WHERE project=?',(project,)).fetchone()
        if old:
            payload=json.loads(old[0])
            append(db,project,payload.get('description',''),'approved' if payload.get('ready') else 'saved',
                payload.get('updated_at') or payload.get('approved_at') or time.time(),payload.get('revision'),'legacy:'+project)
    # Older approved text may survive in immutable queued-run manifests.
    for row in db.execute('SELECT id,config,created FROM jobs WHERE project=?',(project,)).fetchall():
        source='job:'+row['id']
        if db.execute('SELECT 1 FROM description_revisions WHERE source=?',(source,)).fetchone():continue
        path=batch.path(row['config']).parent/'inputs.json'
        try:data=json.loads(path.read_text())
        except (OSError,ValueError):continue
        prep=data.get('preparation',{})
        if prep.get('ready') and isinstance(prep.get('description'),str):
            append(db,project,prep['description'],'approved',prep.get('approved_at') or row['created'],prep.get('revision'),source)


def history(batch,project):
    config,_,_=batch.inputs(project)
    if config.get('batch_input_revision'):raise ValueError('Open the source project to browse description revisions')
    with batch.db() as db:
        db.execute('BEGIN IMMEDIATE');backfill(batch,db,project)
        rows=[dict(r) for r in db.execute('SELECT * FROM description_revisions WHERE project=? ORDER BY created DESC,rowid DESC',(project,))]
    return {'revisions':rows}
