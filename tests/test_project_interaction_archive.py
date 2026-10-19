import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('archive',Path(__file__).parents[1]/'scripts/export_project_interactions.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_credentials_and_temporary_key_redacted():
    raw='-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n-----END OPENSSH PRIVATE KEY-----\nssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest123 temporary\napi_key=sk-abcdefghijklmnopqrstuvwxyz'
    safe=module.redact(raw)
    assert 'secret\n' not in safe
    assert 'AAAAC3' not in safe
    assert 'abcdefghijklmnopqrstuvwxyz' not in safe
    assert '[REDACTED' in safe
    assert 'shortpass' not in module.redact('用户名密码都是shortpass')


def test_only_external_messages_with_provenance(tmp_path):
    src=tmp_path/'source';src.mkdir();thread='known-thread'
    def message(role,text,phase=None,id=None):return dict(type='response_item',timestamp='2026-10-09T00:01:00Z',payload=dict(type='message',role=role,phase=phase,id=id,content=[dict(type='input_text',text=text)]))
    records=[dict(type='session_meta',payload=dict(id=thread,thread_source='user')),
        message('user','actual user request',id='u1'),message('user','actual user request',id='u1'),
        message('assistant','public result','final_answer'),message('assistant','hidden reasoning','analysis'),
        message('developer','not an interaction'),message('user','<heartbeat>scheduled</heartbeat>'),
        message('user','<environment_context>metadata</environment_context>'),
        dict(type='response_item',payload=dict(type='custom_tool_call_output',output='secret tool output'))]
    path=src/f'rollout-{thread}.jsonl';path.write_text('\n'.join(json.dumps(r) for r in records)+'\n',encoding='utf8')
    dest=tmp_path/'export';result=module.export(src,dest,[thread])
    rows=[json.loads(line) for line in (dest/'messages.jsonl').read_text(encoding='utf8').splitlines()]
    assert result['message_count']==4
    assert result['counts']==dict(user_message=1,assistant_reply=1,automation=1,runtime_context=1)
    assert all(r['source_file']==path.name and r['source_line']>1 for r in rows)
    assert not any('hidden reasoning' in r['text'] or 'tool output' in r['text'] for r in rows)
    manifest=json.loads((dest/'manifest.json').read_text(encoding='utf8'))
    assert manifest['skipped']['duplicate_message_id']==1
    assert manifest['sources'][0]['bytes']==path.stat().st_size
    assert len(manifest['sources'][0]['sha256'])==64
    assert (dest/'by_date/2026-10-09.md').exists()


def test_other_threads_and_subagent_logs_excluded(tmp_path):
    for name,thread,source in [('wanted','wanted','user'),('wanted_agent','wanted','subagent'),('other','other','user')]:
        records=[dict(type='session_meta',payload=dict(id=thread,thread_source=source)),dict(type='response_item',payload=dict(type='message',role='user',content=[dict(type='input_text',text=name)]))]
        (tmp_path/f'{name}.jsonl').write_text('\n'.join(map(json.dumps,records)),encoding='utf8')
    result=module.export(tmp_path,tmp_path/'export',['wanted'])
    assert result['message_count']==1
    assert result['source_files']==1
