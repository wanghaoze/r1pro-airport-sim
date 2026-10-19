"""Build a static handoff inventory without importing or executing project jobs."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs/handoff'


def included_in_handoff(path):
    """Keep execution tools; the handoff uses interactive direct SSH only."""
    if path.name.startswith(('public_ssh_', 'connect_gpu_')):
        return False
    if path.name == Path(__file__).name:
        return True
    text = path.read_text(encoding='utf-8-sig')
    return not any(marker in text for marker in ('ProxyCommand', 'experiments_ed25519'))


def category(name):
    if any(s in name for s in ('galaxea', 'public_ssh', 'connect_gpu')):
        return '连接与真机部署'
    if any(s in name for s in ('watch_', 'maintain_', 'status', 'video_index')):
        return '只读监测与索引（以脚本实际副作用为准）'
    if any(s in name for s in ('isaac',)):
        return 'Isaac 原生仿真、数据与训练'
    if any(s in name for s in ('real2sim',)):
        return '真机示范离线回放与配准'
    if any(s in name for s in ('train', 'pi05', 'vla', 'pickup', 'action8', 'task_complete', 'complete_task')):
        return '数据、VLA 训练与模型评测'
    if any(s in name for s in ('single_tray', 'three_table', 'three_action')):
        return '单托盘场景、控制与数据'
    if any(s in name for s in ('diagnos', 'audit_', 'probe_', 'inspect_', 'analyze_', 'summarize_', 'compare_', 'test_')):
        return '历史控制实验、诊断与审计'
    return '安装、项目维护与旧多托盘基线'


def info(path):
    text = path.read_text(encoding='utf-8-sig')
    row = dict(path=path.relative_to(ROOT).as_posix(), category=category(path.name),
               sha256=hashlib.sha256(path.read_bytes()).hexdigest(), arguments=[], subcommands=[], delegates=[])
    if path.suffix == '.py':
        tree = ast.parse(text)
        row['description'] = (ast.get_docstring(tree) or '未提供模块说明；按文件名分类，运行前阅读源码。').split('\n\n')[0].replace('\n', ' ')
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and any(a.name == 'main' for a in n.names):
                row['delegates'].append(n.module)
            if not isinstance(n, ast.Call): continue
            method = getattr(n.func, 'attr', '')
            if method == 'add_argument':
                row['arguments'].append(dict(names=[ast.unparse(a) for a in n.args],
                    settings={k.arg: ast.unparse(k.value) for k in n.keywords if k.arg}, line=n.lineno))
            if method == 'add_parser' and n.args: row['subcommands'].append(ast.unparse(n.args[0]))
    else:
        row['description'] = next((s.lstrip('# ').strip() for s in text.splitlines() if s.startswith('#') and not s.startswith('#!')), 'Shell/PowerShell 入口；参数和副作用见源码。')
    row['fixed_server_paths'] = '/home/' in text
    return row


def build():
    scripts = list((ROOT/'scripts').glob('*.py')) + list((ROOT/'scripts').glob('*.sh')) + list((ROOT/'scripts').glob('*.ps1'))
    scripts += list((ROOT/'r1pro_teleop').rglob('__main__.py'))
    # Also cover module CLI entries outside scripts/, not ordinary library files.
    for path in (ROOT/'r1pro_teleop').rglob('*.py'):
        text = path.read_text(encoding='utf-8-sig')
        if '__name__' in text and '__main__' in text and 'argparse' in text: scripts.append(path)
    rows = [info(p) for p in sorted(set(scripts)) if included_in_handoff(p)]
    configs = sorted((ROOT/'configs').glob('*'))
    configs = [p for p in configs if p.is_file()]
    data = dict(schema='handoff_static_catalog/1', scope='direct SSH handoff execution scripts and package CLI entries; host-specific access wrappers and frozen runs/releases/vendor excluded',
        entries=rows, configs=[dict(path=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in configs])
    lines = ['# 交接脚本与配置索引', '',
        '由 `scripts/build_handoff_catalog.py` 静态读取源码生成；不会 import 脚本、调用 `--help` 或启动任务。', '',
        f'共 **{len(rows)} 个入口/辅助脚本**、**{len(configs)} 个 configs 配置文件**。机器可读参数/默认值/来源 SHA 见 [script_catalog.json](script_catalog.json)。', '',
        '操作顺序见 [交接 README](README.md)。本索引包含历史诊断；有文件不等于支持当前任务，也不等于已实测成功。', '',
        '连接方式统一为 `ssh michelle@xinmatrix` 或 `ssh michelle@100.104.0.108`。索引只收录本次交接适用的执行入口，不收录机器专用的远程访问包装器；监控直接在服务器运行。', '',
        '`runs/`、服务器 `releases/` 内的冻结副本/一次性 bootstrap、third_party/vendor 不重复计入；其部署身份见 README 和服务器快照。不要把旧运行目录中的脚本直接当新任务入口。', '',
        '参数取自 AST 调用点，可能属于不同子命令或辅助函数；请按源码上下文使用，不要把一行列出的所有参数组合运行。Shell 参数见源码；“无 argparse”不是无参数，更不表示只读。尤其诊断脚本可能在模块顶层直接执行，不能批量运行 `--help`。', '',
        '更新：`python scripts/build_handoff_catalog.py --write`；检查：`python scripts/build_handoff_catalog.py --check`。', '']
    for group in sorted({r['category'] for r in rows}):
        lines += [f'## {group}', '', '| 脚本 | 用途（源码说明） | CLI 线索 |', '|---|---|---|']
        for row in rows:
            if row['category'] != group: continue
            cli = []
            if row['subcommands']: cli.append('子命令：' + ', '.join(row['subcommands']))
            if row['arguments']: cli.append('参数：' + ', '.join('/'.join(a['names']).replace("'", '') for a in row['arguments']))
            if row['delegates']: cli.append('委托：' + ', '.join(row['delegates']))
            if not cli: cli.append('无静态 argparse；先读源码')
            if row['fixed_server_paths']: cli.append('含服务器固定路径')
            clean = lambda s: s.replace('|', '\\|').replace('\n', ' ')
            lines.append(f"| [{row['path']}](../../{row['path']}) | {clean(row['description'])} | {clean('；'.join(cli))} |")
        lines.append('')
    lines += ['## 全部配置', '', '这里只登记文件身份。具体用途先查 README 的流程表；不要把旧八文本/单桌配置替换当前三动作配置。', '', '| 文件 |', '|---|']
    lines += [f'| [{p.relative_to(ROOT).as_posix()}](../../{p.relative_to(ROOT).as_posix()}) |' for p in configs]
    return {'SCRIPTS.md': '\n'.join(lines)+'\n', 'script_catalog.json':json.dumps(data,ensure_ascii=False,indent=2)+'\n'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--write',action='store_true');group.add_argument('--check',action='store_true')
    args=parser.parse_args();generated=build()
    if args.write:
        DEST.mkdir(parents=True,exist_ok=True)
        for name, content in generated.items(): (DEST/name).write_text(content,encoding='utf8')
    else:
        stale=[name for name,content in generated.items() if not (DEST/name).exists() or (DEST/name).read_text(encoding='utf8')!=content]
        if stale: raise SystemExit('Stale handoff catalog: '+', '.join(stale))
    print(json.dumps(dict(status='written' if args.write else 'current',files=list(generated))))


if __name__ == '__main__': main()
