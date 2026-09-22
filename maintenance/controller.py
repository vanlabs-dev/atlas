"""Durable gated advancement; callers hold an outer exclusive lock."""
import time
import uuid

STAGES = ('detected', 'evidence-ready', 'editing', 'validated', 'published', 'activated')


def advance_job(store, job, steps, *, notify=None, lease_seconds=21600,
                max_attempts=3, retry_delay=0, owner=None, resume=False):
    """Run remaining gates, using the durable job rather than a stale snapshot.

    max_attempts includes the initial attempt. retry_delay is seconds after a
    gate failure. Interrupted runs require the old lease to expire or the same
    explicit owner (only safe while holding the outer exclusive lock).
    """
    if retry_delay < 0:
        raise ValueError('retry_delay must be nonnegative')
    key = (job['genesis'], job['activation_hash'], job['code_hash'])
    owner = owner or uuid.uuid4().hex
    job, refusal = store.begin_attempt(key, owner, now=time.time(), ttl=lease_seconds,
                                       max_attempts=max_attempts, resume=resume)
    if refusal:
        return {'state': 'leased' if refusal == 'leased' else job['state'],
                'receipt': job['receipt'], 'retry_status': refusal}
    state, receipt = job['state'], job['receipt']
    try:
        for next_state in STAGES[STAGES.index(state)+1:]:
            try:
                candidate = steps[next_state]({**job, 'state': state, 'receipt': receipt})
                if not isinstance(candidate, dict):
                    raise ValueError('gate returned no receipt')
                store.transition(key, owner, state, next_state, candidate, now=time.time())
            except Exception as exc:
                blocked = {'reason': str(exc)[:2000], 'exception': type(exc).__name__,
                           'failed_gate_after': state, 'last_receipt': receipt}
                store.transition(key, owner, state, 'blocked', blocked,
                                 now=time.time(), retry_delay=retry_delay)
                state, receipt = 'blocked', blocked
                break
            state, receipt = next_state, candidate
        # Notification enqueue and its error persistence are outside the gate
        # failure handler: even a failed SQLite write cannot undo activation.
        if notify and state in ('activated', 'blocked', 'failed'):
            _notify(store, key, notify, job, state, receipt)
        return {'state': state, 'receipt': receipt}
    finally:
        store.release(key, owner)


def resume_job(store, job, steps, **kwargs):
    """Explicit bounded retry from failed_gate_after, never from detected."""
    return advance_job(store, job, steps, **{**kwargs, 'resume': True})


def _notify(store, key, notify, job, state, receipt):
    try:
        notify(job, state, receipt)
    except Exception as exc:
        error = {'reason': str(exc)[:2000], 'exception': type(exc).__name__,
                 'state': state, 'receipt': receipt}
    else:
        error = None
    store.notification_result(key, error)
