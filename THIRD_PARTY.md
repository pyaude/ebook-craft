# 第三方代码、模型与字体

本项目通过依赖安装复用上游代码，不复制上游源码到应用目录。分发打包程序时，需要同时保留各依赖及其传递依赖的许可证。

| 组件 | 用途 | 上游 | 许可证 |
|---|---|---|---|
| RapidOCR / rapidocr-onnxruntime 1.2.3 | 文本检测、方向分类、识别；发行包包含 ONNX 权重 | https://github.com/RapidAI/RapidOCR | Apache-2.0 |
| PaddleOCR | RapidOCR 模型来源 | https://github.com/PaddlePaddle/PaddleOCR | Apache-2.0 |
| OpenCV | 插图区域检测、图像形态学与连通区域分析 | https://opencv.org/ | Apache-2.0（当前安装版本） |
| ONNX Runtime | CPU 模型推理 | https://github.com/microsoft/onnxruntime | MIT |
| pypdfium2 / PDFium | PDF 渲染 | https://github.com/pypdfium2-team/pypdfium2 | pypdfium2 为 Apache-2.0 或 BSD-3-Clause；PDFium 及其第三方代码另附许可证 |
| ReportLab | PDF 生成 | https://www.reportlab.com | BSD |
| FastAPI | Web API | https://github.com/fastapi/fastapi | MIT |
| 霞鹜文楷 | PDF/EPUB 嵌入字体 | https://github.com/lxgw/LxgwWenKai | SIL OFL 1.1；见 assets/OFL.txt |


本项目自行编写的代码采用 MIT 协议；EPUB 打包使用 Python 标准库自行实现，不再依赖 EbookLib。第三方代码、模型和字体仍适用各自许可证，不因本项目采用 MIT 而变更。输入书籍的内容权利不属于本项目授权范围。
