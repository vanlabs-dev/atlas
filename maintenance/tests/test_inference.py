import json
import pytest
from maintenance import inference as i


class Agent:
    tools = []
    valid_tool_names = set()
    def __init__(self, **kwargs):
        self.kwargs = kwargs
    def run_conversation(self, user_message, **kwargs):
        assert self.compression_enabled is False
        return {'final_response': '{"ok":true}', 'messages': []}
    def close(self):
        pass


def test_tool_free_pinned_request():
    seen = []
    def factory(**kwargs):
        a = Agent(**kwargs)
        seen.append(a)
        return a
    assert i.infer_json({'task': 'smoke'}, agent_factory=factory) == {'ok': True}
    assert seen[0].kwargs['enabled_toolsets'] == []
    assert seen[0].kwargs['model'] == 'gpt-6-astra'
    assert seen[0].kwargs['provider'] == 'openai-codex'
    assert seen[0].kwargs['skip_memory'] is True
    assert seen[0].kwargs['skip_context_files'] is True


@pytest.mark.parametrize('case', ['tools', 'input', 'output', 'calls', 'list', 'duplicate'])
def test_inference_fails_closed(case):
    class Unsafe(Agent):
        tools = [{'function': {'name': 'terminal'}}] if case == 'tools' else []
        def run_conversation(self, *args, **kwargs):
            text = {'output': '{"large":"' + 'x' * 500 + '"}',
                    'list': '[]', 'duplicate': '{"a":1,"a":2}'}.get(case, '{"ok":true}')
            return {'final_response': text, 'messages':
                    [{'role': 'assistant', 'tool_calls': [{}]}] if case == 'calls' else []}
    with pytest.raises(i.InferenceError):
        i.infer_json({'x': 'x' * 50}, agent_factory=Unsafe,
            max_input_bytes=10 if case == 'input' else 1000, max_output_bytes=100)


def test_broker_runs_fixed_module_with_sanitized_environment(monkeypatch):
    import subprocess
    monkeypatch.setenv('GITHUB_TOKEN', 'must-not-inherit')
    captured = {}
    def run(command, **kwargs):
        captured.update(kwargs)
        captured['command'] = command
        return subprocess.CompletedProcess(command, 0, b'{"ok":true}', b'')
    broker = i.HermesBroker(python='/trusted/python', hermes_source='/trusted/hermes', runner=run)
    assert broker({'task': 'smoke'}) == {'ok': True}
    assert 'GITHUB_TOKEN' not in captured['env']
    assert captured['timeout'] <= 240
    assert captured['command'][0] == '/trusted/python'
    assert captured['cwd'] != '/home/pi/atlas'


@pytest.mark.parametrize('metadata', [
    {'completed': False}, {'failed': True}, {'partial': True},
    {'interrupted': True}, {'error': 'SECRET provider error'},
    {'completed': None}, {'failed': 'false'}, {'partial': 0},
    {'interrupted': []},
])
def test_unsafe_completion_rejected_even_with_valid_json(metadata):
    class Incomplete(Agent):
        def run_conversation(self, *args, **kwargs):
            return dict(super().run_conversation(*args, **kwargs), **metadata)
    with pytest.raises(i.InferenceError, match='completion') as error:
        i.infer_json({}, agent_factory=Incomplete)
    assert 'SECRET' not in str(error.value)


def test_retryable_rate_limit_is_classified_without_provider_text():
    class Limited(Agent):
        def run_conversation(self, *args, **kwargs):
            return {'final_response': 'API call failed after 3 retries: SECRET',
                    'messages': [], 'failed': True, 'completed': False,
                    'failure_reason': 'rate_limit', 'failure_retryable': True}
    with pytest.raises(i.InferenceError) as error:
        i.infer_json({}, agent_factory=Limited)
    assert error.value.diagnostic == {
        'version': 1, 'category': 'rate_limit', 'json_location': None}
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize('metadata', [
    {'failure_reason': 'rate_limit'},
    {'failure_reason': 'rate_limit', 'failure_retryable': False},
    {'failure_reason': 'rate_limit', 'failure_retryable': 1},
    {'failure_reason': 'rate_limit SECRET', 'failure_retryable': True},
    {'failure_reason': 'billing', 'failure_retryable': True},
    {'failure_retryable': True},
])
def test_untrusted_rate_limit_fields_stay_generic(metadata):
    class Limited(Agent):
        def run_conversation(self, *args, **kwargs):
            return {'final_response': 'SECRET provider body', 'messages': [],
                    'failed': True, **metadata}
    with pytest.raises(i.InferenceError) as error:
        i.infer_json({}, agent_factory=Limited)
    assert error.value.diagnostic['category'] == 'failed_completion'
    assert 'SECRET' not in str(error.value)


