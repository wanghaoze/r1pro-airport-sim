# 真机双模型部署（2026-10-13）

用户本轮授权在Galaxea真机分别尝试混合与仅真机π0.5；VLA server位于workstation、client位于robot。此授权新增真机执行scope，不代表历史仿真已成为真机成功证据。保持robot原run.py、scheduler/scheduler.py与scheduler/joint_command_filter.py不改，只新增独立配置和必要的独立workstation模型接口。

已通过现有EC2跳板实际连接xinmatrix；不需续临时experiments SSH授权。两模型状态实际stage=trained、updates=10000，pipeline complete、params存在：

- mixed: /home/michelle/haoze/r1pro-airport-sim/runs/real_sim_pickplace_20261009_v3/pi05/checkpoints/pi05_real_sim_pickplace/training/9999
- real_only: /home/michelle/haoze/r1pro-airport-sim/runs/real_only_pi05_20261012_v1/pi05/checkpoints/pi05_real_only_pickplace/training/9999

workstation只读GalaxeaVLA副本run.py支持--config/-c、--record；默认15Hz、action_steps16。该副本缺joint_command_filter.py，不能视作robot版本。等待robot SSH地址/可用登录方式，须只读核实际配置schema、过滤器开启/阈值、scheduler发布路径、状态及动作单位、server协议、网络可达性。未启动真机client，未发布命令，未声称部署完成。训练模型19通道rad/m、原真机数据夹爪mm，必须显式匹配往返单位与左右顺序；已有旧serve脚本source=simulation不能原样用于混合/真机来源。保留真实模型输出、过滤后命令、反馈和拒绝记录。现有安全过滤不得绕过。

## 2026-10-13 v2部署与键盘命令停止

最终server run：`/home/michelle/haoze/r1pro-airport-sim/runs/galaxea_robot_deploy_20261013_v2`。mixed8093/PID2264413/birth7589328；real_only8094/PID2264414/birth7589328。服务已预热并监听；v1端点经PID/birth/argv/cwd核验后停止，旧日志保留。release同名v2冻结。不含自动重启服务/训练，原不相关服务未停止。

robot两份配置位于原r1pro目录：config_pi05_mixed_estop_20261013.toml、config_pi05_real_only_estop_20261013.toml。原run/scheduler/filter/config SHA完全不变；指令文件按用户要求改为Pick up the tray。相机/反馈检查15秒无头帧，ROS实际只参数/日志话题，未启动client或发布关节命令。当前blocked_live_sensors、ready_operator_stop_latched，不能称真机拿取通过。

Workstation控制终端：
```bash
/home/michelle/miniconda3/envs/r1pro-vla/bin/python /home/michelle/haoze/r1pro-airport-sim/releases/galaxea_robot_deploy_20261013_v2/scripts/control_galaxea_servers.py --control-file /home/michelle/haoze/r1pro-airport-sim/runs/galaxea_robot_deploy_20261013_v2/operator_control.json
```
本机：`powershell -ExecutionPolicy Bypass -File .\scripts\control_galaxea_servers.ps1` 使用已有允许PTY的EC2跳板密钥，不用restrict实验密钥。保持控制终端；E/空格锁定，Q/退出锁定，R解除后重新启动client。心跳超1秒拒绝；真实测试键盘R/E/R状态及控制进程SIGKILL后心跳过期，两服务经robot协议请求拒绝（0发布）。这是VLA命令停止，无法撤回在途/最后目标，不是硬件急停。默认锁定，不自动R。最多一个robot client/端点；不要同时启动两模型client。

