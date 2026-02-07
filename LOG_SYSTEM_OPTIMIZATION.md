# docmind-ai 日志系统优化说明

## 优化概述

docmind-ai 的运行日志已从控制台输出优化为按 PDF UUID 分文件保存到 `debug_logs` 目录，方便调试和问题定位。

## 主要改动

### 1. 新增日志工具类 (`api/logger_utils.py`)

提供了按文档 UUID 创建独立日志文件的功能：

```python
from api.logger_utils import create_document_logger

# 为文档创建专属日志记录器
doc_logger = create_document_logger(document_id, "parse")
doc_logger.info("开始解析文档")
doc_logger.error("解析失败", exc_info=True)
```

**主要功能：**
- 为每个文档创建独立的日志文件：`debug_logs/{uuid}.log`
- 支持日志级别：DEBUG, INFO, WARNING, ERROR
- 同时输出到文件和控制台
- 自动记录会话开始和结束时间
- 提供旧日志清理功能

### 2. 修改文档处理路由 (`api/document_routes.py`)

在 `parse_document_background` 函数中集成了文件日志：

```python
# 创建文档专属日志记录器
doc_logger = create_document_logger(document_id, "parse")

# 记录关键信息
doc_logger.info(f"开始解析文档: {file_path}")
doc_logger.info(f"文件类型: {file_type}, 模型: {model}")
doc_logger.info(f"解析配置: {json.dumps(parse_config, indent=2, ensure_ascii=False)}")

# 记录各阶段进度
doc_logger.info("开始 PDF 解析流程")
doc_logger.info("PDF 解析完成")
doc_logger.info("开始树结构质量审计")

# 记录性能统计
doc_logger.info(f"解析完成: {document_id}")
doc_logger.info(f"总耗时: {duration_ms}ms")
doc_logger.info(f"LLM 调用次数: {perf_summary.get('total_llm_calls', 0)}")

# 记录错误
doc_logger.error(f"解析失败: {error_msg}")
doc_logger.error(f"错误堆栈:\n{traceback.format_exc()}")

# 关闭日志记录器
get_document_logger().close_logger(document_id)
```

### 3. 修改 PageIndexV2 主程序 (`pageindex_v2/main.py`)

- 在 `__init__` 方法中添加 `document_id` 参数
- 根据是否有 `document_id` 创建文件日志记录器或控制台日志记录器
- 修改 `log_progress` 方法同时记录到文件和控制台

```python
class PageIndexV2:
    def __init__(self, options: Optional[ProcessingOptions] = None, document_id: Optional[str] = None):
        self.document_id = document_id
        
        # Setup logger
        if document_id:
            # 使用文件日志器（API 调用）
            from api.logger_utils import create_document_logger
            self.logger = create_document_logger(document_id, "pageindex_v2")
        else:
            # 使用标准控制台日志器（独立运行）
            self.logger = logging.getLogger("pageindex_v2")
```

### 4. 修改适配器 (`pageindex_v2/legacy_adapter.py`)

传递 `document_id` 参数给 PageIndexV2：

```python
# 获取 document_id（从 progress_callback）
doc_id = _setup_progress_callback()

# 创建处理器时传入 document_id
processor = PageIndexV2(options, document_id=doc_id)
```

### 5. 更新 .gitignore

添加日志文件忽略规则：

```gitignore
# Debug logs (按 UUID 保存的调试日志)
lib/docmind-ai/debug_logs/*.log
```

### 6. 创建 debug_logs 目录

```
lib/docmind-ai/
├── debug_logs/
│   ├── .gitkeep                    # 保持目录结构
│   ├── README.md                   # 使用说明
│   └── {uuid}.log                  # 文档日志文件（运行时生成）
```

## 日志文件格式

每个文档的日志文件包含：

