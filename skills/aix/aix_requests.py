"""One durable unresolved CREATE intent, using the protocol's idempotency key.

This is a client outbox, never a ledger or a task-state authority.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import sqlite3


@contextmanager
def create_intent(client, payload):
    store = client.store
    digest = hashlib.sha256(json.dumps([client.base_url,client.agent_id,payload],
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if store.backend == 'memory':
        # Session-only callers cannot claim cross-process recovery.
        pending = getattr(client,'_pending_creates',{})
        old = pending.get(digest)
        key = old or 'aix-skill-'+secrets.token_hex(16)
        pending[digest]=key;client._pending_creates=pending
        yield key,bool(old),lambda:pending.pop(digest,None)
        return
    store.prepare_file_path()
    path=store.isolated_file.with_name(store.isolated_file.name+'.pending-requests.sqlite3')
    with sqlite3.connect(path,timeout=35) as db:
        os.chmod(path,0o600)
        db.execute('CREATE TABLE IF NOT EXISTS pending (intent TEXT PRIMARY KEY, key TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT key FROM pending WHERE intent=?',(digest,)).fetchone()
        key=row[0] if row else 'aix-skill-'+secrets.token_hex(16)
        db.execute('INSERT OR IGNORE INTO pending VALUES (?,?)',(digest,key))
        db.commit()  # durable BEFORE network I/O; serialize sends separately
        db.execute('BEGIN IMMEDIATE')
        # A prior owner may have completed while we waited for its send lock.
        current=db.execute('SELECT key FROM pending WHERE intent=?',(digest,)).fetchone()
        if not current:
            # Reuse this caller's key: server replay is safe; never invent a second key.
            pass
        def complete():db.execute('DELETE FROM pending WHERE intent=? AND key=?',(digest,key))
        try:
            yield key,bool(row),complete
        finally:
            db.commit()  # preserve pending on exceptions; never infer rollback at origin

def input_upload_intent(client, payload, files, value=None, *, clear=False):
    """Durable association of explicit local paths with unresolved CREATE input IDs.

    This outbox metadata never asserts that an Offer or upload exists at origin.
    Keep it through uncertain CREATE so bound inputs cannot become fresh IDs.
    """
    digest = hashlib.sha256(json.dumps([client.base_url, client.agent_id, payload, files],
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    store = client.store
    if store.backend == 'memory':
        entries = getattr(client, '_pending_input_uploads', {})
        client._pending_input_uploads = entries
        if clear: entries.pop(digest, None)
        elif value is not None: entries.setdefault(digest, value)
        return entries.get(digest)
    store.prepare_file_path()
    path = store.isolated_file.with_name(store.isolated_file.name+'.pending-requests.sqlite3')
    with sqlite3.connect(path, timeout=35) as db:
        os.chmod(path, 0o600)
        db.execute('CREATE TABLE IF NOT EXISTS input_uploads (intent TEXT PRIMARY KEY, refs TEXT NOT NULL)')
        if clear:
            db.execute('DELETE FROM input_uploads WHERE intent=?', (digest,))
        elif value is not None:
            db.execute('INSERT OR IGNORE INTO input_uploads VALUES (?,?)', (digest, json.dumps(value)))
        row = db.execute('SELECT refs FROM input_uploads WHERE intent=?', (digest,)).fetchone()
        return json.loads(row[0]) if row else None
