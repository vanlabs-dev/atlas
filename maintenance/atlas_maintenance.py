#!/usr/bin/env python3
"""Atlas runtime maintenance: independent scan, gated worker, durable status."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys

from .store import Store
from .detect import Detector
from .fastscan import BatchRPC, scan_fast
from .controller import advance_job, resume_job


def enqueue_notification(store, job, status, receipt):
    if status not in ('detected','blocked','activated'):
        raise ValueError('unsupported notification status')
    identity=job['activation_hash']+':'+job['code_hash'][2:]
    spec=job['evidence']['current']['runtime']['specVersion']
    detail=f"runtime spec {spec}; block {job['number']}; state {status}"
    if status=='activated':detail+='; commit '+str(receipt['commit'])
    if status=='blocked':
        # Do not put arbitrary provider error text or generated content in alerts.
        detail+='; gate '+str(receipt.get('failed_gate_after','unknown'))+'; inspect maintenance status'
    with store.db:
        store.db.execute('CREATE TABLE IF NOT EXISTS maintenance_notifications ('
            'id INTEGER PRIMARY KEY, upgrade_id TEXT NOT NULL, status TEXT NOT NULL, '
            'detail TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(upgrade_id,status))')
        store.db.execute('INSERT OR IGNORE INTO maintenance_notifications(upgrade_id,status,detail,created_at) VALUES(?,?,?,?)',
            (identity,status,detail,datetime.datetime.now(datetime.timezone.utc).isoformat()))


def status(store, genesis, config=None):
    import time
    config = config or {}
    baseline = store.baseline(genesis)
    if baseline is not None:
        baseline = {k: v for k, v in baseline.items() if k != 'metadata'}
    jobs = []
    for job in store.jobs(genesis):
        summary = {k: job[k] for k in ('number', 'activation_hash', 'code_hash', 'state',
                   'receipt', 'attempts', 'next_retry_at', 'last_attempt_at', 'notification_error',
                   'lease_owner', 'lease_until')}
        retry = None
        if job['state'] not in ('activated', 'historical-audited'):
            if job['attempts'] >= config.get('max_job_attempts', 3):
                retry = 'retry-exhausted'
            elif job['next_retry_at'] is not None and job['next_retry_at'] > time.time():
                retry = 'retry-delayed'
            elif job['state'] in ('blocked', 'failed'):
                retry = 'retry-ready'
        summary.update(retry_status=retry, reason=(job['receipt'] or {}).get('reason'))
        jobs.append(summary)
    return {'cursor': store.cursor(genesis), 'baseline': baseline,
            'progress': store.progress(genesis), 'jobs': jobs}


def job_root(config, job):
    return Path(config['state_dir'])/'jobs'/job['activation_hash'][2:]


def unfinished_publication(config, job):
    checkpoint = (job.get('receipt') or {}).get('failed_gate_after', job['state'])
    root = job_root(config, job)
    return checkpoint == 'published' or any(
        (root/name).exists() for name in ('publication-intent.json', 'publication-receipt.json'))


def reconcile_history(store, config, target, older):
    """Rebuild evidence from retained artifacts; never invent audit coverage."""
    from .pipeline import model_packet, combine_packets
    from .worker import canonical
    if any(unfinished_publication(config, j) for j in older):
        return {'state': 'blocked', 'retry_status': 'publication-recovery-required',
                'reason': 'Unresolved historical publication cannot be retired'}
    try:
        root = job_root(config, target).resolve(strict=True)
        receipt = json.loads((root/'evidence-receipt.json').read_text())
        model = json.loads((root/'model-packet.json').read_text())
        digest = hashlib.sha256(canonical(model)).hexdigest()
        if digest != receipt['model_packet_sha256']:
            raise ValueError('model packet changed after collection')
        target_key = (target['genesis'], target['activation_hash'], target['code_hash'])
        validations = [t['receipt'] for t in store.history(target_key) if t['state'] == 'validated']
        if not validations or validations[-1].get('evidence_sha256') != digest:
            raise ValueError('model packet is not bound to the validated target')
        packets = []
        for item in receipt['evidence_receipts']:
            directory = Path(item['packet_dir']).resolve(strict=True)
            directory.relative_to(root)
            packet = json.loads((directory/'packet.json').read_text())
            rebuilt = model_packet(packet, directory, config['source_repo'])
            deployment = rebuilt['deployments']['new']
            if item['key'] != [deployment['genesis_hash'], deployment['block_hash'], deployment['code_hash']]:
                raise ValueError('historical evidence identity mismatch')
            if hashlib.sha256(canonical(rebuilt)).hexdigest() != item['evidence_sha256']:
                raise ValueError('historical evidence changed after collection')
            packets.append(rebuilt)
        if canonical(combine_packets(packets)) != canonical(model):
            raise ValueError('historical evidence does not reconstruct the audited model packet')
        audit = {'complete': True, 'audit_target': list(target_key),
                 'commit': target['receipt']['commit'],
                 'evidence_receipts': receipt['evidence_receipts']}
        store.mark_historical_audited(
            [(j['genesis'], j['activation_hash'], j['code_hash']) for j in older], audit)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'state': 'blocked', 'retry_status': 'historical-reconciliation-required',
                'reason': str(exc)[:1000], 'activated_target': target['activation_hash']}
    return {'state': 'activated', 'receipt': target['receipt'], 'historical_audited': len(older)}


def process_jobs(store, config, command):
    """Caller must hold worker.lock, including when reclaiming our stable lease."""
    from .pipeline import Pipeline
    all_jobs = store.jobs(config['genesis'])
    jobs = [j for j in all_jobs if j['state'] not in ('activated', 'historical-audited')]
    if not jobs:
        return {'state': 'idle'}
    if all_jobs[-1]['state'] == 'activated':
        return reconcile_history(store, config, all_jobs[-1], jobs)
    job = jobs[-1]
    old_publications = [j for j in jobs[:-1] if unfinished_publication(config, j)]
    if old_publications:
        if command != 'recover':
            return {'state': 'blocked', 'retry_status': 'publication-recovery-required',
                    'activation_hash': old_publications[0]['activation_hash'],
                    'reason': 'Older publication must be recovered before processing a newer target'}
        job = old_publications[0]
    failed = job['state'] in ('blocked', 'failed')
    if ((command == 'retry' and not failed) or
            (command == 'recover' and job['state'] == 'detected')):
        return {'state': 'blocked', 'retry_status': 'inappropriate-stage',
                'reason': 'retry requires a failure; recover requires a durable checkpoint'}
    pipeline = Pipeline(config, store, job)
    advance = resume_job if failed else advance_job
    result = advance(store, job, pipeline.steps(),
                     max_attempts=config.get('max_job_attempts', 3),
                     retry_delay=config.get('retry_delay_seconds', 3600),
                     owner='worker:' + str(Path(config['state_dir']).resolve()),
                     notify=lambda j,s,r:enqueue_notification(store,j,s,r))
    if result['state'] == 'activated':
        current = store.jobs(config['genesis'])
        if current[-1]['activation_hash'] == job['activation_hash']:
            older = [j for j in current[:-1] if j['state'] not in ('activated', 'historical-audited')]
            if older:
                return reconcile_history(store, config, current[-1], older)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=str(Path(__file__).with_name('config.json')))
    parser.add_argument('command',choices=('init','scan','process','retry','recover','status','inference-smoke'))
    args=parser.parse_args(argv)
    config=json.loads(Path(args.config).read_text())
    state=Path(config['state_dir'])
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(state,0o700)
    if args.command=='inference-smoke':
        from .inference import HermesBroker
        broker=HermesBroker(python=config['hermes_python'],hermes_source=config['hermes_source'],timeout=config['inference_timeout'])
        result=broker({'protocol':'Return exactly {"ready":true,"tools":false} as JSON.'})
        if result != {'ready':True,'tools':False}:raise ValueError('inference smoke response mismatch')
        print(json.dumps(result));return 0
    if args.command=='status':
        # SQLite supplies a consistent view without waiting for a long model job.
        with Store(state/'maintenance.db') as store:
            print(json.dumps(status(store,config['genesis'],config),indent=2))
        return 0
    lock_name='scan.lock' if args.command in ('init','scan') else 'worker.lock'
    with (state/lock_name).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'state':'busy'}));return 0
        with Store(state/'maintenance.db') as store:
            if args.command in ('init','scan'):
                detector=Detector(BatchRPC(config['rpc_url'],timeout=config['rpc_timeout']),store,config['genesis'])
                if args.command=='init':
                    detector.initialize(config['baseline']['number'],config['baseline']['hash'])
                    result={'initialized':True,'scope':config['baseline']['coverage']}
                else:
                    result=scan_fast(detector,max_blocks=config['scan_max_blocks'])
                    for job in store.jobs(config['genesis']):enqueue_notification(store,job,'detected',{})
            else:
                result=process_jobs(store, config, args.command)
            print(json.dumps(result,indent=2))
            return 2 if isinstance(result,dict) and (
                result.get('state') in ('blocked', 'failed') or
                result.get('retry_status') == 'retry-exhausted') else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        # Full details remain in the durable job receipt when processing a job.
        print(json.dumps({'state':'failed','exception':type(exc).__name__,'reason':str(exc)[:1000]}))
        raise SystemExit(2)