在已恢复驱动/相机、现场准备确认后，robot终端沿用原入口：
```bash
cd /home/nvidia/GalaxeaVLA/experiments/r1pro
source ./start.sh
python run.py --config config_pi05_mixed_estop_20261013.toml --record
# 上一个client退出后，改用仅真机：
python run.py --config config_pi05_real_only_estop_20261013.toml --record
```
原filter保持max_step0.1、velocity1.5、tracking0.25、age0.5与夹爪0..100mm；不二值化/裁剪。黑图探测负夹爪拒绝不代表真实场景结果，保留待live观测复核。server日志robot_filter_applied_on_client字段表示已配置client侧filter的协议预期，并非server验证执行或发布；实际控制证据必须来自原client记录，此轮发布0。5核心单元测试通过；metadata/协议探测/原SHA在runs/galaxea_robot_deploy_20261013_v1_reference，运行视频未产生。

## NumPy2录制修复：使用新增v3入口

用户真实日志首次推理617.54ms后，原recorder接收filter列表时copy=False报错；发布在录制前，因此可能已提交首命令，不能说0动作。附带Executor退出警告是异常退出后的清理问题。robot NumPy2.2.6、imageio/ffmpeg二进制缺失，未修改环境/vendor。新入口仅进程内录制适配，原run.py/scheduler/filter/recorder SHA未变。OpenCV mp4v单帧编码/解码、JSON实际filtered/raw值、20fps通过，测试0控制发布。v1/v2入口是失败证据，请只用v3。

```bash
cd /home/nvidia/GalaxeaVLA/experiments/r1pro
source ./start.sh
python run_pi05_record_compat_20261013_v3.py --config config_pi05_mixed_estop_20261013.toml --record
# 仅真机（不要与上一client同时运行）：
python run_pi05_record_compat_20261013_v3.py --config config_pi05_real_only_estop_20261013.toml --record
```
保持键盘控制终端，R解除/E停止，硬件急停独立。finally保存录制和关闭桥；真实client/完整任务尚未在新入口实测，不自动启动无人看护动作。

## 0–80mm限幅：最终server v3与新配置

用户明确批准提交限幅，修复是命令边界处理而非模型精度提高。原90步记录不变，触发下一返回值left100.462387/right95.387520mm已保留。最终run `/home/michelle/haoze/r1pro-airport-sim/runs/galaxea_robot_deploy_20261013_v3`：mixed8095/PID2608368/birth8503147；real_only8096/PID2608369/birth8503148。v2旧服务身份核验后停止。v3共享v2 operator_control.json/operator_heartbeat.json，原本机控制终端仍用，不需要重启；当前部署已锁定，用户明确R后重新启动client。

server raw_chunk/raw_action保留原始m值，commands.jsonl与client录像JSON的gripper_clipping记raw_mm/submitted_mm/clipped。只饱和两夹爪0..80，不比例缩放、不改臂命令/过滤门/checkpoint/norm。NaN/Inf仍拒绝。新client配置显式两夹爪range[0,80]；原四脚本SHA不变。

```bash
cd /home/nvidia/GalaxeaVLA/experiments/r1pro
source ./start.sh
python run_pi05_record_compat_20261013_v3.py --config config_pi05_mixed_gripper80_20261013.toml --record
# 或仅真机（不同时运行）：
python run_pi05_record_compat_20261013_v3.py --config config_pi05_real_only_gripper80_20261013.toml --record
```

3本机通道/单位/有限与限幅测试通过；robot真实原filter对新两配置接受80、拒绝100，测试无控制发布。证据runs/galaxea_robot_deploy_20261013_v3_reference。新版本完整真机任务结果尚未产生，不能把限幅测试当拿取成功。

## 跟踪误差诊断入口v4与LAN配置

已核Place176：server处理平均65.03ms、client实际间隔384.62ms，物理跟踪异常缺精确反馈，未宣称根因解决。真实16MiB网络基准直连71.79ms/Tailscale183.37ms；新透明relay PID2686671/run galaxea_robot_lan_transport_20261013_v1在10.42.0.191:8095/8096转发到原模型端点，停止控制和夹爪80门不变。两endpoint机器人LAN握手通过，模型服务未重启。

