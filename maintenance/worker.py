"""Deterministic coding/review protocol; models have no filesystem tools.

propose(root, packet, model, selected_paths=()) returns an in-memory proposal.
model is callable(dict)->dict (normally inference.HermesBroker, which creates a
fresh session on every call). Large packets receive bounded full-raw-source
audit passes before a compact, explicitly labeled summary view. Coder/reviewer
audits are independent, with controller-checked exact coverage and hash receipts.
Reads are limited to tracked, nonsecret regular UTF-8 files.
``packet`` requires complete=True, upstream_paths, chunk_ids and chunks
[{id,path,text,sha256}], with no blocked status/reasons. Optional atlas_inventory
subsystems extend mandatory inventory-group coverage. Source coverage is never
truncated: raw audit batches are bounded at 120k source bytes and every request
at 800k serialized bytes. No summary can stand in for an undelivered raw chunk.

``propose`` produces edits for existing hash-bound files or absent regular files
with before_sha256=None. ``apply_proposal`` applies but does NOT stage them.
Hash-bound unique substring replacements normalize to the same full-content API.
Their serialized output and materialized file/overall sizes have separate caps.
File requests replace the payload window, retaining inspected hashes locally.
Rejected batches preserve the previous window/hashes and return sanitized feedback;
a valid corrected request is required before finalizing, within max_rounds. Full
inventory/groups remain evidence coverage, separate from conditional requestability.
Actual broker JSON budgets include the next window and a feedback reserve.
Reviews start with complete unified diffs; original/current files are requestable.
Pass proposal= to run_isolated_tests so untracked new tests are included. The
parent stages/commits explicit manifest paths, then supplies the actual tree and
trusted check results to review_proposal. Independent review's evidence hash is
sha256(canonical(packet)); validate_candidate must receive those exact bytes.

No commands from model output are ever executed. apply_proposal is the only
write API; publication and testing are separate trusted orchestration gates.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path

SUBSYSTEMS = ('inventory', 'hardening', 'hermes', 'knowledge', 'repotrack',
              'livedata', 'telegram', 'fleet', 'subnt', 'specs', 'operator_docs')


class WorkerBlocked(RuntimeError):
    """The candidate must not proceed to publication."""


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def request_wire(payload):
    """Match HermesBroker/infer_json spacing; canonical remains hash-only."""
    return json.dumps(payload, allow_nan=False).encode()


def tracked_paths(root):
    output = subprocess.check_output(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
        '-c', 'core.fsmonitor=false', '-C', str(root), 'ls-files', '-z'], timeout=30,
        env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
             'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
             'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1'})
    return sorted(set(output.decode().rstrip('\0').split('\0')) - {''})


def safe_path(root, path, *, writable=False, new=False):
    if not isinstance(path, str) or not path or '\\' in path or any(ord(c) < 32 for c in path):
        raise WorkerBlocked('invalid path')
    parts = path.split('/')
    lower = path.lower()
    if any(p in ('', '.', '..') or p.startswith('.') for p in parts) or Path(path).is_absolute():
        raise WorkerBlocked('hidden or escaping path')
    if any(p.lower() in ('var', 'private', 'secrets', 'keys', 'output', 'outputs', 'node_modules', 'auth.json') for p in parts) or any(
        word in lower for word in ('secret', 'credential', 'id_rsa', 'id_ed25519')) or lower.endswith(('.pem', '.key', '.p12', '.pfx', '.db', '.sqlite', '.sqlite3')):
        raise WorkerBlocked('secret/state path')
    if writable and any(p.lower() in ('conftest.py', 'conftest.pyc', 'pytest.ini', '.pytest.ini',
            'pytest.toml', '.pytest.toml', 'pyproject.toml', 'setup.cfg', 'tox.ini',
            'pytest', 'pytest.py', 'pytest.pyc', '_pytest', '__pycache__',
            'sitecustomize', 'sitecustomize.py', 'sitecustomize.pyc',
            'usercustomize', 'usercustomize.py', 'usercustomize.pyc')
            for p in parts):
        raise WorkerBlocked('test harness policy path')
    if writable and (parts[0] == 'maintenance' or parts[-1] == 'AGENTS.md' or
        lower.startswith('openspec/changes/archive/') or
        (not new and lower.startswith('docs/runtime-upgrades/'))):
        raise WorkerBlocked('policy or immutable history path')
    target = Path(root)
    for part in parts:
        target = target / part
        if target.is_symlink():
            raise WorkerBlocked('symlink path')
    return target


def preflight_file(root, path, inventory, max_bytes):
    """Check metadata only, before any member of a requested batch is opened."""
    if not isinstance(path, str) or path not in inventory:
        raise WorkerBlocked('untracked file request')
    target = safe_path(root, path)
    try:
        if not target.is_file() or target.stat().st_nlink != 1:
            raise WorkerBlocked('not a regular private file')
        if target.stat().st_size > max_bytes:
            raise WorkerBlocked('file budget exceeded or binary file')
    except OSError as exc:
        raise WorkerBlocked('unreadable text file') from exc
    return target


def requestable_inventory(root, inventory, max_bytes):
    result = []
    for path in inventory:
        try:
            preflight_file(root, path, inventory, max_bytes)
        except WorkerBlocked:
            continue
        result.append(path)
    return result


def request_error(path, reason, inventory):
    # Never echo arbitrary model strings, control characters or credential tokens.
    label = path if isinstance(path, str) and path in inventory else '<unavailable>'
    label = re.sub(r'[^A-Za-z0-9_./ -]', '?', label)[:160]
    label = re.sub(r'(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]+', '<redacted>', label)
    return {'path': label, 'reason': reason}


def requested_files(root, response, inventory, max_bytes):
    """All-or-nothing read: errors contain only sanitized paths/static reasons."""
    paths = response.get('paths')
    if (not isinstance(paths, list) or not paths or len(paths) > 64 or
            any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths)):
        return None, [{'path': '<request>', 'reason': 'invalid file request; use 1-64 unique paths'}]
    errors = []
    for path in paths:
        try:
            preflight_file(root, path, inventory, max_bytes)
        except WorkerBlocked as exc:
            errors.append(request_error(path, str(exc), inventory))
    if errors:
        return None, errors
    window = {}
    for path in paths:
        try:
            window[path] = read_text(root, path, inventory=inventory, max_bytes=max_bytes)
        except WorkerBlocked as exc:
            errors.append(request_error(path, str(exc), inventory))
    return (None, errors) if errors else (window, [])


def request_metadata(payload, requestable, feedback, max_file_bytes, limit):
    """Annotate exact wire usage (including this annotation) and recovery reserve."""
    payload['requestable_inventory'] = requestable
    payload['request_feedback'] = feedback
    payload['request_limits'] = {
        'max_file_bytes': max_file_bytes, 'max_paths': 64, 'max_context_bytes': limit,
        'feedback_reserve_bytes': 24000,
        'limitations': 'inventory and inventory_groups are FULL evidence, not read permission. '
            'Request only requestable_inventory paths; metadata eligibility is conditional on UTF-8, '
            'binary and credential screening. Hidden, secret/state, symlink, untracked and nonregular '
            'paths are denied. No partial batches or truncation. Correct a rejected request with a '
            'valid smaller batch before finalizing. Each request consumes a round. Requests replace '
            'the window. The next serialized payload including evidence, diffs and inspected hashes '
            'must fit max_context_bytes minus feedback_reserve_bytes. Never infer missing contents.',
        'serialized_payload_bytes': 0}
    while True:
        size = len(request_wire(payload))
        if payload['request_limits']['serialized_payload_bytes'] == size:
            return payload
        payload['request_limits']['serialized_payload_bytes'] = size


def fit_request(payload, candidate, errors, requestable, max_file_bytes, limit, *,
                inspected=None, version=None):
    if errors:
        return {'status': 'rejected', 'errors': errors}
    trial = {**payload, 'files': candidate}
    if inspected is not None:
        trial['inspected_files'] = {**inspected, **{p: f['sha256'] for p, f in candidate.items()}}
    if version is not None:
        trial['file_version'] = version
    request_metadata(trial, requestable, None, max_file_bytes, limit)
    if len(request_wire(trial)) > limit - trial['request_limits']['feedback_reserve_bytes']:
        return {'status': 'rejected', 'errors': [{'path': '<request>',
            'reason': 'context budget exceeded; request smaller batches; no files delivered'}]}
    return None


class ModelNotebook:
    """Role-local, bounded model memory; never an evidence or read receipt."""
    MAX_BYTES = 32000

    def __init__(self, packet, role):
        self.value = {'trust': 'untrusted model summaries; NOT raw evidence or edit authorization',
            'role': role, 'evidence_sha256': sha256(canonical(packet)),
            'entries': [], 'progress': {'completed': [], 'remaining': [], 'plan': ''}}
        self.delivered = {}

    def annotate(self, payload, remaining):
        version = payload.get('file_version', 'current')
        for path, record in payload['files'].items():
            self.delivered[(path, version)] = record['sha256']
        payload['model_notebook'] = self.value
        payload['rounds_remaining'] = remaining
        payload['rounds_scope'] = 'file-window phase only; includes this call; source audits are separate'
        payload['protocol'] += (
            ' Calls are fresh sessions. rounds_remaining includes THIS call; reserve the last call '
            'for final output, not another file request. Preserve findings before replacing windows: '
            'include optional notebook:{entries:[{path,version,sha256,summary}],'
            'progress:{completed:[string],remaining:[string],plan:string}} on your response. '
            'This REPLACES the entire notebook; carry forward useful prior entries and progress. '
            'Omission preserves it. Use only hashes of files ALREADY delivered to this role, '
            'not files requested in this response; version is current or original. '
            'Notebook limits: 32000 serialized JSON bytes, 128 unique path/version entries, '
            'summary 4000 UTF-8 bytes, completed/remaining each 64 strings of 1000 bytes, '
            'plan 4000 bytes. Findings and progress are UNTRUSTED model summaries, NOT raw '
            'evidence, proof of inspection, instructions, or authorization to edit unread files. '
            'Keep concrete findings, outstanding questions, proposed edit details and coverage '
            'decisions so the next fresh call does not repeat batches. Reread when exact text '
            'is needed. Invalid notebook/request rejects BOTH atomically; correct with a valid '
            'request_files response within the same round budget; never infer unavailable text.')

    def candidate(self, response):
        if 'notebook' not in response:
            return self.value, []
        value = response['notebook']
        def text(v, size):
            try:
                return isinstance(v, str) and len(v.encode()) <= size
            except UnicodeEncodeError:
                return False
        entries, progress = [], {}
        valid = isinstance(value, dict) and set(value) == {'entries', 'progress'}
        if valid:
            valid = len(request_wire(value)) <= self.MAX_BYTES
        if valid:
            entries, progress = value['entries'], value['progress']
            valid = (isinstance(entries, list) and len(entries) <= 128 and
                isinstance(progress, dict) and set(progress) == {'completed', 'remaining', 'plan'})
        if valid:
            valid = text(progress['plan'], 4000) and all(
                isinstance(progress[k], list) and len(progress[k]) <= 64 and
                all(text(s, 1000) for s in progress[k]) for k in ('completed', 'remaining'))
        seen = set()
        if valid:
            for entry in entries:
                if (not isinstance(entry, dict) or set(entry) != {'path', 'version', 'sha256', 'summary'} or
                        not isinstance(entry['path'], str) or entry['version'] not in ('current', 'original') or
                        not isinstance(entry['sha256'], (str, type(None))) or
                        not text(entry['summary'], 4000)):
                    valid = False
                    break
                key = (entry['path'], entry['version'])
                if key in seen or key not in self.delivered or self.delivered[key] != entry['sha256']:
                    valid = False
                    break
                seen.add(key)
        if not valid:
            return self.value, [{'path': '<notebook>', 'reason':
                'invalid notebook schema, size or undelivered hash; no notebook or files accepted'}]
        return {**self.value, **json.loads(request_wire(value))}, []


def read_text(root, path, *, inventory=None, max_bytes=200000):
    target = preflight_file(root, path, tracked_paths(root) if inventory is None else inventory, max_bytes)
    try:
        with target.open('rb') as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes or b'\0' in data:
            raise WorkerBlocked('file budget exceeded or binary file')
        text = data.decode('utf-8')
        if re.search(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}', text):
            raise WorkerBlocked('credential material in tracked text')
    except (OSError, UnicodeError) as exc:
        raise WorkerBlocked('unreadable text file') from exc
    return {'content': text, 'sha256': sha256(data)}


def check_packet(packet):
    if packet.get('complete') is not True or packet.get('status', 'ready') != 'ready' or packet.get('blocked_reasons'):
        raise WorkerBlocked('incomplete source evidence')
    chunks = packet.get('chunks', [])
    ids = [c['id'] for c in chunks]
    if not ids or len(ids) != len(set(ids)) or sorted(ids) != sorted(packet.get('chunk_ids', [])):
        raise WorkerBlocked('incomplete chunk manifest')
    if set(c['path'] for c in chunks) != set(packet.get('upstream_paths', [])):
        raise WorkerBlocked('incomplete source path coverage')
    if any(sha256(c['text'].encode()) != c['sha256'] for c in chunks):
        raise WorkerBlocked('evidence chunk hash mismatch')


def inventory_groups(inventory, packet):
    groups = {}
    for path in inventory:
        group = path.split('/', 1)[0] if '/' in path else 'root'
        groups.setdefault(group, []).append(path)
    for group, record in packet.get('atlas_inventory', {}).get('subsystems', {}).items():
        groups[group] = sorted(set(groups.get(group, [])) | set(record.get('paths', [])))
    return groups


def check_dispositions(response, packet, groups=None):
    if sorted(response.get('covered_chunks', [])) != sorted(packet['chunk_ids']):
        raise WorkerBlocked('incomplete chunk review')
    required = [('upstream', packet['upstream_paths']), ('subsystems', SUBSYSTEMS)]
    if groups is not None:
        required.append(('inventory_groups', groups))
    for field, expected in required:
        records = response.get(field, {})
        if set(records) != set(expected):
            raise WorkerBlocked('incomplete ' + field + ' review')
        for record in records.values():
            if record.get('disposition') not in ('update_required', 'no_impact') or not record.get('evidence'):
                raise WorkerBlocked('unsupported or blocked disposition')


def snapshot_tree(root, *, max_bytes=64000000, extra_paths=()):
    """Hash every tracked regular file locally; never send this inventory's bytes."""
    import stat
    result = {}
    total = 0
    for path in sorted(set(tracked_paths(root)) | set(extra_paths)):
        # Restricted files stay outside the worker's scope. Validator rejects
        # publication of them independently; do not open their contents here.
        try:
            target = safe_path(root, path)
        except WorkerBlocked:
            result[path] = 'restricted'
            continue
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise WorkerBlocked('nonregular tracked file')
        digest = hashlib.sha256()
        with target.open('rb') as stream:
            while data := stream.read(1048576):
                total += len(data)
                if total > max_bytes:
                    raise WorkerBlocked('candidate snapshot budget exceeded')
                digest.update(data)
        result[path] = [digest.hexdigest(), info.st_mode & 0o777]
    return result


