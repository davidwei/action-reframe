"""Separate telemetry database; no automatic deletion policy."""
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time

DEFAULTS={'enabled':True,'timezone':'America/Los_Angeles','report_hour':7,'model_commentary':False}


def folder(root):
    p=Path(root)/'.lookout';p.mkdir(parents=True,exist_ok=True);return p


def settings(root):
    p=folder(root)/'settings.json'
    return dict(DEFAULTS,**(json.loads(p.read_text()) if p.exists() else {}))


@contextmanager
def connect(root):
    db=sqlite3.connect(folder(root)/'telemetry.sqlite3',timeout=.25)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,ts REAL,kind TEXT,body TEXT,received REAL);
    CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
    CREATE TABLE IF NOT EXISTS reports(day TEXT PRIMARY KEY,body TEXT,updated REAL);
    CREATE TABLE IF NOT EXISTS decisions(key TEXT PRIMARY KEY,state TEXT,until_day TEXT,updated REAL);
    CREATE TABLE IF NOT EXISTS job_snapshots(id TEXT PRIMARY KEY,status TEXT);
    ''')
    try:
        with db:yield db
    finally:db.close()


def insert(root,events):
    with connect(root) as db:
        db.executemany('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)',
            [(e['id'],e['timestamp'],e['kind'],json.dumps(e),time.time()) for e in events])


def status(root):
    with connect(root) as db:
        row=db.execute('SELECT count(*) n,min(ts) first,max(received) last FROM events').fetchone()
        decisions={r['key']:dict(r) for r in db.execute('SELECT * FROM decisions')}
        days=[r[0] for r in db.execute('SELECT day FROM reports ORDER BY day DESC')]
    heartbeat=folder(root)/'heartbeat.json'
    health=json.loads(heartbeat.read_text()) if heartbeat.exists() else {}
    return dict(settings=settings(root),events=row['n'],first_event=row['first'],last_event=row['last'],
        storage_bytes=sum(p.stat().st_size for p in folder(root).glob('*') if p.is_file()),
        collector=health,collector_alive=time.time()-health.get('timestamp',0)<20,days=days,decisions=decisions)
