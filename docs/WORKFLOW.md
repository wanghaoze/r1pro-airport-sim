# 安装与运行流程

本页主要保留旧多托盘 smoke/formal400 基线。当前单托盘、Isaac 三盘、各套训练及 workstation/robot 启动请从 [交接 README](handoff/README.md) 进入；不要把本页旧基线命令直接当当前三动作新数据管线。

逐步骤逻辑、状态字典与失败判定统一维护于 [SCENE_TASK_SPEC.md](SCENE_TASK_SPEC.md)。本文件保留安装/命令示例；修改流程时先同步统一规范并运行 `python scripts/sync_task_spec.py --check`。

## 1. 环境

Linux 是正式批处理平台，Python 3.11，必须在非 base Conda 环境安装。已有 `r1pro-tray` 可直接复用。不要复制旧虚拟环境，不要 sudo/pip 系统安装。

```bash
conda create -n r1pro-tray python=3.11 -y
conda activate r1pro-tray
cd /path/to/r1pro-airport-sim
bash scripts/setup_r1pro_server.sh --with-lerobot
python -m pip install pytest
python -m pip check
export PYTHONPATH="$PWD"
python scripts/project.py check --compile
```

安装脚本使用已有锁定版本：MuJoCo 3.13.0、PyTorch 2.8.0 cu129、LeRobot 0.4.4。CPU 负责 IK/物理求解，GPU/EGL 负责渲染；GPU 利用率低不表示物理未运行。无须 CUDA 12.4。

Windows 可执行资源检查、部分单元测试和诊断，但正式 batch 使用 POSIX 文件锁，必须在 Linux 运行。

预构建网格已包含，无需重新分解碰撞网格。可选的 `build_assets.py` 需要额外的 trimesh/coacd，实验 online_push 需要 ruckig；默认固定动作配置不启用这些重建/实验功能。安装脚本不是整个依赖树的完整锁文件，新环境仍应执行 pip check 并保存版本快照。

## 2. 准备四相机场景

下面先用附带 smoke 集。原始资源只读，四相机转换输出到新目录；命令拒绝覆盖已有目录。

```bash
python scripts/project.py fourcam --set smoke --output runs/smoke_fourcam
python -m r1pro_teleop.airport_fsm prepare \
  --manifest runs/smoke_fourcam/manifest.json \
  --output runs/smoke_collection \
  --config configs/airport_primitives3_smoke.json --half-turn-equivalent
python -m r1pro_teleop.airport_fsm preflight --root runs/smoke_collection --workers 2
```

`--half-turn-equivalent` 只适用于不区分首尾的矩形托盘；有方向标识时不要使用。scene split 由 prepare 固定：smoke 8/2/2，formal 300/50/50；原始生成器中的 split 不作为训练划分依据。

预检会拒绝非法初态。预检失败不代表轨迹失败，也不能直接跳过预检。附带场景不是服务器后续修正过的 v7 场景，部分可能被拒绝；如需修正，使用 `repair_airport_initial_settle.py --help` 在新的来源目录处理，之后重新 prepare，不能改已登记场景。

## 3. 先小批验证，再扩大

如测试新的可达性拉近分支，将正式prepare的配置替换为 `configs/airport_reach_pull.json` 并使用**新collection目录**。该配置为400场景；测试12场景时复制到新配置并设置expected_scenes=12、split_counts=[8,2,2]。原v50配置继续默认关闭拉近，不代表新分支已经部署或提高了成功率。

```bash
python -m r1pro_teleop.airport_fsm generate --root runs/smoke_collection --workers 2 --limit 3
python -m r1pro_teleop.airport_fsm report --root runs/smoke_collection
```

`generate` 处理完选中场景不等于全部成功；必须看 report 中 `physics_ready`、失败原因与导出数。不要用 `--limit 3` 推断固定是哪三个场景，精确选择使用 `--scene-ids ID ...`。

## 4. 导出和验收

```bash
R1PRO_GPU=0 bash scripts/run_r1pro_gpu.sh -m r1pro_teleop.airport_fsm export \
  --root runs/smoke_collection --shard-size 1 --action-layout mobile19
python -m r1pro_teleop.airport_fsm report --root runs/smoke_collection
```

成功候选才进入普通训练 shard。保留原 Episode，技能视图只引用帧区间；失败/恢复证据单独保留。检查 `quality/export_summary.json`、`datasets/catalog.json`、各 shard 的 `source_manifest.json` 和各 attempt 的 `export_quality.json`。官方 loader 必须能读首末帧，回放不能发散，分辨率/帧率/空白帧与 split 泄漏均须检查。

## 5. 正式 400 场景

```bash
python scripts/project.py fourcam --set formal --output runs/formal_fourcam
python -m r1pro_teleop.airport_fsm prepare --manifest runs/formal_fourcam/manifest.json --output runs/formal_collection --config configs/airport_primitives3.json --half-turn-equivalent
python -m r1pro_teleop.airport_fsm preflight --root runs/formal_collection --workers 2
python -m r1pro_teleop.airport_fsm generate --root runs/formal_collection --workers 2
R1PRO_GPU=0 bash scripts/run_r1pro_gpu.sh -m r1pro_teleop.airport_fsm export --root runs/formal_collection --shard-size 1 --action-layout mobile19
python -m r1pro_teleop.airport_fsm report --root runs/formal_collection --require-all-exported
```

最后一条非零退出表示尚未全部通过，不能把拒绝/失败算作成功数据。当前基线不保证通过全部 400 场景。修改配置、代码或资源后，必须新建 collection，旧 provenance/哈希不能伪造。

新生成的 collection 会记录绝对路径和依赖指纹，请先把项目放到服务器最终目录再 prepare；不要直接搬移已登记运行目录并修改旧指纹。

## 6. 测试

```bash
python -m pytest tests/test_fixed_primitives.py tests/test_blended_trajectory.py tests/test_contact_handoff.py tests/test_motion_repair.py tests/test_repeat_handling.py tests/test_airport_fsm_unit.py -q
```

完整历史测试中有依赖平台或历史生成目录的用例；新项目资源检查与上面核心回归测试结果保存在 `evidence/project_validation/`。程序控制入口是 FSM，不需要 Quest 设备或人工操作。