def model_call(model, payload, limit):
    """Bound actual serialized requests and responses, using fresh payloads."""
    wire = request_wire(payload)
    if len(wire) > min(limit, 800000):
        raise WorkerBlocked('context budget exceeded; incomplete review forbidden')
    response = model(json.loads(wire))
    if not isinstance(response, dict) or len(canonical(response)) > limit:
        raise WorkerBlocked('invalid or oversized model response')
    return response


def source_audits(packet, model, role, limit, source_bytes=120000):
    """Deliver every raw chunk exactly once before any summary-only final gate.

    Small packets retain the single-call protocol (raw evidence in every gate).
    Receipts are controller-built, never accepted from the final model response.
    Each call is independent: neither prior conversation nor coder receipts enter
    a reviewer audit. Hashes bind the actual delivered bytes and exact response.
    """
    if len(canonical(packet)) <= source_bytes:
        return packet, []
    original_hash = sha256(canonical(packet))
    context = {k: v for k, v in packet.items() if k not in ('chunks', 'atlas_inventory')}
    if 'atlas_inventory' in packet:
        atlas = packet['atlas_inventory']
        paths = list(dict.fromkeys([f['path'] for f in atlas.get('files', [])] +
            [p for record in atlas.get('subsystems', {}).values() for p in record.get('paths', [])]))
        indices = {p: i for i, p in enumerate(paths)}
        context['atlas_inventory'] = {
            **{k: v for k, v in atlas.items() if k not in ('files', 'subsystems')},
            'view': 'path-manifest', 'sha256': sha256(canonical(atlas)),
            'full_path_manifest': paths,
            'subsystems': {name: {**{k: v for k, v in record.items() if k != 'paths'},
                'path_indices': [indices[p] for p in record.get('paths', [])]}
                for name, record in atlas.get('subsystems', {}).items()}}
    context['original_packet_sha256'] = original_hash
    groups, batch, size = [], [], 0
    for chunk in packet['chunks']:
        chunk_size = len(chunk['text'].encode())
        if chunk_size > source_bytes:
            raise WorkerBlocked('single source chunk exceeds audit budget')
        if batch and size + chunk_size > source_bytes:
            groups.append(batch)
            batch, size = [], 0
        batch.append(chunk)
        size += chunk_size
    if batch:
        groups.append(batch)
    receipts, delivered = [], []
    for index, chunks in enumerate(groups):
        payload = {'role': role, 'phase': 'source-audit', 'batch_index': index,
            'batch_count': len(groups), 'evidence_context': context, 'chunks': chunks,
            'protocol': 'Independently inspect ALL supplied raw source chunks. Identify migrations, '
                'activation semantics, changed APIs, consumer impact, tests and documentation implications. '
                'Return EXACTLY {action:source_audit,covered_chunks:[{id,sha256}],summary:string}. '
                'Echo every supplied chunk id/hash exactly once, in supplied order. Summary must contain '
                'specific findings with chunk/path references, including risks and follow-up file inspections. '
                'Maximum summary UTF-8 bytes: 16000. This is a source audit, not final approval.'}
        response = model_call(model, payload, limit)
        expected = [{'id': c['id'], 'sha256': c['sha256']} for c in chunks]
        if (set(response) != {'action', 'covered_chunks', 'summary'} or
                response.get('action') != 'source_audit' or response.get('covered_chunks') != expected or
                not isinstance(response.get('summary'), str) or not response['summary'].strip() or
                len(response['summary'].encode()) > 16000):
            raise WorkerBlocked('invalid source audit coverage or schema')
        delivered.extend(c['id'] for c in chunks)
        receipts.append({'role': role, 'batch_index': index,
            'original_packet_sha256': original_hash, 'request_sha256': sha256(canonical(payload)),
            'response_sha256': sha256(canonical(response)), 'covered_chunks': expected,
            'summary_trust': 'untrusted-model-findings; NOT raw evidence',
            'summary': response['summary']})
    if delivered != [c['id'] for c in packet['chunks']] or len(set(delivered)) != len(delivered):
        raise WorkerBlocked('controller source audit coverage mismatch')
    return {**context, 'view': 'source-audit-summaries',
        'chunks': [{k: v for k, v in c.items() if k != 'text'} for c in packet['chunks']],
        'source_audits': receipts}, receipts


