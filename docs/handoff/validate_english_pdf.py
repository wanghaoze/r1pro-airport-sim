"""Validate the generated English handover without executing project jobs."""
from __future__ import annotations
import ast
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import pdfplumber
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
NAME = 'R1Pro_Project_Review_and_Operations_Handover_EN'
PDF = ROOT / 'output/pdf' / (NAME + '.pdf')


def main():
    errors = []
    reader = PdfReader(PDF)
    texts = [p.extract_text() or '' for p in reader.pages]
    text = '\n'.join(texts)
    compact = re.sub(r'\s+', '', text)
    inventory = json.loads((ROOT/'runs/documentation_pdf_20261016/script_catalog.snapshot.json').read_text(encoding='utf8'))
    source = (ROOT/'docs/handoff/README_EN.md').read_text(encoding='utf8')
    build = json.loads((ROOT/'output/pdf'/(NAME+'.sources.json')).read_text(encoding='utf8'))
    for record in inventory['entries'] + inventory['configs']:
        if record['path'] not in compact:
            errors.append('Missing inventory path: '+record['path'])
    if any(len(t)<350 for t in texts): errors.append('Blank or very sparse page')
    restricted = [r'jump\s*host', r'bastion', r'ProxyCommand', r'ProxyJump',
                  r'\bEC2\b', r'experiments_ed25519', r'100%[A-Za-z]+',
                  r'password\s*[:=]\s*\S+', r'[\u4e00-\u9fff]', r'\ufffd']
    if any(re.search(pattern,text,re.I) for pattern in restricted):
        errors.append('Language, direct-access or sensitive-content check failed')
    if len(reader.pages) != build['pages']: errors.append('Page-count mismatch')
    if hashlib.sha256(PDF.read_bytes()).hexdigest()!=build['pdf_sha256']: errors.append('PDF hash mismatch')
    if hashlib.sha256(source.encode('utf8')).hexdigest()!=build['source_sha256']: errors.append('English source hash mismatch')
    for h in build['headings']:
        if re.sub(r'\s+','',h['heading']) not in re.sub(r'\s+','',texts[h['page']-1]):
            errors.append('Heading/page mismatch: '+h['heading'])
    bounds=[]
    with pdfplumber.open(PDF) as pdf:
        for i,p in enumerate(pdf.pages):
            bad=[c for c in p.chars if c['x0']<42 or c['x1']>p.width-42 or c['top']<17 or c['bottom']>p.height-15]
            if bad: bounds.append({'page':i+1,'count':len(bad)})
    if bounds: errors.append('Text outside expected page bounds')
    checked=[]
    for block in re.findall(r'```(?:bash|powershell)\n(.*?)```', source, re.S):
        for line in block.replace('\\\n',' ').splitlines():
            if line.lstrip().startswith('#'): continue
            m=re.search(r'(scripts/[\w_]+\.py)',line)
            if not m: continue
            path=ROOT/m.group(1)
            if not path.is_file(): errors.append('Missing command file: '+m.group(1));continue
            code=path.read_text(encoding='utf-8-sig')
            tree=ast.parse(code)
            flags=set(re.findall(r"['\"](--[a-zA-Z][a-zA-Z0-9-]*)['\"]",code))
            for n in ast.walk(tree):
                if not isinstance(n,ast.For): continue
                try: values=ast.literal_eval(n.iter)
                except (ValueError,TypeError): continue
                if isinstance(values,(list,tuple)) and all(isinstance(x,str) for x in values):
                    flags.update('--'+x for x in values)
            used=set(re.findall(r'(?<![\w/])--[A-Za-z][A-Za-z0-9-]*',line))
            if used-flags: errors.append('Unknown flags: '+path.name+' '+str(sorted(used-flags)))
            checked.append(path.name)
    expected_metrics={'real_only':[5.349,2.431,15.213,29.209],'mixed':[5.235,2.405,14.118,28.666]}
    for name,expected in expected_metrics.items():
        d=json.loads((ROOT/f'runs/pi05_real_mixed_comparison_20261012_v1/{name}/metrics.json').read_text(encoding='utf8'))
        a=d['by_action']; pick=a['Pick up the tray']; place=a['Place the tray']
        actual=[math.degrees(math.sqrt(pick['arm_mse_rad2'])),math.degrees(math.sqrt(place['arm_mse_rad2'])),
                math.sqrt(pick['gripper_mse_mm2']),math.sqrt(place['gripper_mse_mm2'])]
        if [round(v,3) for v in actual]!=expected:errors.append('Offline metric mismatch: '+name)
        if d['overall']['frames']!=3653 or d['overall']['valid_chunk_timesteps']!=69450:
            errors.append('Offline denominator mismatch: '+name)
    closed=json.loads((ROOT/'runs/pi05_real_mixed_closed_loop_20261012_v1_reference/comparison_summary.json').read_text(encoding='utf8'))
    for name,data in closed.items():
        if len(data['cases'])!=20 or sum(c['success'] for c in data['cases'])!=0:
            errors.append('Closed-loop result mismatch: '+name)
    evidence=json.loads((ROOT/'runs/documentation_pdf_20261016/evidence_sources.json').read_text(encoding='utf8'))
    for record in evidence['sources']:
        if not (ROOT/record['path']).is_file():errors.append('Missing source: '+record['path'])
    rendered=sorted((ROOT/'tmp/pdfs/handover_final_render').glob('page-*.png'))
    if len(rendered)!=len(reader.pages): errors.append('Incomplete render set')
    review_path=ROOT/'runs/documentation_pdf_20261016/visual_review.json'
    review=json.loads(review_path.read_text(encoding='utf8')) if review_path.exists() else None
    if not review or review.get('pdf_sha256')!=build['pdf_sha256'] or review.get('pages_reviewed')!=list(range(1,len(reader.pages)+1)):
        errors.append('Visual review missing or stale')
    report=dict(captured_at=datetime.now(timezone.utc).isoformat(),passed=not errors,
                scope='English PDF artifact validation; no operational jobs executed',
                pdf_sha256=build['pdf_sha256'],pages=len(reader.pages),script_entries=len(inventory['entries']),
                configurations=len(inventory['configs']),command_examples_checked=len(checked),
                evidence_files=len(evidence['sources']),all_inventory_paths_present=True,
                text_bounds_violations=bounds,rendered_pages=len(rendered),visual_review=review,
                errors=errors)
    (ROOT/'output/pdf'/(NAME+'.validation.json')).write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
    raise SystemExit(0 if not errors else 1)


if __name__=='__main__':main()
