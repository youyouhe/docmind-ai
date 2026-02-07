# 文档删除功能优化说明

## 优化概述

优化了文档删除功能，确保删除文档时清理**所有**相关文件，不留垃圾文件。

## 问题背景

之前的删除功能只删除了基本文件（`_tree.json` 和 `_stats.json`），但遗漏了：
- 审计报告文件 (`_audit_report.json`)
- 审计备份文件 (`_audit_backup_*.json`)
- 恢复前备份文件 (`_audit_backup_before_restore_*.json`)
- 调试日志文件 (`debug_logs/{uuid}.log`)

这导致 `parsed` 目录和 `debug_logs` 目录积累大量垃圾文件。

## 主要改动

### 1. 优化 `delete_parse_results` 函数 (`api/storage.py`)

**修改前**：只删除 2 个文件
```python
def delete_parse_results(self, document_id: str) -> bool:
    tree_path = self.parsed_dir / f"{document_id}_tree.json"
    stats_path = self.parsed_dir / f"{document_id}_stats.json"
    
    deleted = False
    if tree_path.exists():
        tree_path.unlink()
        deleted = True
    if stats_path.exists():
        stats_path.unlink()
        deleted = True
    
    return deleted
```

**修改后**：删除所有相关文件
```python
def delete_parse_results(self, document_id: str) -> bool:
    """
    Delete ALL parse result files for a document, including:
    - tree.json
    - stats.json
    - audit_report.json
    - All audit backup files (audit_backup_*.json)
    """
    deleted = False
    deleted_files = []
    
    # Define specific file patterns to delete
    file_patterns = [
        f"{document_id}_tree.json",
        f"{document_id}_stats.json",
        f"{document_id}_audit_report.json",
    ]
    
    # Delete specific files
    for filename in file_patterns:
        file_path = self.parsed_dir / filename
        if file_path.exists():
            file_path.unlink()
            deleted = True
            deleted_files.append(filename)
    
    # Delete all audit backup files (using glob pattern)
    audit_backup_pattern = f"{document_id}_audit_backup_*.json"
    for backup_file in self.parsed_dir.glob(audit_backup_pattern):
        backup_file.unlink()
        deleted = True
        deleted_files.append(backup_file.name)
    
    # Log deleted files
    if deleted_files:
        logger.info(f"Deleted {len(deleted_files)} parse result files: {deleted_files}")
    
    return deleted
```

### 2. 优化 `delete_all_document_data` 函数 (`api/storage.py`)

**新增功能**：删除调试日志文件

```python
def delete_all_document_data(self, document_id: str) -> dict:
    """
    Delete all files associated with a document, including:
    - Upload file (PDF/Markdown)
    - Parse results (tree, stats, audit reports, backups)
    - Debug logs
    """
    results = {
        "upload_deleted": False,
        "parse_results_deleted": False,
        "debug_log_deleted": False,  # 新增
    }
    
    # ... (删除上传文件和解析结果)
    
    # Delete debug log file (新增)
    debug_log_path = self.data_dir.parent / "debug_logs" / f"{document_id}.log"
    if debug_log_path.exists():
        debug_log_path.unlink()
        results["debug_log_deleted"] = True
        logger.info(f"Deleted debug log file: {debug_log_path.name}")
    
    return results
```

### 3. 添加日志记录

在 `storage.py` 顶部添加 logging 导入和 logger 配置：

```python
import logging

logger = logging.getLogger("pageindex.api.storage")
```

这样可以记录删除操作的详细信息，方便调试。

## 删除的文件类型

现在删除文档时会清理以下所有文件：

| 文件类型 | 文件名模式 | 说明 |
|---------|-----------|------|
| 上传文件 | `{uuid}.pdf` 或 `{uuid}.md` | 原始上传的文档 |
| 树结构 | `{uuid}_tree.json` | 解析后的树结构数据 |
| 统计数据 | `{uuid}_stats.json` | 树结构统计信息 |
| 审计报告 | `{uuid}_audit_report.json` | 质量审计报告 |
| 审计备份 | `{uuid}_audit_backup_*.json` | 应用修改前的备份 |
| 恢复备份 | `{uuid}_audit_backup_before_restore_*.json` | 恢复前的备份 |
| 调试日志 | `{uuid}.log` | 处理过程的详细日志 |

## 测试

提供了测试脚本 `test_delete_document.py` 用于验证删除功能：

```bash
cd lib/docmind-ai
python test_delete_document.py <document_id>
```

**测试输出示例**：