def audit_result(receipts):
    return {'source_audit_receipts': receipts,
            'source_audit_coverage_count': sum(len(r['covered_chunks']) for r in receipts)}


def proposal_diffs(proposal):
    import difflib
    result = {}
    for edit in proposal['edits']:
        path = edit['path']
        lines = difflib.unified_diff(
            (proposal['before_files'][path]['content'] or '').splitlines(keepends=True),
            edit['content'].splitlines(keepends=True), fromfile='a/' + path, tofile='b/' + path)
        result[path] = ''.join(line if line.endswith('\n') else
            line + '\n\\ No newline at end of file\n' for line in lines)
    return result


def propose(root, packet, model, *, selected_paths=(), max_rounds=8,
            max_context_bytes=800000, max_file_bytes=200000, max_edit_bytes=200000,
            max_materialized_bytes=2000000):
    check_packet(packet)
    baseline_snapshot = snapshot_tree(root)
    inventory = tracked_paths(root)
    files = {p: read_text(root, p, inventory=inventory, max_bytes=max_file_bytes) for p in selected_paths}
    window = dict(files)
    evidence, receipts = source_audits(packet, model, 'coding-worker', max_context_bytes)
    requestable = requestable_inventory(root, inventory, max_file_bytes)
    feedback = None
    notebook = ModelNotebook(packet, 'coding-worker')
    for round_index in range(max_rounds):
        payload = {'role': 'coding-worker', 'protocol':
            'Return {action:request_files,paths:[requestable_inventory paths]} to inspect more text. '
            'Each request replaces the file window; previously inspected hashes remain available. '
            'or {action:propose,edits:[{path,before_sha256,content}],covered_chunks:[ids],'
            'upstream:{path:{disposition,evidence}},subsystems:{name:{disposition,evidence}},'
            'inventory_groups:{group:{disposition,evidence}}}. '
            'Also cover EVERY inventory_groups key, not only the fixed subsystem list. '
            'Dispositions: update_required, no_impact, blocked. Every upstream path and subsystem '
            'requires an evidence reference. before_sha256 must equal the inspected file hash; '
            'use null ONLY for a new absent regular file (including new tests/reports). '
            'For existing inspected files prefer {path,before_sha256,replacements:[{old,new}]} '
            'instead of content. Each nonempty old must occur exactly once in the original file; '
            'replacements must not overlap and are applied simultaneously. Never return commands.',
            'evidence': evidence, 'inventory': inventory, 'files': window,
            'inspected_files': {p: f['sha256'] for p, f in files.items()},
            'required_subsystems': list(SUBSYSTEMS), 'inventory_groups': inventory_groups(inventory, packet)}
        notebook.annotate(payload, max_rounds - round_index)
        request_metadata(payload, requestable, feedback, max_file_bytes, max_context_bytes)
        response = model_call(model, payload, max_context_bytes)
        next_notebook, note_errors = notebook.candidate(response)
        if note_errors:
            feedback = {'status': 'rejected', 'errors': note_errors}
            continue
        if response.get('action') == 'request_files':
            candidate, errors = requested_files(root, response, inventory, max_file_bytes)
            feedback = fit_request({**payload, 'model_notebook': next_notebook}, candidate, errors, requestable, max_file_bytes,
                max_context_bytes, inspected=payload['inspected_files'])
            if feedback is None:
                assert candidate is not None
                notebook.value = next_notebook
                window = candidate
                files.update(window)
                feedback = None
            continue
        if feedback is not None:
            raise WorkerBlocked('unresolved rejected file request')
        if response.get('action') != 'propose':
            raise WorkerBlocked('unknown protocol action')
        check_dispositions(response, packet, payload['inventory_groups'])
        edits = response.get('edits')
        if not isinstance(edits, list) or len(edits) > 64:
            raise WorkerBlocked('invalid edits')
        if len(canonical(edits)) > max_edit_bytes:
            raise WorkerBlocked('edit budget exceeded')
        seen = set()
        materialized = 0
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) not in (
                    {'path', 'before_sha256', 'content'}, {'path', 'before_sha256', 'replacements'}):
                raise WorkerBlocked('invalid edit schema')
            path = edit['path']
            is_new = edit['before_sha256'] is None
            target = safe_path(root, path, writable=True, new=is_new)
            if path in seen:
                raise WorkerBlocked('duplicate edit')
            seen.add(path)
            if is_new:
                if path in inventory or target.exists():
                    raise WorkerBlocked('new file is not absent')
                files[path] = {'content': None, 'sha256': None}
            elif path not in files or edit['before_sha256'] != files[path]['sha256'] or read_text(root, path)['sha256'] != edit['before_sha256']:
                raise WorkerBlocked('unread or stale edit hash')
            if 'replacements' in edit:
                replacements = edit['replacements']
                if is_new or not isinstance(replacements, list) or not replacements:
                    raise WorkerBlocked('invalid replacements')
                original = files[path]['content']
                spans = []
                for replacement in replacements:
                    if (not isinstance(replacement, dict) or set(replacement) != {'old', 'new'} or
                            not all(isinstance(replacement[k], str) for k in ('old', 'new')) or
                            not replacement['old'] or original.count(replacement['old']) != 1):
                        raise WorkerBlocked('replacement old substring must be unique')
                    start = original.index(replacement['old'])
                    if original.find(replacement['old'], start + 1) != -1:
                        raise WorkerBlocked('replacement old substring must be unique')
                    spans.append((start, start + len(replacement['old']), replacement['new']))
                spans.sort()
                if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
                    raise WorkerBlocked('overlapping replacements')
                content = original
                for start, end, new in reversed(spans):
                    content = content[:start] + new + content[end:]
                edit.pop('replacements')
                edit['content'] = content
            if not isinstance(edit['content'], str):
                raise WorkerBlocked('invalid edit content')
            size = len(edit['content'].encode())
            materialized += size
            if size > max_file_bytes or materialized > max_materialized_bytes or '\0' in edit['content']:
                raise WorkerBlocked('edit budget exceeded or binary content')
        manifest = {e['path']: {'before_sha256': e['before_sha256'],
            'after_sha256': sha256(e['content'].encode())} for e in response['edits']}
        return {**response, **audit_result(receipts), 'manifest': manifest, 'baseline_snapshot': baseline_snapshot,
                'before_files': {p: files[p] for p in manifest},
                'manifest_sha256': sha256(canonical(manifest)),
                'evidence_sha256': sha256(canonical(packet))}
    raise WorkerBlocked('file-request iteration budget exhausted')


