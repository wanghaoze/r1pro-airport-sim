# 来源与可复现范围

代码来自 `validation/primitives3_20260923/v50/validated_release_code.zip`，不是整理当天混有其他实验的工作区。具体 SHA256 与逐文件来源见 PROJECT_PROVENANCE.json。新增注释通过 AST 对比证明未改变基线控制语句。

网格、碰撞形状、URDF 和 XML 模板独立复制自本机 `outputs/r1pro_tray_scene`；Galaxea 许可证保留在 licenses/GalaxeaManipSim。第三方资源继续遵循原许可证；此整理不授予新的商用/分发权。前端依赖许可证仍位于 r1pro_teleop/static。

附带12+400场景来自本地 `outputs/airport_trays_final_v1`，XML 仅调整资源相对路径并更新哈希；原 XML 哈希保留在 project_relocation。它们不是服务器 `airport_fsm_400_fourcam_v7_20260922` 的稳定性修正版。四相机转换及 preflight 必须重跑，不能承诺复现 v50 完全相同的轨迹。

历史服务器数据和完整视频未复制进项目；报告放在 evidence/v50，原视频继续在 humanvideo/validation/primitives3_20260923/v50。运行独立项目不依赖该历史目录。若要严格复现服务器轨迹，应另外导入当时的 scene.json/mobile.xml 和相关依赖，并保留校验哈希；不能用相同 scene_id 假定内容相同。

没有包含 SSH 密钥、账户凭据、Conda 环境、训练模型权重、原始真机 bag 或大规模轨迹。原 humanvideo 不做搬移/删除。Quest 兼容代码保留，但 Agent 仿真生成不需要 Quest。