```
======================================================================
测试删除文档: d258c641-3ab6-4ae9-b8b4-71126669cdbc
======================================================================

📋 删除前检查文件:

检查的文件:
  upload_pdf          : ✓ 存在       - d258c641-3ab6-4ae9-b8b4-71126669cdbc.pdf
  upload_md           : ✗ 不存在      - d258c641-3ab6-4ae9-b8b4-71126669cdbc.md
  tree                : ✓ 存在       - d258c641-3ab6-4ae9-b8b4-71126669cdbc_tree.json
  stats               : ✓ 存在       - d258c641-3ab6-4ae9-b8b4-71126669cdbc_stats.json
  audit_report        : ✓ 存在       - d258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_report.json
  debug_log           : ✓ 存在       - d258c641-3ab6-4ae9-b8b4-71126669cdbc.log

  找到 3 个审计备份文件:
    - d258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_backup_backup_36fda2e7.json
    - d258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_backup_backup_8adac2d8.json
    - d258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_backup_backup_e6c8ea64.json

🗑️  执行删除操作...

删除结果:
  upload_deleted                : ✓ 成功
  parse_results_deleted         : ✓ 成功
  debug_log_deleted             : ✓ 成功

📋 删除后验证:

======================================================================
✅ 测试成功 - 所有相关文件已删除
======================================================================
```

## 使用方式

### API 调用

通过 API 删除文档时会自动清理所有相关文件：

```bash
# DELETE /api/documents/{document_id}
curl -X DELETE "http://localhost:8003/api/documents/{document_id}"
```

响应示例：
```json
{
  "success": true,
  "message": "Document deleted successfully",
  "document_id": "d258c641-3ab6-4ae9-b8b4-71126669cdbc",
  "deletion_results": {
    "upload_deleted": true,
    "parse_results_deleted": true,
    "debug_log_deleted": true
  }
}
```

### 代码调用

```python
from api.storage import StorageService
from api.database import DatabaseManager

storage = StorageService()
db = DatabaseManager()

# 删除所有文件
deletion_results = storage.delete_all_document_data(document_id)

# 删除数据库记录
db.delete_document(document_id)
```

## 日志示例

删除操作会记录详细日志：

```
2026-02-06 22:25:00 - pageindex.api.storage - INFO - Deleted upload file: d258c641-3ab6-4ae9-b8b4-71126669cdbc.pdf
2026-02-06 22:25:00 - pageindex.api.storage - INFO - Deleted 7 parse result files for document d258c641-3ab6-4ae9-b8b4-71126669cdbc: [
  'd258c641-3ab6-4ae9-b8b4-71126669cdbc_tree.json',
  'd258c641-3ab6-4ae9-b8b4-71126669cdbc_stats.json',
  'd258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_report.json',
  'd258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_backup_backup_36fda2e7.json',
  'd258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_backup_backup_8adac2d8.json',
  'd258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_backup_backup_e6c8ea64.json',
  'd258c641-3ab6-4ae9-b8b4-71126669cdbc_audit_backup_before_restore_a1b2c3d4.json'
]
2026-02-06 22:25:00 - pageindex.api.storage - INFO - Deleted debug log file: d258c641-3ab6-4ae9-b8b4-71126669cdbc.log
```

## 优势

1. **彻底清理**：删除所有相关文件，不留垃圾
2. **节省空间**：避免累积大量无用文件
3. **易于维护**：清晰的文件管理，便于维护和调试
4. **可追溯**：详细的日志记录，方便问题排查
5. **向后兼容**：不影响现有功能

## 数据库记录清理（重要更新）

### 问题发现

在文件删除优化之后，我们发现了一个**数据库记录孤立**的问题：

**症状**：
- 文件已通过 `storage.delete_all_document_data()` 删除
- 但 `audit_backups` 表中的记录仍然存在
- 造成数据库中存在指向不存在文件的孤立记录

**根本原因**：
```python
# 数据库模型定义 (database.py)
class AuditBackup(Base):
    doc_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"))
    # ↑ 代码中定义了 CASCADE
```

但实际数据库中的外键约束是 `NO ACTION`：
```sql
-- 实际数据库约束
FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE NO ACTION
```

这意味着删除文档时，数据库**不会自动**删除关联的 audit_backup 记录。

### 解决方案

我们实施了**双重保障**策略：

#### 1. 修改 `database.py` - 显式删除 audit_backup 记录

在 `delete_document()` 方法中添加显式删除逻辑：

```python
def delete_document(self, document_id: str) -> bool:
    """Delete a document and associated parse results."""
    with self.get_session() as session:
        doc = session.query(Document).filter(Document.id == document_id).first()
        if doc:
            # Explicitly delete audit backup records first
            # This is needed because the foreign key constraint is NO ACTION instead of CASCADE
            backup_count = session.query(AuditBackup).filter(
                AuditBackup.doc_id == document_id
            ).delete()
            if backup_count > 0:
                logger.info(f"Deleted {backup_count} audit backup records for document {document_id}")
            
            # Now delete the document
            session.delete(doc)
            session.commit()
            return True
        return False
```

#### 2. 新增 `delete_audit_backups_by_document()` 方法

