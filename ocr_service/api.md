# DeepSeek-OCR-2 Service API

基于 DeepSeek-OCR-2 模型的 OCR 微服务，提供图像和 PDF 的文字识别功能。

## 基础信息

- **默认端口**: 8010
- **模型**: deepseek-ai/DeepSeek-OCR-2
- **环境变量**:
  - `OCR_PORT`: 服务端口 (默认 8010)
  - `OCR_MODEL`: 模型名称 (默认 deepseek-ai/DeepSeek-OCR-2)
  - `OCR_BASE_SIZE`: 基础尺寸 (默认 1024)
  - `OCR_IMAGE_SIZE`: 图像尺寸 (默认 768)

## 启动服务

```bash
# 直接运行
python ocr_service/main.py

# 或使用脚本
bash ocr_service/start_ocr.sh

# Docker 方式 (待实现)
docker run -d --gpus all -p 8010:8010 docmind-ocr
```

## API 端点

---

### 1. 健康检查

**GET** `/health`

检查服务状态和 GPU 可用性。

**响应示例**:
```json
{
  "status": "healthy",
  "model": "deepseek-ai/DeepSeek-OCR-2",
  "gpu_available": true
}
```

---

### 2. 单页图像 OCR

**POST** `/ocr/page`

对单个图像文件进行 OCR 识别。

**请求**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| image | File | 是 | 图像文件 (JPEG/PNG) |
| page_number | int | 否 | 页码，从 1 开始，默认 1 |

**响应**:
```json
{
  "page_number": 1,
  "markdown_text": "# 识别结果\n\n这是 OCR 识别的文本内容...",
  "success": true,
  "error": null
}
```

**示例**:
```bash
curl -X POST http://localhost:8010/ocr/page \
  -F "image=@page1.png" \
  -F "page_number=1"
```

---

### 3. PDF OCR

**POST** `/ocr/pdf`

对 PDF 文件进行批量 OCR 识别，自动将每页转换为图像并识别。

**请求**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| pdf | File | 是 | PDF 文件 |
| page_start | int | 否 | 起始页码，默认 1 |
| page_end | int | 否 | 结束页码，-1 表示全部 |

**响应**:
```json
{
  "total_pages": 10,
  "pages": [
    {
      "page_number": 1,
      "markdown_text": "第1页内容...",
      "success": true
    },
    {
      "page_number": 2,
      "markdown_text": "第2页内容...",
      "success": true
    }
  ]
}
```

**示例**:
```bash
# 识别整个 PDF
curl -X POST http://localhost:8010/ocr/pdf \
  -F "pdf=@document.pdf"

# 只识别前 5 页
curl -X POST http://localhost:8010/ocr/pdf \
  -F "pdf=@document.pdf" \
  -F "page_start=1" \
  -F "page_end=5"
```

---

## 错误响应

所有端点可能返回的错误:

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 413 | 文件过大 |
| 503 | OCR 模型未加载 |
| 500 | 内部错误 |

**错误响应示例**:
```json
{
  "page_number": 1,
  "markdown_text": "",
  "success": false,
  "error": "Failed to process image: ..."
}
```

---

## 使用注意事项

1. **GPU 要求**: 需要 CUDA 可用的 GPU 以获得最佳性能
2. **内存**: 模型需要约 8GB GPU 显存
3. **图像质量**: 建议 300 DPI 以获得最佳识别效果
4. **批量处理**: 建议批量处理时控制并发数量

---

## 与主服务集成

主服务 (FastAPI) 可以通过以下方式调用 OCR 服务:

```python
import requests

def ocr_pdf_file(pdf_path: str, page_start: int = 1, page_end: int = -1):
    with open(pdf_path, 'rb') as f:
        response = requests.post(
            'http://localhost:8010/ocr/pdf',
            files={'pdf': f},
            data={'page_start': page_start, 'page_end': page_end}
        )
    return response.json()
```

---

## 依赖

- Python 3.10+
- torch (with CUDA)
- transformers
- pymupdf (fitz)
- fastapi
- uvicorn
- flash-attn (可选，提升性能)
