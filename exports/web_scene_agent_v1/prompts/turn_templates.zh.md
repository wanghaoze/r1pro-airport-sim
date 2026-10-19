# 每轮上下文与任务模板

占位符由后端JSON序列化填入，不把日志拼进system权限段。request_id由后端生成；除已展示schema字段外，不把凭据、绝对服务器写入路径交给LLM。

## 场景编辑

```text
request_id: {{REQUEST_ID}}
capabilities: {{AVAILABLE_OPERATIONS_JSON}}
scene_snapshot: {{VERIFIED_SCENE_STATE_JSON}}
selected_rooms: {{SELECTED_ROOM_IDS_JSON}}
user_request: {{USER_TEXT_JSON}}

理解用户修改意图。相对量依照scene_snapshot计算为房间局部绝对坐标，度转换弧度。
如缺坐标基准或目标范围，先问必要信息。只提交一次scene.patch，保留未请求字段。
若用户要看当前场景而状态缺失，先scene.describe。解释草稿和原生应用的差别。
```

## 数据选择与训练计划

```text
request_id: {{REQUEST_ID}}
dataset_catalog: {{REGISTERED_DATASETS_JSON}}
approved_recipe: {{EXPLICIT_RECIPE_OR_NULL}}
user_request: {{USER_TEXT_JSON}}

仅使用catalog里的dataset_id。先说明scope、域、split和完整来源对数。
用户未指定训练配方时提出具体steps/batch/父模型候选及影响，不把推荐当批准。
明确选择后提交training.plan。读取返回artifact中的blockers，不自行推导可启动。
不能把不同任务/来源混合。当前native两动作数据不能直接调用三动作trainer。
```

## 结果解释

```text
tool_receipt: {{RECEIPT_JSON}}
artifact: {{ARTIFACT_JSON}}
server_job_snapshot: {{VERIFIED_JOB_STATE_OR_NULL}}

先说实际结果。没有server_job_snapshot时不报告实时GPU/PID/训练进度。
draft_saved=草稿保存，blocked=计划被资格门阻塞，initializing=初始化，
training必须有actual_completed_updates>0，checkpoint_saved必须有真实路径/SHA。
模型测试成功另依真实评测报告，complete仅表示流程结束。
```
