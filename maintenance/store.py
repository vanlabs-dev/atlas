"""SQLite durable scan ledger. Store is a context manager; callers serialize workers.

initialize explicitly accepts a pinned baseline (not a claim of prior audit).
All returned records are plain dictionaries, and evidence is JSON serializable.
"""
import json
import sqlite3


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS chains (genesis TEXT PRIMARY KEY, number INTEGER NOT NULL, hash TEXT NOT NULL, baseline TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (genesis TEXT, activation_hash TEXT, code_hash TEXT, number INTEGER NOT NULL, evidence TEXT NOT NULL, state TEXT NOT NULL DEFAULT \'detected\', receipt TEXT, lease_owner TEXT, lease_until REAL, PRIMARY KEY(genesis, activation_hash, code_hash))')
        self.db.execute('CREATE TABLE IF NOT EXISTS transitions (id INTEGER PRIMARY KEY, genesis TEXT, activation_hash TEXT, code_hash TEXT, previous TEXT, state TEXT, receipt TEXT, at REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS progress (genesis TEXT, kind TEXT, receipt TEXT, PRIMARY KEY(genesis,kind))')
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(jobs)')}
        for name, definition in {'notification_error': 'TEXT',
                                 'attempts': 'INTEGER NOT NULL DEFAULT 0',
                                 'next_retry_at': 'REAL', 'last_attempt_at': 'REAL'}.items():
            if name not in columns:
                self.db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {definition}')
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def cursor(self, genesis):
        row = self.db.execute('SELECT number, hash FROM chains WHERE genesis=?', (genesis,)).fetchone()
        return dict(row) if row else None

    def baseline(self, genesis):
        row = self.db.execute('SELECT baseline FROM chains WHERE genesis=?', (genesis,)).fetchone()
        return json.loads(row[0]) if row else None

    def jobs(self, genesis):
        """Deployment-order records; evidence and receipt are decoded JSON."""
        rows = self.db.execute('SELECT * FROM jobs WHERE genesis=? ORDER BY number, activation_hash', (genesis,))
        return [{**dict(r), 'evidence': json.loads(r['evidence']),
                 'receipt': json.loads(r['receipt']) if r['receipt'] else None,
                 'notification_error': json.loads(r['notification_error']) if r['notification_error'] else None} for r in rows]

    def notification_result(self, key, error):
        """Record enqueue failure separately from gate/activation state."""
        with self.db:
            self.db.execute('UPDATE jobs SET notification_error=? WHERE genesis=? AND activation_hash=? AND code_hash=?',
                            (json.dumps(error) if error else None, *key))

    def accept_block(self, genesis, number, block_hash, parent_hash, event=None):
        """Atomically accept one contiguous finalized block and optional event.

        A replay of the exact current block is idempotent. Exceptions roll back
        both job insertion and cursor advancement. event must name this block.
        """
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous = self.cursor(genesis)
            if previous == {'number': number, 'hash': block_hash}:
                return
            if previous is None or number != previous['number'] + 1 or parent_hash != previous['hash']:
                raise ValueError('noncontiguous scan; explicit baseline required')
            if event is not None:
                if event.get('activation_number') != number or event.get('activation_hash') != block_hash or not event.get('code_hash'):
                    raise ValueError('event identity mismatch')
                self.db.execute('INSERT INTO jobs(genesis,activation_hash,code_hash,number,evidence) VALUES(?,?,?,?,?)',
                                (genesis, block_hash, event['code_hash'], number, json.dumps(event, sort_keys=True)))
            self.db.execute('UPDATE chains SET number=?, hash=? WHERE genesis=?', (number, block_hash, genesis))

    def claim(self, key, owner, *, now, ttl=300):
        """Claim/renew a job lease. key=(genesis, activation_hash, code_hash)."""
        if not owner or ttl <= 0:
            raise ValueError('owner and positive ttl required')
        with self.db:
            result = self.db.execute('UPDATE jobs SET lease_owner=?, lease_until=? WHERE genesis=? AND activation_hash=? AND code_hash=? AND (lease_until IS NULL OR lease_until<=? OR lease_owner=?)', (owner, now + ttl, *key, now, owner))
            return result.rowcount == 1

    def get_job(self, key):
        row = self.db.execute('SELECT * FROM jobs WHERE genesis=? AND activation_hash=? AND code_hash=?', key).fetchone()
        if row is None:
            raise ValueError('unknown job')
        result = dict(row)
        for field in ('evidence', 'receipt', 'notification_error'):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def begin_attempt(self, key, owner, *, now, ttl, max_attempts, resume=False):
        """Atomically claim and start/recover one bounded attempt.

        Resume restores the last successful checkpoint without appending a fake
        success transition. Failure receipts remain in immutable history.
        Returns (job, refusal_reason); no writes on a refused attempt.
        """
        if not owner or ttl <= 0 or max_attempts < 1:
            raise ValueError('owner, positive ttl and max_attempts required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            job = self.get_job(key)
            state = job['state']
            if state in ('activated', 'historical-audited') or (state in ('blocked', 'failed') and not resume):
                return job, 'terminal' if state in ('activated', 'historical-audited') else 'resume-required'
            if job['lease_until'] is not None and job['lease_until'] > now and job['lease_owner'] != owner:
                return job, 'leased'
            if job['attempts'] >= max_attempts:
                return job, 'retry-exhausted'
            if job['next_retry_at'] is not None and now < job['next_retry_at']:
                return job, 'retry-delayed'
            receipt = job['receipt']
            if state in ('blocked', 'failed'):
                if not isinstance(receipt, dict) or receipt.get('failed_gate_after') not in ('detected', 'evidence-ready', 'editing', 'validated', 'published') or 'last_receipt' not in receipt:
                    raise ValueError('missing durable failure checkpoint')
                state, receipt = receipt['failed_gate_after'], receipt['last_receipt']
            self.db.execute('UPDATE jobs SET state=?, receipt=?, attempts=attempts+1, last_attempt_at=?, next_retry_at=NULL, lease_owner=?, lease_until=? WHERE genesis=? AND activation_hash=? AND code_hash=?',
                            (state, json.dumps(receipt), now, owner, now + ttl, *key))
            return self.get_job(key), None

    def release(self, key, owner):
        with self.db:
            self.db.execute('UPDATE jobs SET lease_owner=NULL, lease_until=NULL WHERE genesis=? AND activation_hash=? AND code_hash=? AND lease_owner=?', (*key, owner))

    def transition(self, key, owner, expected, state, receipt, *, now, retry_delay=0):
        """CAS transition under a live lease; append immutable receipt history.

        Failure checkpoints must match the durable last successful receipt.
        Only begin_attempt(resume=True) may restore a failed checkpoint.
        """
        allowed = {'detected': {'evidence-ready'}, 'evidence-ready': {'editing'},
                   'editing': {'validated'}, 'validated': {'published'},
                   'published': {'activated'}}
        if expected not in allowed or state not in allowed[expected] | {'blocked', 'failed'}:
            raise ValueError('invalid state transition')
        if retry_delay < 0:
            raise ValueError('retry_delay must be nonnegative')
        if state in ('blocked', 'failed') and (receipt.get('failed_gate_after') != expected or 'last_receipt' not in receipt):
            raise ValueError('failure checkpoint required')
        if state in ('published', 'activated') and not receipt.get('commit'):
            raise ValueError('commit receipt required')
        payload = json.dumps(receipt, sort_keys=True)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if state in ('blocked', 'failed') and self.get_job(key)['receipt'] != receipt['last_receipt']:
                raise ValueError('failure checkpoint does not match durable receipt')
            result = self.db.execute('UPDATE jobs SET state=?, receipt=? WHERE genesis=? AND activation_hash=? AND code_hash=? AND state=? AND lease_owner=? AND lease_until>?', (state, payload, *key, expected, owner, now))
            if result.rowcount != 1:
                raise ValueError('stale state or expired/unowned lease')
            if state in ('blocked', 'failed'):
                self.db.execute('UPDATE jobs SET next_retry_at=? WHERE genesis=? AND activation_hash=? AND code_hash=?', (now + retry_delay, *key))
            self.db.execute('INSERT INTO transitions(genesis,activation_hash,code_hash,previous,state,receipt,at) VALUES(?,?,?,?,?,?,?)', (*key, expected, state, payload, now))
            if state in ('validated', 'published', 'activated'):
                kind = 'audited' if state == 'validated' else state
                progress = json.dumps({**receipt, 'activation_hash': key[1], 'code_hash': key[2]}, sort_keys=True)
                self.db.execute('INSERT INTO progress VALUES(?,?,?) ON CONFLICT(genesis,kind) DO UPDATE SET receipt=excluded.receipt', (key[0], kind, progress))

    def mark_historical_audited(self, keys, receipt, *, now=None):
        """Atomically retire historical jobs covered by a latest activated audit.

        Receipt schema: complete=True, audit_target=[genesis,hash,code_hash],
        commit matching that activated target, evidence_receipts=[{key:[...],
        complete:True, evidence_sha256:<64 hex>}], including every key and target.
        This records trusted evidence attestations; it does not validate files.
        It never creates activation/publication progress for historical jobs.
        """
        import time
        now = time.time() if now is None else now
        keys = list(dict.fromkeys(tuple(k) for k in keys))
        if not keys:
            return
        if not isinstance(receipt, dict) or receipt.get('complete') is not True:
            raise ValueError('complete audit receipt required')
        target_key = receipt.get('audit_target')
        if not isinstance(target_key, (list, tuple)) or len(target_key) != 3 or not all(isinstance(v, str) and v for v in target_key):
            raise ValueError('audit target reference required')
        target_key = tuple(target_key)
        evidence = {}
        for item in receipt.get('evidence_receipts', []):
            if not isinstance(item, dict) or not isinstance(item.get('key'), (list, tuple)) or len(item['key']) != 3:
                raise ValueError('invalid evidence receipt')
            key = tuple(item['key'])
            digest = item.get('evidence_sha256', '')
            if key in evidence or item.get('complete') is not True or not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdefABCDEF' for c in digest):
                raise ValueError('complete unique evidence digest required')
            evidence[key] = item
        if any(key not in evidence for key in [*keys, target_key]):
            raise ValueError('missing complete evidence for audit coverage')
        payload = json.dumps(receipt, sort_keys=True)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            target = self.get_job(target_key)
            latest = self.db.execute('SELECT MAX(number) FROM jobs WHERE genesis=?', (target_key[0],)).fetchone()[0]
            if target['number'] != latest or target['state'] != 'activated' or not receipt.get('commit') or target['receipt'].get('commit') != receipt['commit']:
                raise ValueError('audit target must be latest activated job with matching commit')
            for key in keys:
                job = self.get_job(key)
                if key[0] != target_key[0] or job['number'] >= target['number']:
                    raise ValueError('historical job must precede audit target on same chain')
                if job['state'] == 'historical-audited':
                    if job['receipt'] != receipt:
                        raise ValueError('historical audit receipt conflict')
                    continue
                if job['state'] == 'activated':
                    raise ValueError('cannot replace an activated job')
                if job['lease_until'] is not None and job['lease_until'] > now:
                    raise ValueError('historical job has live lease')
                self.db.execute("UPDATE jobs SET state='historical-audited', receipt=?, lease_owner=NULL, lease_until=NULL, next_retry_at=NULL WHERE genesis=? AND activation_hash=? AND code_hash=?", (payload, *key))
                self.db.execute('INSERT INTO transitions(genesis,activation_hash,code_hash,previous,state,receipt,at) VALUES(?,?,?,?,?,?,?)', (*key, job['state'], 'historical-audited', payload, now))

    def progress(self, genesis):
        """Independent last audited/published/activated receipts, never cursor."""
        return {r['kind']: json.loads(r['receipt']) for r in self.db.execute('SELECT * FROM progress WHERE genesis=?', (genesis,))}

    def history(self, key):
        return [{**dict(r), 'receipt': json.loads(r['receipt'])} for r in self.db.execute('SELECT * FROM transitions WHERE genesis=? AND activation_hash=? AND code_hash=? ORDER BY id', key)]

    def initialize(self, genesis, number, block_hash, evidence):
        if self.cursor(genesis) is not None:
            raise ValueError('baseline already initialized')
        if number < 0:
            raise ValueError('negative baseline')
        with self.db:
            self.db.execute('INSERT INTO chains VALUES (?,?,?,?)', (genesis, number, block_hash, json.dumps(evidence, sort_keys=True)))