def test_captured_success_metadata_and_legacy_absence_accepted():
    # Metadata projection from failed-json/completion.json's real successful replay.
    # No response content or provider/user text is copied into this fixture.
    class Completed(Agent):
        def run_conversation(self, *args, **kwargs):
            return dict(super().run_conversation(*args, **kwargs), completed=True,
                        failed=False, partial=False, interrupted=False,
                        response_transformed=False, turn_exit_reason=None)
    assert i.infer_json({}, agent_factory=Completed) == {'ok': True}
    assert i.infer_json({}, agent_factory=Agent) == {'ok': True}


@pytest.fixture
def child_source(tmp_path):
    # Fake only the external Hermes installation; execute the real broker child.
    (tmp_path / 'model_tools.py').write_text('')
    (tmp_path / 'agent').mkdir()
    (tmp_path / 'agent' / '__init__.py').write_text('')
    (tmp_path / 'agent' / 'tool_executor.py').write_text('')
    def install(result=None, exception=None):
        body = ('raise RuntimeError(' + repr(exception) + ')' if exception else
                'return ' + repr(result))
        (tmp_path / 'run_agent.py').write_text(
            'import sys\nclass AIAgent:\n'
            ' tools = []\n valid_tool_names = set()\n'
            ' def __init__(self, **kwargs): pass\n'
            ' def close(self): pass\n'
            ' def run_conversation(self, *args, **kwargs):\n'
            '  print("SECRET stdout")\n'
            '  print("SECRET stderr", file=sys.stderr)\n  ' + body + '\n')
        return tmp_path
    return install


@pytest.mark.parametrize('response,metadata,category,location', [
    ('{\n"SECRET": }', {}, 'invalid_json', {'line': 2, 'column': 11, 'position': 12}),
    ('{}', {'completed': False}, 'incomplete_completion', None),
    ('{}', {'failed': True}, 'failed_completion', None),
    ('API call failed after 3 retries: SECRET',
     {'failed': True, 'failure_reason': 'rate_limit', 'failure_retryable': True,
      'completed': False}, 'rate_limit', None),
    ('{}', {'partial': True}, 'partial_completion', None),
    ('{}', {'interrupted': True}, 'interrupted_completion', None),
    ('{}', {'error': 'SECRET provider'}, 'completion_error', None),
    ('{"SECRET":1,"SECRET":2}', {}, 'duplicate_key', None),
    ('{"SECRET":NaN}', {}, 'nonfinite_json', None),
    ('[]', {}, 'nonobject_json', None),
    ('x' * 200001, {}, 'output_budget', None),
    ('{}', {'failed': True, 'completed': True}, 'failed_completion', None),
    ('{}', {'completed': None}, 'invalid_completion_metadata', None),
    ('{}', {'partial': 0}, 'invalid_completion_metadata', None),
    ('{}', {'failed': 'false'}, 'invalid_completion_metadata', None),
    ('```json\n{}\n```', {}, 'invalid_json', {'line': 1, 'column': 1, 'position': 0}),
    ('{} trailing', {}, 'invalid_json', {'line': 1, 'column': 4, 'position': 3}),
], ids=lambda value: str(value)[:60])
def test_child_failure_diagnostics_roundtrip(child_source, response, metadata, category, location):
    import subprocess
    import sys
    import traceback
    source = child_source(dict(final_response=response, messages=[], **metadata))
    captured = []
    def run(*args, **kwargs):
        result = subprocess.run(*args, **kwargs)
        captured.append(result)
        return result
    broker = i.HermesBroker(python=sys.executable, hermes_source=source, runner=run)
    payload = {'SECRET user': 'SECRET input'}
    with pytest.raises(i.InferenceError) as error:
        broker(payload)
    expected = {'version': 1, 'category': category, 'json_location': location}
    assert captured[0].returncode != 0
    assert json.loads(captured[0].stdout) == expected
    assert captured[0].stderr == b''
    assert len(captured) == 1
    assert error.value.diagnostic == expected
    assert category in str(error.value)
    assert 'SECRET' not in ''.join(traceback.format_exception(error.value))


def test_unknown_child_exception_is_generic(child_source):
    import sys
    import traceback
    source = child_source(exception='SECRET credentials and provider body')
    with pytest.raises(i.InferenceError) as error:
        i.HermesBroker(python=sys.executable, hermes_source=source)({})
    assert error.value.diagnostic == {
        'version': 1, 'category': 'broker_failed', 'json_location': None}
    assert 'SECRET' not in ''.join(traceback.format_exception(error.value))