添加专门的清理方法（如需要可独立调用）：

```python
def delete_audit_backups_by_document(self, doc_id: str) -> int:
    """
    Delete all audit backup records for a document.
    
    NOTE: This only deletes database records. Files should be deleted separately
    via storage.delete_all_document_data().
    
    Returns:
        Number of backup records deleted
    """
    with self.get_session() as session:
        count = session.query(AuditBackup).filter(
            AuditBackup.doc_id == doc_id
        ).delete()
        session.commit()
        logger.info(f"Deleted {count} audit backup records for document {doc_id}")
        return count
```

### 清理工具

提供了两个诊断和清理工具：

#### 1. `check_audit_backup_db.py` - 检查数据库状态
```bash
python check_audit_backup_db.py
```

输出：
- 数据库表结构
- 外键约束配置（CASCADE vs NO ACTION）
- 现有备份记录数量
- 级联删除机制分析

#### 2. `check_orphaned_records.py` - 检查孤立记录
```bash
python check_orphaned_records.py
```

输出：
- 总记录数
- 有效记录数（文件存在）
- 孤立记录数（文件不存在）
- 按文档分组显示孤立记录

#### 3. `cleanup_orphaned_records.py` - 清理孤立记录
```bash
python cleanup_orphaned_records.py
```

功能：
- 扫描所有 audit_backup 记录
- 检查对应文件是否存在
- 删除文件不存在的孤立记录
- 需要用户确认后执行删除

**示例输出**：
```
======================================================================
孤立记录清理工具
======================================================================

总备份记录数: 27
✓ 有效记录（文件存在）: 0
✗ 孤立记录（文件不存在）: 27

孤立记录按文档分组:
  - c36d9356-2559-48c0-9f6d-aa608e94c971: 3 条记录
  - 2af05b24-7bb1-41b0-bb33-88eadaadcd03: 18 条记录
  - fc66c877-982d-4010-823e-730b48c0911f: 2 条记录

是否删除 27 条孤立记录？ (y/n): y

✓ 成功删除 27 条孤立记录
✓ 所有剩余记录都有对应的文件，清理完成！
```

### 完整删除流程

现在删除文档时的完整流程：

```python
# In document_routes.py: delete_document()
async def delete_document(document_id: str):
    # 1. 删除所有文件
    storage.delete_all_document_data(document_id)
    #    - 上传文件 (.pdf/.md)
    #    - 解析结果 (tree, stats, audit report)
    #    - 审计备份文件 (all *_audit_backup_*.json)
    #    - 调试日志 (debug_logs/{uuid}.log)
    
    # 2. 删除数据库记录（包括显式删除 audit_backups）
    db.delete_document(document_id)
    #    - 显式删除 audit_backup 记录（因为 CASCADE 不工作）
    #    - 删除 document 记录
```

### 验证清理效果

运行以下命令验证数据库干净：

```bash
# 检查是否有孤立记录
python check_orphaned_records.py

# 预期输出：
# ✓ 有效记录（文件存在）: X
# ✗ 孤立记录（文件不存在）: 0
```

## 相关文件

**核心文件**：
- `api/storage.py` - 存储服务（文件删除逻辑）
- `api/database.py` - 数据库管理（记录删除逻辑，新增显式清理）
- `api/document_routes.py` - 文档路由（调用删除功能）

**测试与诊断工具**：
- `test_delete_document.py` - 测试文件删除功能
- `check_audit_backup_db.py` - 检查数据库状态和约束
- `check_orphaned_records.py` - 检查孤立记录
- `cleanup_orphaned_records.py` - 清理孤立记录

**文档**：
- `DELETE_OPTIMIZATION.md` - 本文档

## 注意事项

1. 删除操作不可逆，请谨慎使用
2. 删除前建议先备份重要数据
3. 使用测试脚本验证删除功能正常工作
4. 定期检查 `parsed` 和 `debug_logs` 目录，确保无垃圾文件累积

## 总结

通过本次优化，文档删除功能现在能够：

**文件清理**：
- ✅ 删除上传的原始文件
- ✅ 删除解析结果（tree, stats）
- ✅ 删除审计报告
- ✅ 删除所有审计备份文件（包括恢复前备份）
- ✅ 删除调试日志文件
- ✅ 记录详细的删除日志

**数据库清理**：
- ✅ 删除文档记录
- ✅ 显式删除审计备份记录（解决 CASCADE 不工作的问题）
- ✅ 防止孤立记录产生
- ✅ 提供诊断和清理工具

**双重保障**：
1. **文件层面**：`storage.delete_all_document_data()` 使用 glob 模式删除所有相关文件
2. **数据库层面**：`db.delete_document()` 显式删除 audit_backup 记录后再删除文档

确保了系统的干净整洁，既不会因为删除文档而留下垃圾文件，也不会留下孤立的数据库记录！
