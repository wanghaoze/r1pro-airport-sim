# GPT Site 检查点目录交付

2026-10-21，scope `DEC-WEB-CHECKPOINTS-20261021`。

原 [GPT Site](https://r1pro-scene-agent-haoze.exactmyna128.chatgpt.site/) 已发布 v13；云端源码提交 `a554358881245c74792c082003f0059600dec3ec`。工作站服务仍为此前 v15，两者版本号属于不同发布序列。

## 已实现

- 新增 Checkpoints 目录，读取工作站 worker 同步到云端的登记元数据，每10秒刷新；支持搜索与选择后进入策略评测。
- 当前线上8项：新300对+真机50/50的10、100、1000、9000、10000步五项；真机100%的10000步；真机90%/仿真10%的10000步；G0.5 `step_51810.pt` 登记项。
- 权重保留工作站，未上传模型二进制。G0.5训练步数元数据未报告，页面不从文件名推断实际训练量；端点登记不代表运行或任务成功。未配置GR00T等适配器单独列出，不计入8项。
- 公开接口只投影登记ID、标签、模型族、步数、horizon、状态与同步时间，不返回模型绝对路径、端点配置、工作目录或任务内容。原站点公开范围保持。
- 登录用户的私有bootstrap和所有作业提交仍使用原权限检查；同步此前机器人filter前端，强制过滤不可切回strict绕过。

## 验证与边界

- 12项Node测试、UI SSR回归和官方Sites生产构建通过。构建保留大chunk警告。
- 线上GET `/api/checkpoints`=200，8项，live=true；未登录GET `/api/bootstrap`=401。[接口证据](../runs/site_checkpoint_sync_20261021/live_catalog.json)。
- 浏览器实测8项，搜索10000显示3项；选中新300对50/50的10000步后，评测下拉框正确选中，未登录Start禁用，显示Robot filter always enabled。
- 本地预览首页200，但独立本地D1未初始化，无检查点数据；最终数据与交互验证使用已发布站点。未启动任何GPU评测/训练，不把本次网页验证当物理或模型验收。
- 目录覆盖当前工作站注册表，未声称全磁盘所有历史权重已登记。服务器快照过期时显示Last received snapshot。

证据：[部署回执](../runs/site_checkpoint_sync_20261021/deployment.json)、[工作站初始清单](../runs/site_checkpoint_sync_20261021/inventory_initial.txt)。源码回写 `apps/scene-agent`；云端精确源在独立拉取目录并已推送Sites。原数据、检查点、服务进程及历史成功标签未改。