@pytest.mark.parametrize('wire', [
    b'SECRET', b'{}', b'[]', b'null', b'\xff', b'x' * 1025,
    b'{"version":1,"category":"SECRET","json_location":null}',
    b'{"version":true,"category":"invalid_json","json_location":null}',
    b'{"version":1,"category":"invalid_json","json_location":null,"error":"SECRET"}',
    b'{"version":1,"category":"invalid_json","category":"broker_failed","json_location":null}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":true,"column":1,"position":0}}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":1,"column":1,"position":200001}}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":1,"column":NaN,"position":0}}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":1,"column":"SECRET","position":0}}',
    b'{"version":1,"category":"broker_failed","json_location":{"line":1,"column":1,"position":0}}',
    b'{"version":2,"category":"broker_failed","json_location":null}',
    b'{"version":1,"category":[],"json_location":null}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":0,"column":1,"position":0}}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":1,"column":2,"position":0}}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":1,"column":1,"position":-1}}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":1,"column":1,"position":0,"text":"SECRET"}}',
    b'{"version":1,"category":"invalid_json","json_location":{"line":1,"line":2,"column":1,"position":0}}',
    b'{"version":1,"category":"broker_failed","json_location":null} SECRET',
], ids=lambda value: repr(value)[:100])
def test_parent_rejects_untrusted_diagnostic_envelopes(wire):
    import subprocess
    import traceback
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, wire, b'SECRET stderr traceback')
    with pytest.raises(i.InferenceError) as error:
        i.HermesBroker(python='/trusted/python', hermes_source='/trusted/hermes', runner=run)({})
    assert error.value.diagnostic == {
        'version': 1, 'category': 'broker_failed', 'json_location': None}
    assert 'SECRET' not in ''.join(traceback.format_exception(error.value))


@pytest.mark.parametrize('wire', [b'{"SECRET":NaN}', b'{"SECRET":Infinity}',
                                 b'{"SECRET":1,"SECRET":2}', b'[]', b'\xffSECRET'])
def test_success_exit_still_requires_strict_bounded_json(wire):
    import subprocess
    import traceback
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, wire, b'SECRET stderr')
    with pytest.raises(i.InferenceError) as error:
        i.HermesBroker(python='/trusted/python', hermes_source='/trusted/hermes', runner=run)({})
    assert 'SECRET' not in ''.join(traceback.format_exception(error.value))
    assert error.value.__cause__ is None


def test_broker_does_not_retry_a_rate_limit_it_cannot_distinguish_from_a_plan_cap():
    import subprocess
    calls = []
    limited = b'{"version":1,"category":"rate_limit","json_location":null}'
    def run(*args, **kwargs):
        calls.append(kwargs['input'])
        if len(calls) == 1:
            return subprocess.CompletedProcess(args, 1, limited, b'SECRET usage limit')
        return subprocess.CompletedProcess(args, 0, b'{"ok":true}', b'')
    with pytest.raises(i.InferenceError) as error:
        i.HermesBroker(python='/trusted/python', hermes_source='/trusted/hermes',
                       runner=run)({'same': 'request'})
    assert error.value.diagnostic['category'] == 'rate_limit'
    assert calls == [calls[0]]
    assert 'SECRET' not in str(error.value)


def test_broker_does_not_retry_a_generic_failure():
    import subprocess
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        return subprocess.CompletedProcess(
            args, 1, b'{"version":1,"category":"failed_completion","json_location":null}',
            b'SECRET')
    with pytest.raises(i.InferenceError) as error:
        i.HermesBroker(python='/trusted/python', hermes_source='/trusted/hermes',
                       runner=run)({})
    assert error.value.diagnostic['category'] == 'failed_completion'
    assert calls == [1]
    assert 'SECRET' not in str(error.value)


def test_child_success_wire_unchanged(child_source):
    import sys
    source = child_source({'final_response': '{"ok":true}', 'messages': [],
                          'completed': True, 'failed': False, 'partial': False,
                          'interrupted': False, 'response_transformed': False,
                          'turn_exit_reason': None})
    assert i.HermesBroker(python=sys.executable, hermes_source=source)({}) == {'ok': True}


@pytest.mark.parametrize('messages', [[{'role': 'tool', 'content': 'SECRET'}],
                                     [{'tool_calls': [{'SECRET': 'SECRET'}]}]])
def test_child_tool_messages_still_denied(child_source, messages):
    import sys
    source = child_source({'final_response': '{}', 'messages': messages, 'completed': True})
    with pytest.raises(i.InferenceError) as error:
        i.HermesBroker(python=sys.executable, hermes_source=source)({})
    assert error.value.diagnostic['category'] == 'unexpected_tool_call'
    assert 'SECRET' not in str(error.value)


def test_output_cap_counts_utf8_bytes():
    class UnicodeResponse(Agent):
        def run_conversation(self, *args, **kwargs):
            return {'final_response': '{"a":"é"}', 'messages': []}
    with pytest.raises(i.InferenceError, match='output budget'):
        i.infer_json({}, agent_factory=UnicodeResponse, max_output_bytes=9)
    assert i.infer_json({}, agent_factory=UnicodeResponse, max_output_bytes=10) == {'a': 'é'}


def test_execution_guard_blocks_dispatch():
    with pytest.raises(i.InferenceError, match='disabled'):
        i.deny_tool_execution('terminal', {'command': 'false'})
