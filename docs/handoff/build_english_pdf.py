"""Build the English handover PDF from reviewed Markdown and a static inventory.

Run with the bundled document Python. This command does not import operational
project modules, start jobs, or connect to any machine.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Preformatted,
    Spacer, Table, TableStyle, KeepTogether, CondPageBreak,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/pdf'
NAME = 'R1Pro_Project_Review_and_Operations_Handover_EN'
SOURCE = ROOT / 'docs/handoff/README_EN.md'
SNAPSHOT = ROOT / 'runs/documentation_pdf_20261016'
PAGE_W, PAGE_H = A4
LEFT, RIGHT, TOP, BOTTOM = 46, 46, 58, 46
WIDTH = PAGE_W - LEFT - RIGHT
NAVY = colors.HexColor('#16334D')
TEAL = colors.HexColor('#117C83')
INK = colors.HexColor('#263744')
GRAY = colors.HexColor('#617381')
PALE = colors.HexColor('#F0F5F7')
LINE = colors.HexColor('#D7E1E6')

CATEGORY = {
    'Isaac 原生仿真、数据与训练': 'Native Isaac simulation, data and training',
    '单托盘场景、控制与数据': 'Single-tray scenes, control and data',
    '历史控制实验、诊断与审计': 'Historical control experiments, diagnostics and audits',
    '只读监测与索引（以脚本实际副作用为准）': 'Monitoring and indexes - verify actual side effects',
    '安装、项目维护与旧多托盘基线': 'Installation, maintenance and legacy multi-tray baseline',
    '数据、VLA 训练与模型评测': 'Data, VLA training and policy evaluation',
    '真机示范离线回放与配准': 'Offline real-command replay and registration',
    '连接与真机部署': 'Robot deployment and transport',
}

EVIDENCE = [
    'docs/SCENE_TASK_SPEC.md', 'docs/project/EXPERIMENT_STATUS.md',
    'docs/governance/README_20261016_BEFORE.md', 'docs/project/DATA_CATALOG.md',
    'runs/afford_pi05_pickup120_20261008_v2_reference/final_motion_audit.json',
    'AFFORD_PI05_120_TRAINING.txt',
    'runs/real_only_pi05_20261012_v1_reference/final_closure.json',
    'docs/project/REAL_SIM_TRANSFER.md',
    'runs/pi05_real_mixed_comparison_20261012_v1/real_only/metrics.json',
    'runs/pi05_real_mixed_comparison_20261012_v1/mixed/metrics.json',
    'runs/pi05_real_mixed_closed_loop_20261012_v1_reference/comparison_summary.json',
    'runs/pi05_real_mixed_closed_loop_20261012_v1_reference/delivery_report.json',
    'runs/real_sim50_pi05_20261015_v1_reference/latest_status_snapshot.json',
    'runs/real2sim_held_contact_20261012_v2_reference/summary.json',
    'runs/real2sim_held_contact_20261012_v2_reference/delivery_validation.json',
    'docs/project/REAL2SIM.md',
    'runs/isaacsim_three_tray_workflow_20261015_v1_reference/demo12_independent_closure_audit_v1.json',
    'runs/isaacsim_three_tray_workflow_20261015_v1_reference/demo12_audit_exit.json',
    'runs/isaacsim_fast_stability_20261016_v9_recorded_reference/audit_summary.json',
    'runs/isaacsim_fast_stability_20261016_v9_recorded_reference/case_000/path_stability.json',
    'runs/isaacsim_fixed_pickplace_20261016_v1_reference/efficiency_snapshot_20261016T131354.json',
    'memory/CURRENT.md', 'docs/project/REAL_ROBOT_DEPLOYMENT_20261013.md',
    'runs/documentation_handoff_20261016/server_inventory.json',
    'docs/handoff/script_catalog.json', 'docs/project/MODULE_MAP.md',
    'docs/handoff/README.md', 'AGENTS.md', 'docs/governance/MEMORY_POLICY.md',
    'runs/documentation_handoff_20261016/validation.json',
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_fonts():
    fonts = Path('C:/Windows/Fonts')
    for name, filename in [('Body', 'arial.ttf'), ('Body-Bold', 'arialbd.ttf'),
                           ('Body-Italic', 'ariali.ttf'), ('Body-BoldItalic', 'arialbi.ttf'),
                           ('Mono', 'consola.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='Body-Bold',
                                 italic='Body-Italic', boldItalic='Body-BoldItalic')


def styles():
    s = {}
    s['body'] = ParagraphStyle('body', fontName='Body', fontSize=9.4, leading=13.35,
                               textColor=INK, spaceAfter=8, splitLongWords=True,
                               allowWidows=0, allowOrphans=0)
    s['h1'] = ParagraphStyle('h1', parent=s['body'], fontName='Body-Bold', fontSize=19,
                             leading=24, textColor=NAVY, spaceAfter=17, keepWithNext=True)
    s['h2'] = ParagraphStyle('h2', parent=s['body'], fontName='Body-Bold', fontSize=11.4,
                             leading=15, textColor=TEAL, spaceBefore=7, spaceAfter=8,
                             keepWithNext=True)
    s['cover'] = ParagraphStyle('cover', parent=s['h1'], fontSize=33, leading=39,
                                spaceBefore=32, spaceAfter=18)
    s['subtitle'] = ParagraphStyle('subtitle', parent=s['h2'], fontSize=22, leading=28,
                                   textColor=TEAL, spaceAfter=28)
    s['small'] = ParagraphStyle('small', parent=s['body'], fontSize=8.2, leading=11.2)
    s['cell'] = ParagraphStyle('cell', parent=s['body'], fontSize=8.2, leading=10.9,
                               spaceAfter=0, allowWidows=1, allowOrphans=1)
    s['cell_head'] = ParagraphStyle('cell_head', parent=s['cell'], fontName='Body-Bold',
                                    textColor=colors.white)
    s['inv'] = ParagraphStyle('inv', parent=s['cell'], fontSize=7.9, leading=10.4)
    s['path'] = ParagraphStyle('path', parent=s['cell'], fontName='Mono', fontSize=7.6,
                               leading=10.1)
    s['code'] = ParagraphStyle('code', fontName='Mono', fontSize=7.6, leading=10.5,
                               textColor=INK, backColor=PALE, borderColor=LINE,
                               borderWidth=0.5, borderPadding=8, spaceBefore=4,
                               spaceAfter=12)
    s['bullet'] = ParagraphStyle('bullet', parent=s['body'], leftIndent=12,
                                 firstLineIndent=-10, spaceAfter=4)
    return s


def inline(text):
    parts = re.split(r'(`[^`]+`)', text)
    result = []
    for part in parts:
        if part.startswith('`') and part.endswith('`'):
            result.append('<font name="Mono" size="8.0">' + html.escape(part[1:-1]) + '</font>')
        else:
            escaped = html.escape(part)
            escaped = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', escaped)
            result.append(escaped)
    return ''.join(result)


class HandoverDoc(BaseDocTemplate):
    def __init__(self, path):
        super().__init__(str(path), pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT,
                         topMargin=TOP, bottomMargin=BOTTOM, title='R1Pro Airport Tray Manipulation - Project Review and Operations Handover',
                         author='R1Pro Project', subject='English technical review and operating handover, 16 October 2026')
        frame = Frame(LEFT, BOTTOM, WIDTH, PAGE_H-TOP-BOTTOM, leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id='normal', frames=[frame], onPage=self.page))
        self.section = 'Project review and operations handover'
        self.headings = []

    def beforeDocument(self):
        self.section = 'Project review and operations handover'
        self.headings = []

    def page(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(TEAL)
        canvas.rect(LEFT, PAGE_H-29, 28, 3, fill=1, stroke=0)
        canvas.setFont('Body-Bold', 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(LEFT+38, PAGE_H-30, 'R1PRO / ENGINEERING HANDOVER')
        canvas.setFont('Body', 7.7)
        canvas.setFillColor(GRAY)
        canvas.drawRightString(PAGE_W-RIGHT, PAGE_H-30, '16 OCT 2026')
        canvas.setStrokeColor(LINE)
        canvas.line(LEFT, 33, PAGE_W-RIGHT, 33)
        canvas.setFont('Body', 7.3)
        canvas.drawString(LEFT, 21, 'Internal engineering reference | Dated evidence; verify live state before operation')
        canvas.drawRightString(PAGE_W-RIGHT, 21, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and hasattr(flowable, '_heading'):
            label, key, include = flowable._heading
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(label, key, level=0, closed=False)
            self.section = label
            self.headings.append({'heading': label, 'page': self.page, 'key': key})
            if include:
                self.notify('TOCEntry', (0, label, self.page, key))


def heading(text, style, key, include=True):
    p = Paragraph(inline(text), style)
    p._heading = (text, key, include)
    return p


def table(rows, s, widths=None, inventory=False):
    count = len(rows[0])
    if widths is None:
        header = rows[0][0]
        if count == 2:
            ratio = (0.40, 0.60) if header in ('Entry point', 'Script') else (0.29, 0.71)
        elif count == 3:
            ratio = (0.06, 0.59, 0.35) if header == 'ID' else (0.24, 0.43, 0.33)
        elif count == 4:
            ratio = (0.22, 0.15, 0.38, 0.25)
            if header == 'Model': ratio = (0.30, 0.20, 0.20, 0.30)
        elif count == 5:
            ratio = (0.20, 0.20, 0.20, 0.20, 0.20)
        else:
            ratio = [1/count]*count
        widths = [WIDTH*r for r in ratio]
    prepared = []
    for i, row in enumerate(rows):
        prepared.append([Paragraph(inline(cell), s['cell_head'] if i == 0 else s['cell']) for cell in row])
    t = Table(prepared, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),NAVY), ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, PALE]),
        ('LEFTPADDING',(0,0),(-1,-1),7), ('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),6), ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LINEBELOW',(0,0),(-1,0),0.6,NAVY),
        ('LINEBELOW',(0,1),(-1,-1),0.25,LINE),
    ]))
    t.spaceAfter = 10
    return [t]


def appendix(catalog, s):
    flow = [PageBreak(), heading('Appendix A. Script inventory', s['h1'], 'appendix-a')]
    flow.append(Paragraph(inline(
        f"This frozen static inventory contains {len(catalog['entries'])} entry/helper scripts. "
        "It covers applicable top-level Python, shell and PowerShell scripts plus package CLI entries. "
        "Frozen runs/releases and third-party implementations are not counted again. "
        "A listed file is not evidence of successful execution. Historical diagnostics may write data or execute at import time; read source before running them."), s['body']))
    flow.append(Paragraph(inline("Full argument names, default expressions, subcommands, source lines and SHA-256 identities are in `docs/handoff/script_catalog.json` and the frozen companion inventory. AST arguments can belong to separate parsers; do not combine them indiscriminately. The descriptions below are shortened source descriptions."), s['body']))
    for group in CATEGORY:
        entries = [r for r in catalog['entries'] if r['category'] == group]
        if not entries: continue
        flow.append(CondPageBreak(105))
        group_style = ParagraphStyle('inventory_heading', parent=s['h2'], keepWithNext=False)
        flow.append(Paragraph(f"{CATEGORY[group]} ({len(entries)})", group_style))
        data = [[Paragraph('Script / package entry', s['cell_head']), Paragraph('Source description / inspection clue',s['cell_head'])]]
        for row in entries:
            desc = row['description']
            desc = desc.replace('\u2014','-').replace('\u2013','-').replace('\u2011','-')
            if re.search(r'[\u4e00-\u9fff]', desc):
                desc = 'Read source for interface and side effects.'
            desc = ''.join(ch if ord(ch) < 128 else ' ' for ch in desc)
            if len(desc)>115: desc=desc[:115].rsplit(' ',1)[0]+'.'
            suffix=[]
            if row['arguments']: suffix.append(f"CLI declarations: {len(row['arguments'])}")
            if row['subcommands']: suffix.append('subcommands')
            if row['delegates']: suffix.append('package delegate')
            if row['fixed_server_paths']: suffix.append('fixed paths')
            if not suffix: suffix=['no static argparse']
            detail=html.escape(desc)+'<br/><font color="#617381" size="7.2">'+html.escape('; '.join(suffix))+'.</font>'
            data.append([Paragraph(html.escape(row['path']),s['path']), Paragraph(detail,s['inv'])])
        t=Table(data,colWidths=[WIDTH*0.49,WIDTH*0.51],repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),NAVY),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LINEBELOW',(0,0),(-1,-1),0.25,LINE)]))
        t.spaceAfter = 12
        flow.append(t)
    flow.extend([PageBreak(), heading('Appendix B. Configuration inventory',s['h1'],'appendix-b'),
                 Paragraph(inline(f"The frozen inventory contains {len(catalog['configs'])} top-level configuration files. Their names identify experiment versions; presence does not imply that a recipe matches the current task. Preserve the chosen file's SHA and inspect all fixed paths before reuse. The separate reviewed deployment examples are listed after the inventory."),s['body'])])
    rows=[['Configuration path','SHA-256 prefix']]
    rows += [[f"`{r['path']}`",r['sha256'][:16]] for r in catalog['configs']]
    flow.extend(table(rows,s,[WIDTH*0.78,WIDTH*0.22]))
    flow.append(Paragraph('Reviewed deployment and stage examples',s['h2']))
    for p in sorted((ROOT/'docs/handoff/examples').iterdir()):
        if p.is_file(): flow.append(Paragraph(inline('`'+p.relative_to(ROOT).as_posix()+'`'),s['small']))
    flow.append(Paragraph('The examples contain configuration structure and model identities. Replace new-output placeholders and verify the actual workstation/robot configuration before use. They do not contain credentials.',s['body']))
    return flow


def parse_markdown(text, catalog, s):
    lines=text.splitlines(); flow=[]; i=0; heading_index=0; on_cover=True
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1; continue
        if line=='<!-- page -->':
            flow.append(PageBreak());on_cover=False;i+=1;continue
        if line=='<!-- toc -->':
            flow.append(PageBreak())
            flow.append(heading('Contents',s['h1'],'contents',False))
            toc=TableOfContents()
            toc.levelStyles=[ParagraphStyle('toc0',fontName='Body',fontSize=9.6,leading=16,
                                             textColor=INK,spaceBefore=0,leftIndent=0,rightIndent=20)]
            toc.dotsMinLevel=0
            flow.append(toc);i+=1;continue
        if line=='<!-- inventory -->':
            flow.extend(appendix(catalog,s));i+=1;continue
        if line.startswith('```'):
            block=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):block.append(lines[i]);i+=1
            i+=1
            widest=max((pdfmetrics.stringWidth(x,'Mono',s['code'].fontSize) for x in block),default=0)
            style=s['code']
            if widest>WIDTH-16:
                style=ParagraphStyle('code_fit',parent=style,fontSize=max(6.7,(WIDTH-16)/widest*style.fontSize))
            flow.append(Preformatted('\n'.join(block),style));continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                r=[x.strip() for x in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',x or 'x') for x in r):rows.append(r)
                i+=1
            flow.extend(table(rows,s));continue
        if line.startswith('# '):
            title=line[2:];heading_index+=1
            if on_cover:flow.append(Spacer(1,50))
            flow.append(heading(title,s['cover'] if on_cover else s['h1'],f'section-{heading_index}',not on_cover));i+=1;continue
        if line.startswith('## '):
            flow.append(Paragraph(inline(line[3:]),s['subtitle'] if on_cover else s['h2']));i+=1;continue
        if line.startswith('- '):
            flow.append(Paragraph('- '+inline(line[2:]),s['bullet']));i+=1;continue
        paragraph=[line];i+=1
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','```','<!--','- ')):
            paragraph.append(lines[i].strip());i+=1
        flow.append(Paragraph(inline(' '.join(paragraph)),s['body']))
    return flow


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-snapshot',action='store_true',help='Capture a new static inventory and evidence-hash manifest')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);SNAPSHOT.mkdir(parents=True,exist_ok=True)
    inv=SNAPSHOT/'script_catalog.snapshot.json'
    if args.refresh_snapshot or not inv.exists():
        inv.write_bytes((ROOT/'docs/handoff/script_catalog.json').read_bytes())
        files=[]
        for name in EVIDENCE:
            path=ROOT/name
            if not path.is_file():raise FileNotFoundError(path)
            files.append(dict(path=name,bytes=path.stat().st_size,sha256=sha(path)))
        for path in sorted((ROOT/'docs/handoff/examples').iterdir()):
            if path.is_file():files.append(dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,sha256=sha(path)))
        (SNAPSHOT/'evidence_sources.json').write_text(json.dumps(dict(captured_at=datetime.now(timezone.utc).isoformat(),evidence_cutoff='2026-10-16T13:16:00+08:00',sources=files),indent=2),encoding='utf8')
    catalog=json.loads(inv.read_text(encoding='utf8'))
    unknown=set(r['category'] for r in catalog['entries'])-set(CATEGORY)
    if unknown:raise ValueError(unknown)
    register_fonts();s=styles()
    md=SOURCE.read_text(encoding='utf8')
    if any(ord(c)>127 for c in md):raise ValueError('English source must use ASCII text for this edition')
    flow=parse_markdown(md,catalog,s)
    doc=HandoverDoc(OUT/(NAME+'.pdf'))
    doc.multiBuild(flow)
    result=dict(built_at=datetime.now(timezone.utc).isoformat(),pdf=NAME+'.pdf',pdf_sha256=sha(OUT/(NAME+'.pdf')),
                english_source=SOURCE.relative_to(ROOT).as_posix(),source_sha256=sha(SOURCE),
                builder_sha256=sha(Path(__file__)),inventory_sha256=sha(inv),
                script_count=len(catalog['entries']),configuration_count=len(catalog['configs']),
                pages=doc.page,headings=doc.headings)
    (OUT/(NAME+'.sources.json')).write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':main()