def verify_manifest(proposal):
    edits = proposal['edits']
    manifest = {e['path']: {'before_sha256': e['before_sha256'],
        'after_sha256': sha256(e['content'].encode())} for e in edits}
    if len(manifest) != len(edits) or manifest != proposal['manifest'] or sha256(canonical(manifest)) != proposal['manifest_sha256']:
        raise WorkerBlocked('proposal manifest mismatch')
    for path, record in manifest.items():
        content = proposal['before_files'][path]['content']
        actual = None if content is None else sha256(content.encode())
        if actual != record['before_sha256']:
            raise WorkerBlocked('original text hash mismatch')
    return manifest


def apply_proposal(root, proposal):
    """Apply explicit regular files after validating ALL old hashes/absences.

    Caller must hold an exclusive candidate lock and discard the candidate after
    ANY exception (multi-file writes are not a filesystem transaction). No git,
    hooks, tests, commands, or model code are executed here.
    """
    import os
    import tempfile
    manifest = verify_manifest(proposal)
    inventory = tracked_paths(root)
    for path, record in manifest.items():
        is_new = record['before_sha256'] is None
        target = safe_path(root, path, writable=True, new=is_new)
        if is_new:
            if target.exists() or path in inventory:
                raise WorkerBlocked('new file appeared before apply')
        elif read_text(root, path, inventory=inventory)['sha256'] != record['before_sha256']:
            raise WorkerBlocked('candidate changed before apply')
    for edit in proposal['edits']:
        is_new = edit['before_sha256'] is None
        target = safe_path(root, edit['path'], writable=True, new=is_new)
        mode = 0o644 if is_new else target.stat().st_mode & 0o777
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.atlas-edit-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(edit['content'].encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        if sha256(target.read_bytes()) != manifest[edit['path']]['after_sha256']:
            raise WorkerBlocked('candidate write verification failed')
    return manifest


def review_proposal(root, packet, proposal, model, *, tree, checks, worker_id,
                    reviewer_id, max_rounds=8, max_context_bytes=800000):
    """Independent fresh-session review, bound to exact edits, evidence and tree.

    tree/checks are TRUSTED harness inputs, not model claims. The publisher's
    validate_candidate must verify tree against the committed candidate and run
    every mandatory check. Evidence bytes for that API are canonical(packet).
    A review uses no coder conversation or reasoning, only original/new text.
    """
    check_packet(packet)
    manifest = verify_manifest(proposal)
    new_paths = {p for p, value in manifest.items() if value['before_sha256'] is None}
    current = snapshot_tree(root, extra_paths=new_paths)
    baseline = proposal['baseline_snapshot']
    if set(current) != set(baseline) | new_paths or any(current[p] != baseline[p] for p in current if p not in manifest):
        raise WorkerBlocked('unreviewed file changes outside manifest')
    if not worker_id or not reviewer_id or worker_id == reviewer_id:
        raise WorkerBlocked('review must be independent')
    if proposal['evidence_sha256'] != sha256(canonical(packet)):
        raise WorkerBlocked('evidence changed before review')
    if not checks or any(value != 'passed' for value in checks.values()):
        raise WorkerBlocked('tests/checks did not pass')
    inventory = sorted(set(tracked_paths(root)) | new_paths)
    files = {p: read_text(root, p, inventory=inventory) for p in manifest}
    if any(files[p]['sha256'] != manifest[p]['after_sha256'] for p in manifest):
        raise WorkerBlocked('candidate changed before review')
    files = {}
    file_version = 'current'
    evidence, receipts = source_audits(packet, model, 'independent-reviewer', max_context_bytes)
    requestable = requestable_inventory(root, inventory, 200000)
    feedback = None
    notebook = ModelNotebook(packet, 'independent-reviewer')
    for round_index in range(max_rounds):
        payload = {'role': 'independent-reviewer', 'protocol':
            'Independently audit ALL source chunks, migrations, activation semantics, '
            'consumer impact, code/docs consistency and test evidence. Do not trust the coder. '
            'Return {action:request_files,paths:[requestable_inventory paths],version:current|original} for full text '
            '(default current). Requests replace the current file window, not accumulate it. Or return '
            '{action:review,approved:bool,manifest_sha256:exact supplied hash,tree:exact supplied tree,'
            'covered_chunks:[all ids],upstream:{path:{disposition,evidence}},'
            'subsystems:{name:{disposition,evidence}},inventory_groups:{group:{disposition,evidence}},'
            'checks:exact supplied check results}. Cover EVERY inventory_groups key. '
            'Dispositions are update_required (confirmed updated), no_impact, blocked.',
            'tree': tree, 'checks': checks, 'manifest': manifest,
            'manifest_sha256': proposal['manifest_sha256'], 'diffs': proposal_diffs(proposal),
            'evidence': evidence,
            'inventory': inventory, 'files': files, 'file_version': file_version,
            'required_subsystems': list(SUBSYSTEMS),
            'inventory_groups': inventory_groups(inventory, packet)}
        notebook.annotate(payload, max_rounds - round_index)
        request_metadata(payload, requestable, feedback, 200000, max_context_bytes)
        if len(request_wire(payload)) > max_context_bytes:
            raise WorkerBlocked('review context budget exceeded')
        result = model_call(model, payload, max_context_bytes)
        next_notebook, note_errors = notebook.candidate(result)
        if note_errors:
            feedback = {'status': 'rejected', 'errors': note_errors}
            continue
        if result.get('action') == 'request_files':
            version = result.get('version', 'current')
            if version not in ('current', 'original'):
                feedback = {'status': 'rejected', 'errors': [{'path': '<request>',
                    'reason': 'invalid review file version; use current or original'}]}
                continue
            candidate, errors = requested_files(root, result, inventory, 200000)
            if not errors and version == 'original':
                assert candidate is not None
                candidate = {p: proposal['before_files'][p] if p in manifest else f
                             for p, f in candidate.items()}
            feedback = fit_request({**payload, 'model_notebook': next_notebook}, candidate, errors, requestable, 200000,
                max_context_bytes, version=version)
            if feedback is None:
                notebook.value = next_notebook
                files = candidate
                file_version = version
            continue
        if feedback is not None:
            raise WorkerBlocked('unresolved rejected review file request')
        if (result.get('action') != 'review' or result.get('approved') is not True or
            result.get('manifest_sha256') != proposal['manifest_sha256'] or
            result.get('tree') != tree or result.get('checks') != checks):
            raise WorkerBlocked('review rejected or not bound to candidate/checks')
        check_dispositions(result, packet, payload['inventory_groups'])
        for field in ('upstream', 'subsystems', 'inventory_groups'):
            for record in result[field].values():
                if record['disposition'] == 'update_required':
                    record['disposition'] = 'updated'
        return {**result, **audit_result(receipts), 'worker': worker_id, 'reviewer': reviewer_id,
                'evidence_sha256': proposal['evidence_sha256']}
    raise WorkerBlocked('review iteration budget exhausted')


def run_isolated_tests(root, *, python_args, venv, cwd='.', timeout=180, proposal=None,
                       max_snapshot_bytes=64000000, max_output_bytes=1000000):
    """Run TRUSTED harness-selected Python tests in networkless bubblewrap.

    Never supply python_args from model output. The test venv must be dedicated
    and credential-free. Only filtered tracked text is copied; no .git, HOME,
    credentials, production state or live checkout is mounted. Candidate and
    dependencies are read-only. /tmp and /run are private scratch. Missing
    bwrap or namespace support is a hard failure, never an unsandboxed fallback.
    """
    import os
    import signal
    import tempfile
    if cwd != '.':
        safe_path(root, cwd)
    inventory = tracked_paths(root)
    if proposal is not None:
        manifest = verify_manifest(proposal)
        inventory = sorted(set(inventory) | set(manifest))
        for path, record in manifest.items():
            if read_text(root, path, inventory=inventory)['sha256'] != record['after_sha256']:
                raise WorkerBlocked('test candidate differs from manifest')
    with tempfile.TemporaryDirectory(prefix='atlas-tests-') as directory:
        snapshot = Path(directory) / 'candidate'
        snapshot.mkdir()
        total = 0
        excluded = []
        for path in inventory:
            try:
                data = read_text(root, path, inventory=inventory, max_bytes=4000000)['content'].encode()
            except WorkerBlocked:
                excluded.append(path)
                continue  # exclusions are reported; caller must gate required suite inputs
            total += len(data)
            if total > max_snapshot_bytes:
                raise WorkerBlocked('test snapshot budget exceeded')
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
            '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/run',
            '--ro-bind', str(Path(venv).resolve()), '/venv',
            '--ro-bind', str(snapshot), '/candidate', '--chdir', '/candidate' + ('' if cwd == '.' else '/' + cwd),
            '--clearenv', '--setenv', 'HOME', '/tmp', '--setenv', 'PATH', '/venv/bin:/usr/bin:/bin',
            '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', '--setenv', 'PYTHONNOUSERSITE', '1',
            '/usr/bin/prlimit', '--as=2147483648', '--cpu=' + str(max(1, int(timeout))),
            '--fsize=' + str(max_output_bytes), '--nofile=128', '--nproc=128', '--', '/venv/bin/python', *python_args]
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                stderr=errors, env={'PATH': '/usr/bin:/bin'}, start_new_session=True)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise WorkerBlocked('isolated test deadline exceeded') from exc
            output.seek(0)
            errors.seek(0)
            stdout, stderr = output.read(max_output_bytes + 1), errors.read(max_output_bytes + 1)
            if len(stdout) > max_output_bytes or len(stderr) > max_output_bytes:
                raise WorkerBlocked('test output budget exceeded')
            return {'returncode': process.returncode, 'stdout': stdout.decode(errors='replace'),
                    'stderr': stderr.decode(errors='replace'), 'isolated': True, 'excluded_paths': excluded}