```
2026-02-06 17:30:00 - doc.{uuid}.parse - INFO - ================================================================================
2026-02-06 17:30:00 - doc.{uuid}.parse - INFO - 日志会话开始 - 文档ID: {uuid}
2026-02-06 17:30:00 - doc.{uuid}.parse - INFO - 日志文件: /path/to/debug_logs/{uuid}.log
2026-02-06 17:30:00 - doc.{uuid}.parse - INFO - 时间: 2026-02-06 17:30:00
2026-02-06 17:30:00 - doc.{uuid}.parse - INFO - ================================================================================
2026-02-06 17:30:01 - doc.{uuid}.parse - INFO - 开始解析文档: /path/to/document.pdf
2026-02-06 17:30:01 - doc.{uuid}.parse - INFO - 文件类型: pdf, 模型: deepseek-chat
2026-02-06 17:30:01 - doc.{uuid}.parse - INFO - 解析配置: {
  "toc_check_pages": 20,
  "max_pages_per_node": 10,
  ...
}
2026-02-06 17:30:02 - doc.{uuid}.parse - INFO - 开始 PDF 解析流程
2026-02-06 17:30:02 - doc.{uuid}.pageindex_v2 - INFO - PageIndex V2 - Document Structure Extractor
...
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - PDF 解析完成
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - ==================================================
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - 解析完成: {uuid}
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - 总耗时: 328500ms (328.50s)
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - LLM 调用次数: 45
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - Token 使用量: 125,000 input, 8,500 output
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - 树结构统计: {
  "total_nodes": 120,
  "max_depth": 4,
  ...
}
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - ==================================================
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - 文档状态已更新为 completed
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - ================================================================================
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - 日志会话结束 - 文档ID: {uuid}
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - 时间: 2026-02-06 17:35:30
2026-02-06 17:35:30 - doc.{uuid}.parse - INFO - ================================================================================
```

## 使用方法

### 查看特定文档的日志

1. 找到文档的 UUID（从 API 响应或数据库中获取）
2. 打开对应的日志文件：`debug_logs/{uuid}.log`

```bash
# 查看完整日志
cat debug_logs/a1b2c3d4-e5f6-7890-abcd-ef1234567890.log

# 实时查看最新日志
tail -f debug_logs/a1b2c3d4-e5f6-7890-abcd-ef1234567890.log

# 搜索错误
grep -i "error" debug_logs/a1b2c3d4-e5f6-7890-abcd-ef1234567890.log
```

### 清理旧日志

```python
from api.logger_utils import get_document_logger

# 清理 7 天前的日志文件
get_document_logger().cleanup_old_logs(days=7)
```

或手动清理：

```bash
# 删除 7 天前的日志
find debug_logs -name "*.log" -mtime +7 -delete
```

## 优势

1. **按文档分离**：每个 PDF 的日志独立保存，互不干扰
2. **易于定位**：通过 UUID 快速找到特定文档的完整处理日志
3. **详细记录**：包含配置、进度、性能统计、错误堆栈等完整信息
4. **便于调试**：出现问题时可以查看完整的处理流程
5. **保留控制台输出**：同时输出到文件和控制台，不影响实时监控
6. **自动管理**：支持自动清理旧日志，节省磁盘空间

## 兼容性

- ✅ 向后兼容：不影响现有功能
- ✅ 控制台输出：仍然保留控制台日志输出
- ✅ 独立运行：PageIndexV2 独立运行时使用标准控制台日志
- ✅ API 调用：通过 API 调用时自动使用文件日志

## 相关文件

- `api/logger_utils.py` - 日志工具类实现
- `api/document_routes.py` - 文档处理路由（集成日志）
- `pageindex_v2/main.py` - PageIndexV2 主程序（支持文件日志）
- `pageindex_v2/legacy_adapter.py` - 适配器（传递 document_id）
- `debug_logs/README.md` - 日志目录使用说明
- `.gitignore` - Git 忽略配置（排除日志文件）

## 测试建议

1. 上传一个 PDF 文档进行解析
2. 检查 `debug_logs` 目录是否生成了对应的日志文件
3. 查看日志文件内容是否完整记录了处理过程
4. 验证控制台输出是否正常（未受影响）

## 常见问题

**Q: 日志文件太大怎么办？**
A: 使用 `cleanup_old_logs(days=7)` 方法定期清理旧日志。

**Q: 如何禁用文件日志？**
A: 修改 `logger_utils.py` 中的 `create_document_logger` 函数，移除文件 handler。

**Q: 日志编码问题？**
A: 日志文件使用 UTF-8 编码，确保文本编辑器也使用 UTF-8 打开。

**Q: 并发处理时日志会混淆吗？**
A: 不会，每个文档有独立的日志文件，不会相互干扰。

## 总结

通过本次优化，docmind-ai 的日志系统更加完善，方便开发者调试和排查问题。日志文件按 UUID 组织，包含完整的处理流程和性能数据，大大提升了可维护性和可调试性。
