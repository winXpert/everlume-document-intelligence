"""Durable, sequential indexing jobs. File receipt and inference are separate."""
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

import httpx


class UploadQueue:
    def __init__(self, store):
        self.store = store
        self.root = store.root / 'upload-queue'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(store.root / 'upload-jobs.db', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT, created TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, job_id TEXT, name TEXT, category TEXT, state TEXT, error TEXT, position INTEGER)')
        # A crashed worker may safely repeat an item: its document ID is stable.
        self.db.execute("UPDATE items SET state='queued' WHERE state='indexing'")
        self.db.commit()

    def create(self, owner, names, category):
        job_id = str(uuid.uuid4())
        with self.lock:
            self.db.execute('INSERT INTO jobs VALUES (?,?,?)', (job_id, owner, datetime.now(timezone.utc).isoformat()))
            self.db.executemany('INSERT INTO items VALUES (?,?,?,?,?,?,?)',
                [(str(uuid.uuid4()), job_id, name, category, 'awaiting_upload', '', i) for i, name in enumerate(names)])
            self.db.commit()
        return self.get(owner, job_id)

    def get(self, owner, job_id):
        with self.lock:
            job = self.db.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (job_id, owner)).fetchone()
            if not job:
                return None
            items = [dict(row) for row in self.db.execute('SELECT * FROM items WHERE job_id=? ORDER BY position', (job_id,))]
        counts = {state: sum(item['state'] == state for item in items) for state in
                  ['awaiting_upload', 'queued', 'indexing', 'indexed', 'failed', 'cancelled']}
        complete = counts['indexed'] + counts['failed'] + counts['cancelled']
        for item in items:
            item['can_retry'] = item['state'] == 'failed' and (self.root / (item['id'] + '.ready')).exists()
        return {'id': job_id, 'created': job['created'], 'items': items, 'counts': counts,
                'total': len(items), 'completed': complete, 'finished': complete == len(items)}

    def recent(self, owner):
        with self.lock:
            ids = [row['id'] for row in self.db.execute('SELECT id FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 20', (owner,))]
        return [self.get(owner, job_id) for job_id in ids]

    def receive(self, owner, job_id, item_id, writer):
        with self.lock:
            job = self.get(owner, job_id)
            item = next((i for i in job['items'] if i['id'] == item_id), None) if job else None
            if not item:
                return None
            if item['state'] not in {'awaiting_upload', 'failed'}:
                return item
            path = self.root / (item_id + '.ready')
            part = self.root / (item_id + '.part')
            try:
                writer(part, item['name'])
                part.replace(path)
                self.db.execute("UPDATE items SET state='queued',error='' WHERE id=?", (item_id,))
            except Exception:
                part.unlink(missing_ok=True)
                raise
            finally:
                self.db.commit()
        return next(i for i in self.get(owner, job_id)['items'] if i['id'] == item_id)

    def fail_receipt(self, owner, job_id, item_id, error):
        with self.lock:
            job = self.get(owner, job_id)
            if job and any(i['id'] == item_id and i['state'] in {'awaiting_upload', 'failed'} for i in job['items']):
                self.db.execute("UPDATE items SET state='failed',error=? WHERE id=?", (error, item_id))
                self.db.commit()

    def cancel(self, owner, job_id):
        with self.lock:
            job = self.get(owner, job_id)
            if not job:
                return None
            for item in job['items']:
                if item['state'] in {'awaiting_upload', 'queued', 'failed'}:
                    self.db.execute("UPDATE items SET state='cancelled' WHERE id=?", (item['id'],))
                    (self.root / (item['id'] + '.ready')).unlink(missing_ok=True)
            self.db.commit()
        return self.get(owner, job_id)

    def retry(self, owner, job_id, item_id):
        with self.lock:
            job = self.get(owner, job_id)
            item = next((i for i in job['items'] if i['id'] == item_id), None) if job else None
            if not item:
                return None
            if not item['can_retry']:
                raise ValueError('Choose the original file again to retry this upload')
            self.db.execute("UPDATE items SET state='queued',error='' WHERE id=?", (item_id,))
            self.db.commit()
            return {'id': item_id, 'state': 'queued'}

    def process_next(self):
        with self.lock:
            row = self.db.execute("SELECT items.*, jobs.owner FROM items JOIN jobs ON jobs.id=items.job_id WHERE state='queued' ORDER BY jobs.created,position LIMIT 1").fetchone()
            if not row:
                return False
            item = dict(row)
            self.db.execute("UPDATE items SET state='indexing' WHERE id=?", (item['id'],))
            self.db.commit()
        path = self.store.files / item['id']
        staged = self.root / (item['id'] + '.ready')
        state, error = 'indexed', ''
        try:
            if not self.store.get(item['owner'], item['id']):
                if staged.exists():
                    staged.replace(path)
                self.store.index(item['owner'], item['id'], path, item['name'], item['category'], 'Batch upload')
        except Exception as exc:
            state = 'failed'
            error = 'Ollama unavailable or model missing. Retry this file.' if isinstance(exc, httpx.HTTPError) else str(exc) if isinstance(exc, ValueError) else 'Indexing failed. Retry this file.'
            logging.warning('Upload queue item %s failed: %s', item['id'], type(exc).__name__)
            if path.exists():
                path.replace(staged)
        finally:
            if state == 'indexed':
                staged.unlink(missing_ok=True)
        with self.lock:
            self.db.execute('UPDATE items SET state=?,error=? WHERE id=?', (state, error, item['id']))
            self.db.commit()
        return True