新增record_v4原filter诊断：每帧/拒绝时完整measured_state、previous_filtered_target、raw_target、差值/阈值与观测年龄写joint_filter_diagnostics.jsonl；原异常照常抛出、拒绝帧不发布。原filter0.325rad拒绝+已录JSON收尾测试通过，0控制发布。原脚本不改，原v3录像保留；原故障物理根因须有下一次真实反馈才能确认。

robot新命令：
```bash
python run_pi05_record_compat_20261013_v4.py --config config_pi05_mixed_gripper80_lan_20261013.toml --record
# 或real-only配置config_pi05_real_only_gripper80_lan_20261013.toml
```
保持现有控制终端，E/空格停、R明确解锁，不自动重跑真机。名义20Hz不代表已实测20Hz。证据filter_diagnostic_validation_v4.txt、network_transfer_probe.json、lan_handshake.json。

2026-10-13 真机执行环境纠正：SSH fresh shell须继承已存在Galaxea FASTRTPS_DEFAULT_PROFILES_FILE=/opt/galaxea/find_server/super_client_configuration_file.xml，再查ros2 topic list --no-daemon；原节点已用此配置，不修改XML。旧未见话题结论仅错误发现环境，不能判SDK未运行。用户重新执行Place已实际启动mixed client PID191319/start_ticks1225013，robot runs/place_retry_diagnostic_20261013_v1/client.log，record_v4/LAN/gripper80；此时正在真实执行，未判成功/闭合，不自动重试。停止由现有操作终端E/空格，0.25跟踪门和原filter不变。

## 一键client（当前推荐入口）

robot进入项目后：
```bash
./vla pick         # mixed Pick
./vla place        # mixed Place
./vla pick real    # real-only Pick
./vla place real   # real-only Place
./vla status
```
从任何目录也可 `~/GalaxeaVLA/experiments/r1pro/vla place`。新增脚本自动source原环境/加载DDS/正确LAN与gripper80配置/精确文本/record_v4，原脚本不改。无参数只显示帮助。已有client先Ctrl+C（录制收尾）后换动作，不运行中覆写文本；自动单实例检查。停止控制终端仍需打开，用户R主动解锁、E/空格停，不自动R/重试。robot实际帮助、status、非法模型和重复client保护测试通过，未自动运行物理动作。

## SDK原生反馈诊断v5

用户明确保留原停止门、不自动恢复。robot新增一键入口：
```bash
./vla_sdk_diagnostics place       # mixed
./vla_sdk_diagnostics place real  # real-only
./vla_sdk_diagnostics pick
```
环境/模型配置/原0.25门/夹爪80/停止键保持；不自动重跑。新record_v5缓存原生SDK回调最近2048条position/velocity/effort、ROS时间、接收时间和ROS发布position。effort原单位未标定，不强称力矩。拒绝后本client无新命令，仅被动记录1秒，再关闭桥与收尾视频。原生窗口在每次录像目录sdk_fault_window.json，包含sdk_pre_fault_history与拒绝后SDK流；joint_filter_diagnostics.jsonl仍保留每步差值。SDK非有限字段以字符串原样指示，控制校验不变。

robot环境合成测试保存SDK三个字段、NaN证据、0.25超限仍抛错、原文件SHA不变、0控制发布，报告sdk_diagnostics_v5_validation.json。尚无新真人试跑/根因证明，不把诊断增强称控制修复。旧vla/v4入口仍存在，下一次需要新SDK证据请使用vla_sdk_diagnostics。

控制终端重复启动修复（2026-10-13）：新release galaxea_keyboard_control_20261013_v3，原PowerShell命令自动使用新版。先抢单实例锁，重复启动只提醒现有PID，无gate/heartbeat变化或traceback。原健康PID2636174未杀；本次旧版重复启动已造成STOP，须在原终端按R明确恢复。换终端先原终端Q再打开新终端。真实旧operator冲突测试及隔离PTY R/E/Q/armed保留测试通过，无硬件控制发布；共用原v2 gate，模型服务不改。
