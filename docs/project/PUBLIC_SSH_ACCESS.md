# GPU服务器公网SSH入口

2026-10-09部署并实测。用户提供EC2与PEM用于部署，并确认弹性IP为47.130.167.160。

连接链：本机SSH → EC2 ec2-user@47.130.167.160:22 → EC2本机127.0.0.1:2222 → GPU服务器michelle@xinmatrix:22。

EC2的2222仅监听loopback，不需要新增公网安全组端口。公网用户通过EC2的SSH跳板访问；本机无需Tailscale。已实测远程hostname/id与交互PTY，尚未在MobaXterm GUI中实际操作。

## MobaXterm

新建SSH会话：Remote host `127.0.0.1`、Port `2222`、Username `michelle`。

Advanced SSH settings勾选Use private key，选择本项目`.secrets/mobaxterm_gpu_ed25519`；此密钥允许交互终端及SFTP，只接受隧道在GPU本机的127.0.0.1连接来源。

Network settings选择SSH gateway：Host `47.130.167.160`、Port `22`、User `ec2-user`，gateway私钥选择本项目`.secrets/haoze_ec2.pem`。这是用户提供PEM的本机权限受限副本，原下载文件未修改。两把密钥作用不同，不能互换。X11转发未授权给新GPU登录密钥。

也可在PowerShell运行`scripts/connect_gpu_via_ec2.ps1`进入交互终端。

## 运行与撤销

GPU项目run：`runs/public_ssh_ec2_20261009_v1`，包括`status.json`、`ssh.log`、`supervisor.log`及`external_verification.json`。进程status只证明SSH子进程与心跳，实际公网登录结论以独立external_verification为准。

专用GPU隧道私钥保存在项目`.secrets/public_ssh/`，未离开GPU。EC2专用用户`r1pro-tunnel`的授权公钥仅允许127.0.0.1:2222监听，不提供终端登录。EC2原sshd配置未修改。

GPU的user service `r1pro-public-ssh.service`启用，michelle linger从no改为yes，用户退出后继续运行。最多3次恢复，退避5/15/45秒；预算耗尽标failed并停止，不无限重试。重启后的服务恢复尚未实测，未为验证重启机器。

状态：`systemctl --user status r1pro-public-ssh.service`。停止并取消开机启动：`systemctl --user disable --now r1pro-public-ssh.service`。手工重试：`systemctl --user restart r1pro-public-ssh.service`。撤销登录还需分别移除新增GPU授权公钥和EC2专用隧道账号；不要删除原有SSH授权。

本轮不更改训练、数据、控制逻辑或仿真任务合同。用户明确部署授权独立于历史临时实验SSH密钥；没有延长或修改旧临时授权。

## 2026-10-09本机MobaXterm配置
已向本机AppData/Roaming/MobaXterm/MobaXterm.ini的Bookmarks添加GPU-public-via-EC2，原两会话保留，原INI备份在项目.secrets，未导出密码。会话导出resources/network/GPU-public-via-EC2.moba及.mxtsessions可用于重新导入。MobaXterm运行中，配置文件已核验，但应用内缓存是否刷新未验证；产品策略阻止原生界面控制，未绕过该限制、未强制重启或关闭用户会话。配置后公网OpenSSH登录及隧道active再次通过。证据runs/public_ssh_ec2_20261009_v1_reference/mobaxterm_config.json。

## 双会话迁移包
2026-10-09新增EC2-public独立登录会话，本机INI及resources/network/EC2-and-GPU.mxtsessions均包含EC2/GPU两会话。迁移压缩包位于项目.secrets/MobaXterm-EC2-GPU-20261009.zip；包含两把用户登录私钥、sessions.template、Prepare-Sessions.ps1、Test-Connections.ps1、已核验known_hosts、README和PROMPT，不包含实验临时私钥或GPU隧道专用私钥。另一电脑解压到英文目录后运行Prepare-Sessions生成实际本机绝对路径的EC2-and-GPU.mxtsessions再导入，避免旧用户目录。迁移包脚本生成和两端公网SSH本机实测通过；另一电脑与MobaXterm GUI尚待测试。证据runs/public_ssh_ec2_20261009_v1_reference/transfer_package.json；可复制prompt resources/network/TRANSFER_PROMPT.txt。
