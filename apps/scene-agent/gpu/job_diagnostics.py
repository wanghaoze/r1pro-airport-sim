"""Structured failures and log errors; originals stay intact for full download."""
import json
import re

def redact(text):
    text=re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~-]+',r'\1[REDACTED]',text)
    return re.sub(r'(?i)((?:api[_-]?key|access[_-]?token|worker[_-]?token|password|secret)\s*[=:]\s*)[^\s,;]+',r'\1[REDACTED]',text)

def diagnostics(run):
    rows=[]
    files=list(run.glob('*failure*.json'))+list((run/'native').glob('*failure*.json'))+list((run/'native/rooms').glob('*/failure.json'))+list((run/'policy').glob('*.error.json'))
    for path in files:
        text=path.read_text(errors='replace')
        rows.append(dict(source=str(path.relative_to(run)),text=redact(text),truncated=False))
    # Log tails include initialization/renderer errors which never make report.json.
    for name in ('runner.log','vla.log','native.log','policy.log','model_http.log','g05_server.log','ros2.log','train.log','prepare_sources.log','prepare_training.log','cpu_transform.log','mse_0.log','mse_1.log','mse_2.log','mse_3.log'):
        path=run/name
        if not path.is_file():continue
        size=path.stat().st_size
        with path.open('rb') as stream:
            stream.seek(max(0,size-65536));text=stream.read().decode('utf8',errors='replace')
        if text.strip():rows.append(dict(source=name,text=redact(text),truncated=size>65536,originalBytes=size))
        if size>65536:
            # Search the entire file so errors before the tail remain visible.
            selected=[];remaining=0
            with path.open(errors='replace') as stream:
                for line_number,line in enumerate(stream,1):
                    if re.search(r'error|exception|traceback|fatal|failed',line,re.I):remaining=12
                    if remaining:selected.append(f'{line_number}: {line.rstrip()}');remaining-=1
            if selected:rows.append(dict(source=name+' · error excerpts from full log',text=redact('\n'.join(selected)),truncated=False))
    return rows

def failure_details(run):
    """Full structured errors for every job kind, including training."""
    paths=list(run.glob('*failure*.json'))+list((run/'training').glob('*failure*.json'))
    return [dict(source=str(p.relative_to(run)),text=redact(p.read_text(errors='replace'))) for p in paths]
