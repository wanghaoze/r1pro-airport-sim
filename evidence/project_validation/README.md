# 本次独立整理验证

2026-09-24，Windows，本机已有 Python 环境；未安装新依赖、未连接服务器、未驱动真机。

- 核心回归：110 passed、1 xfailed；见 core_tests.xml。预期失败为既有测试，不是本次新增成功。
- 四相机、移动模型与批处理可移植性：7 passed；见 portability_tests.xml。
- 412 场景，121952 条 XML 资源引用全部指向项目内部且存在；抽样 3 模型编译通过，见 resources.json。
- 12 个 smoke 场景四相机转换及来源契约检查通过，抽样编译包含双头部、双腕部相机，见 fourcam.json。
- 关键控制代码仅增加注释，AST 控制语句未变，见 comment_ast_check.json。

测试使用原项目已有解释器，但模块从本项目导入；解释器不是项目资源依赖。运行时请自行激活 Conda 环境。

没有重新执行完整任务、全场景两秒静置预检或 LeRobot 导出。历史 v50 报告另放 evidence/v50，不可混为本次验证。首次测试发现 UTF-8 注释被 Windows 默认编码误读及 POSIX 锁测试平台差异；已明确指定 UTF-8，并在 Windows 验证拒绝无锁批处理，修复后测试结果如上。
