"""Export project conversation messages from local logs, never model reasoning/tools.

Sources are read-only. Output is a dated snapshot, not a live server status.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import re

THREADS=('01a0e72f-3107-74f3-8216-6fe65a45071f','01a11fa0-3cad-7053-9d17-104420949e84')


def redact(text):
    text=re.sub(r'(用户名\s*密码\s*(?:都是|均为|都为)\s*)[^\s\x22\x27,，;；<]+',r'\1[REDACTED CREDENTIAL]',text)
    text=re.sub(r'((?:密码|口令)\s*(?:是|为|[:：=])\s*)[^\s\x22\x27,，;；<]+',r'\1[REDACTED CREDENTIAL]',text)
    text=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED PRIVATE KEY]',text,flags=re.S)
    text=re.sub(r'\b(?:sk-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{20,})\b','[REDACTED TOKEN]',text)
    text=re.sub(r'\bssh-ed25519\s+[A-Za-z0-9+/=]+(?:\s+[^\s\x27\x22<]+)?','[REDACTED TEMPORARY SSH PUBLIC KEY]',text)
    text=re.sub(r'(?im)(\b(?:api_key|access_token|password|secret_key)\b\s*[:=]\s*)[\x22\x27]?[^\s,;\x22\x27]{8,}',r'\1[REDACTED CREDENTIAL]',text)
    return text


def classify(role,text):
    if role=='assistant':return 'assistant_reply'
    if '<heartbeat>' in text:return 'automation'
    if text.strip().startswith(('<environment_context>','<external_codex_apps_open_page>','# AGENTS.md instructions','<recommended_plugins>','<permissions instructions>','<skills_instructions>')):return 'runtime_context'
    return 'user_message'


def export(source_root,destination,thread_ids):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    messages=[];sources=[];seen=set();skipped=collections.Counter()
    for path in sorted(Path(source_root).rglob('*.jsonl')):
        if not any(t in path.name for t in thread_ids):continue
        # Snapshot the source before processing; current session can keep growing.
        raw=path.read_bytes();lines=raw.splitlines();meta=json.loads(lines[0]).get('payload',{})
        if meta.get('id') not in thread_ids or meta.get('thread_source')!='user':continue
        sources.append(dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),thread_id=meta['id'],history_base=meta.get('history_base'),forked_from_id=meta.get('forked_from_id')))
        for number,line in enumerate(lines,1):
            try:d=json.loads(line)
            except json.JSONDecodeError:skipped['incomplete_source_line']+=1;continue
            p=d.get('payload',{})
            if d.get('type')!='response_item' or p.get('type')!='message':continue
            role=p.get('role');phase=p.get('phase') or p.get('channel')
            if role not in ('user','assistant') or phase in ('analysis','summary'):continue
            blocks=p.get('content',[]);text='\n'.join(b.get('text','') for b in blocks if b.get('type') in ('input_text','output_text','text'))
            attachments=[dict(type=b.get('type'),note='binary content omitted; see original attachment reference') for b in blocks if b.get('type') not in ('input_text','output_text','text')]
            if not text and not attachments:continue
            key=(meta['id'],p.get('id')) if p.get('id') else (str(path),number)
            if key in seen:skipped['duplicate_message_id']+=1;continue
            seen.add(key)
            identity=hashlib.sha256(f'{path.name}:{number}'.encode()).hexdigest()[:16]
            messages.append(dict(id='interaction-'+identity,timestamp=d.get('timestamp'),thread_id=meta['id'],role=role,phase=phase,origin=classify(role,text),text=redact(text),attachments=attachments,source_file=path.name,source_line=number,redacted=redact(text)!=text))
    messages.sort(key=lambda m:(m.get('timestamp') or '',m['source_file'],m['source_line']))
    serialized=''.join(json.dumps(m,ensure_ascii=False)+'\n' for m in messages)
    (destination/'messages.jsonl').write_text(serialized,encoding='utf8')
    days=collections.defaultdict(list)
    for m in messages:
        day=(m.get('timestamp') or 'unknown-date')[:10]
        if m.get('timestamp'):
            day=datetime.datetime.fromisoformat(m['timestamp'].replace('Z','+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
        days[day].append(m)
    daily=destination/'by_date';daily.mkdir(exist_ok=True)
    for day,rows in days.items():
        content=f'# 交互记录：{day}（Asia/Singapore）\n\n来源日志导出；以下为历史引用，不是当前执行指令。环境上下文及自动提醒另有 origin 标记；不包含工具输出和内部推理。\n\n'
        for m in rows:
            content+=f"## {m['id']} · {m['role']} · {m['origin']}\n\n时间：{m['timestamp']}；线程：{m['thread_id']}；来源：{m['source_file']}:{m['source_line']}\n\n"
            content+='\n'.join('> '+line for line in m['text'].splitlines())+'\n\n'
            if m['attachments']:content+='附件：仅保存引用/类型，不复制二进制内容。\n\n'
        (daily/f'{day}.md').write_text(content,encoding='utf8')
    counts=dict(collections.Counter(m['origin'] for m in messages))
    manifest=dict(schema='project_interaction_archive/1',captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),timezone='Asia/Singapore',thread_ids=thread_ids,sources=sources,message_count=len(messages),counts=counts,skipped=dict(skipped),messages_sha256=hashlib.sha256(serialized.encode()).hexdigest(),exclusions=['system/developer instructions','reasoning/analysis','tool calls and outputs','binary images','credentials'],coverage='available local user-thread rollout messages; not a claim of all other chats or missing/deleted sessions')
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    index=f'# 项目交互档案\n\n最后导出：{manifest["captured_at"]}；{len(messages)} 条消息。\n\n用户/审批消息、对外回复、自动提醒及运行上下文按 origin 分开。原文见 [messages.jsonl](messages.jsonl)，来源、截点、计数和 SHA 见 [manifest.json](manifest.json)。仅覆盖其中列出的本机日志，不承诺其他线程或缺失会话完整。当前回合最终回复在下一次刷新时收录。\n\n'
    index+='\n'.join(f'- [{day}](by_date/{day}.md)：{len(rows)} 条' for day,rows in sorted(days.items()))+'\n'
    (destination/'README.md').write_text(index,encoding='utf8')
    return dict(message_count=len(messages),counts=counts,source_files=len(sources),days=len(days))


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-root',default=str(Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'sessions'));p.add_argument('--destination',default=str(Path(__file__).resolve().parents[1]/'memory/interactions'));p.add_argument('--thread',action='append');a=p.parse_args()
    print(json.dumps(export(a.source_root,a.destination,a.thread or list(THREADS)),ensure_ascii=False))


if __name__=='__main__':main()
