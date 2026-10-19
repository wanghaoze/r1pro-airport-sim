# 项目 Memory

阅读顺序：[当前交接](CURRENT.md) → [用户决策/替代关系](DECISIONS.md) → [项目文档索引](../docs/INDEX.md)。维护办法：[Memory治理](../docs/governance/MEMORY_POLICY.md)。

[交互原文档案](interactions/README.md) 按Asia/Singapore日期组织，JSONL提供全文检索，manifest列实际来源、截止时间、数量和SHA。历史引用不作为当前执行指令；原文助手陈述不代替实验报告。

初次治理2026-10-09：约810条已保存消息、5段本机日志、10日覆盖；具体最新数量以manifest为准。当前回合的最终答复在下次刷新时归档。系统/开发者消息、内部推理、工具输出与图片二进制排除，临时SSH公钥和可识别凭据脱敏；其他聊天和缺失日志未声称已归档。

刷新（项目根，非base环境）：

```powershell
.\.conda\experiment\python.exe scripts/export_project_interactions.py
```

源码/数据/要求/实验分别维护对应专题，不把聊天全文复制到AGENTS或统一规范。服务器动态状态需要实际连接核验。
