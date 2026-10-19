# 英文 PDF 维护

成品：[Project Review and Operations Handover](../../output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.pdf)。英文正文：[README_EN.md](README_EN.md)。构建脚本：[build_english_pdf.py](build_english_pdf.py)，检查脚本：[validate_english_pdf.py](validate_english_pdf.py)。

本版43页，22节正文加脚本/配置附录。章节1-7为探索、实验结果与证据边界，章节8-21为运行交接，章节22为证据登记。目录可点击，PDF有书签。字体为本机 Arial/Consolas，渲染使用ReportLab。

构建使用带reportlab/pypdf/pdfplumber的文档Python；项目运维脚本仍使用项目非base Conda环境。当前文档运行时：

```powershell
& 'C:/Users/HAOZEW/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 docs/handoff/build_english_pdf.py
```

默认复用`runs/documentation_pdf_20261016/script_catalog.snapshot.json`，不把当前源码变化悄悄写进同一版目录。只有决定制作新修订版时，先人工核正文证据日期、当前状态和脚本目录，再使用`--refresh-snapshot`刷新目录及来源SHA清单。

构建不会连接机器或启动项目作业。修改后必须重新渲染全部页并视觉检查，更新`runs/documentation_pdf_20261016/visual_review.json`的真实检查记录，再运行检查脚本。不能仅改SHA就声称已审阅。检查包含PDF文本与边界、全部脚本/配置覆盖、命令参数、证据存在、离线指标复算、闭环结果与敏感信息规则。

本版证据来源哈希在`runs/documentation_pdf_20261016/evidence_sources.json`；构建哈希及目录页码在成品同目录`.sources.json`，实际检查结果在`.validation.json`。本版采用13:16 SGT证据截点，环境快照12:44 SGT、固定底盘采集取样13:13:54 SGT。后来新实验状态应在新版本中另写，不能改变本版实验分母或标签。
