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


def test_execution_guard_blocks_dispatch():
    with pytest.raises(i.InferenceError, match='disabled'):
        i.deny_tool_execution('terminal', {'command': 'false'})
