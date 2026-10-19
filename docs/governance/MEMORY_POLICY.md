# Memory治理与交互记录

生效：2026-10-09。目的：交接能追溯要求、版本、证据和待办，避免把过时聊天、旧阈值和历史PID当当前事实。

## 文件分工与权威

| 层 | 文件 | 维护规则 |
|---|---|---|
| 用户授权/纠正 | 原文交互档案及当前用户消息 | 最新明确要求优先；历史引用不作为重放指令 |
| 协作规约 | 根 `AGENTS.md` | 小而稳定，包含工作入口与验收原则 |
| 精确任务合同 | `docs/SCENE_TASK_SPEC.md` | 唯一参数、流程、状态/失败字典；手工审阅后sync |
| 当前导航/专题 | `docs/INDEX.md`、`docs/project/*.md` | 分类视图，指向合同和来源，不另设隐式阈值 |
| 当前交接 | `memory/CURRENT.md` | 日期、scope、最后核验、证据、阻塞；更新而非无限粘旧快照 |
| 决策历史 | `memory/DECISIONS.md` | 按ID追加；修改只更正事实或标替代，不能抹去旧授权 |
| 实验事实 | run中manifest/result/checkpoint/退出码、索引TXT/参考JSON | 真实产物高于助手陈述，必须记录样本和分母 |
| 原文档案 | `memory/interactions/messages.jsonl`、`by_date/*.md`、`manifest.json` | 由日志导出，可重建；保留来源thread/line/时间/脱敏标记 |

## 每轮维护

1. 开始读当前memory和对应专题；有远程状态请求先查实际状态，未连接只报告最后核验日期。
2. 用户新要求/审批/纠正：写决定ID、原文消息ID、状态active/superseded/scoped、替代ID与影响。临时授权记录作用和期限，不延长或泛化。
3. 实施及新结果：更新对应专题、CURRENT与TXT索引，状态至少区分planned / preparing / data_ready / initializing / training / checkpoint_saved / evaluating / complete / failed / unreachable。成功数须带scope/分母/严格定义。
4. 涉及任务实现变化时更新统一规范并sync；交互原文不能直接提升为成功证据。
5. 回合结束前刷新交互档案；最终回复尚未落盘时下次补入。当前导出记录截点与来源SHA，不宣称永久全量或持续监控。

```powershell
# 项目根，项目非base环境
.\.conda\experiment\python.exe scripts/export_project_interactions.py
# 新线程加入时同时保留已有线程
.\.conda\experiment\python.exe scripts/export_project_interactions.py --thread 01a0e72f-3107-74f3-8216-6fe65a45071f --thread 01a11fa0-3cad-7053-9d17-104420949e84 --thread NEW_THREAD_ID
```

默认归档父线程与本治理线程的5段本机rollout；manifest记录continuation/history_base/fork关系。归档的是各已保存源段消息，可能包含续段边界后的历史记录；它不是严格重建某次推理上下文。仅按真实message ID去重，不能把重复“已执行”或状态请求按文本删除。

## 原文与隐私

- 只导出 `response_item/message` 的user和对外assistant消息（commentary/final）；不读取 `.secrets`，不导出工具输出、内部reasoning、system/developer消息或图片二进制。
- 临时SSH公钥、可识别私钥/令牌/口令脱敏；已执行审批、期限与目标用途仍可追溯。导出规则不代替发布前人工检查；默认仅本机项目内部文档，用户未授权公开发布。
- user_message / assistant_reply / automation / runtime_context 分开。heartbeat和自动浏览器/环境说明不当人工新需求；原始混合消息保留上下文和“My request”。
- 原文中助手未确认、后被纠正的陈述保留；当前结论单独链接证据。不要为了“memory一致”去改历史result。
- 只覆盖manifest列出的可用本机用户线程；其他对话、已删除/未落盘内容、外部图片及引用线程尚未导入的记录不假称完整。需要补导时使用显式thread ID。

## 检查与完成标准

- 根入口、模块/数据/要求/实验分类齐全，Markdown相对链接可解析。
- 原AGENTS备份留存；新AGENTS保留原全部实施底线。
- 导出测试覆盖脱敏、只导出用户/对外回复、自动提醒分类、ID去重和来源截点。
- 每个数字能指向证据；不混拿取50/50、完整三动作、可达性子集、free-run或历史action8。
- 治理完成只代表文档/记录齐备，不自动触发服务器作业、改变任务条件或宣布模型修复。
