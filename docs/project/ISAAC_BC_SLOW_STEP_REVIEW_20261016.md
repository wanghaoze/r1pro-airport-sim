# BC v5 单步长等待只读诊断（2026-10-16 17:34 SGT）

结论：观察到第201次梯度计算长等待，但随后自行恢复至已完成223步。没有发 signal、没有改配置或重启。不能将这次情况定性为已确认的 collective 死锁，也不能把已保存步数从100写成223。

服务器运行根：`/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_three_tray_workflow_20261015_v1/bc_resume_after_parallel_20261016_v5`。

## 实查证据

- 训练 PID3617181 / start_ticks35523795，实际 argv 为 code_v54 `train_pi05_isaac_three_tray.py --mode train --stop 1000`，cwd 为项目根；guard3616725、coordinator3617151仍存在。
- `training/training_status.json` 在 unix1792142878.346（17:27:58 SGT）写入 actual_completed_updates=200、gradient_dispatch_200。17:32:58采样仍同状态；主监督心跳继续不等于梯度进度。
- `training/initialization_stacks.log` 多次在 line139 `jax.block_until_ready((state,info))`。源码每一步都落盘阶段，故不是仅每100步显示一次。
- 训练各卡占约17.7GiB；只读 nvidia-smi pmon 显示本进程 SM82%/100%、memory activity0%，整体GPU功耗约100W。不能把GPU利用率当梯度完成证据。
- 两个工作线程3618793/3618791的5秒CPU增量为500/498ticks；主线程 futex等待。内核线程stack/syscall因系统权限不可读取，未修改ptrace系统设置。
- 当前进程56个TCP连接的独立5秒采样，发送/接收各增加366,190,144字节；两者为本机端点同一流量的两面，不应相加计算有效吞吐。单向计数约73MB/s，连接涉及LAN、tailnet及虚拟网卡。证明当时通信有活动，不能仅据Python等待栈断言完全死锁；是否有效collective进展未独立验证。
- 新采集native3650282实际启动unix1792143075.630，比200步长等待开始晚197.28秒，不能将首次停滞归因于它启动。另有原生进程3600241已更早运行，未停止无关作业。
- `train_1000_attempt_0.log` 未见新CUDA/NCCL/OOM/fatal错误。仅恢复开始时旧checkpoint metrics/metrics缺失日志；随后100→200已成功，不能把该日志直接认定当前根因。
- unix1792143285.966（17:34:45 SGT）实际状态自行变为223 / gradient_dispatch_223、heartbeat1792143285.187。本轮排查始终只读，无控制干预。
- 已确认保存仍为`training/pi05/checkpoints/pi05_isaac_three_tray/training/99`，receipt`training/checkpoint_000100.json`；没有200/223检查点收据。原冻结3来源/27段BC，非新泛化数据、非模型任务成功。

## 建议

保持当前实际有进度的训练，不因本次长单步盲目重启。监控实际更新与下一保存收据，ETA遇到长单步标为不可靠。若再次反复长等待，在新独立诊断运行开启NCCL日志、记录接口选择和每步吞吐；可比较单机loopback传输，但尚未验证，不能直接改当前冻结作业或声称根因已确定。CPU调盘研究与合法来源生成继续各自独立推进。
