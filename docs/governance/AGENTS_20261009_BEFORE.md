# 修改本项目

- 先阅读 README.md 和统一规范 docs/SCENE_TASK_SPEC.md；CONSTRAINTS/WORKFLOW 是补充入口。
- 修改场景生成、配置、状态机、动作/接触约束、相机、记录/导出时，必须在同一改动更新 docs/SCENE_TASK_SPEC.md 对应步骤、状态字典、失败规则和变更记录，然后运行 `python scripts/sync_task_spec.py --write` 与 `--check`。自动附录不代替人工核对；不能只刷新哈希而不审阅流程。
- 默认任务仅为仿真；不得把 simulation/program_generated 标成真机或人工遥操。
- 保留接触动力学、相机朝向、原生视频、scene split 和失败证据，禁止以放宽验收冒充控制改进。
- 参数化动作预算和计时排除项必须一起报告；不可承诺所有场景均在 3 秒内可行。
- 不改已有 collection；代码、配置或资源变化后使用新运行目录。
- 安装仅使用非 base Conda 环境；不要修改系统 Python 或 vendor。
- 调整控制逻辑先跑相关核心测试，再做完整物理 Episode；没有服务器实测时不要声称已部署。
- evidence/v50 是历史验收，resources/scenes 是本地来源；二者不能当作相同场景版本。
- 所有项目资源应留在本目录，运行时不得依赖原 humanvideo 目录。
