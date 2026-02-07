# 目录自动创建修复

## 问题描述

当用户手动删除 `data/uploads/` 或 `data/parsed/` 目录后，上传文档时会报 500 错误，因为保存文件时目录不存在。

**错误日志**:
```
192.168.8.121:8787 - "POST /api/documents/upload HTTP/1.1" 500 Internal Server Error
```

---

## 根本原因

`StorageService` 只在初始化时调用一次 `_ensure_directories()`，如果目录在服务运行期间被删除，后续的文件保存操作会失败。

---

## 修复方案

在所有文件保存操作之前，增加目录存在性检查和自动创建。

---

## 修改详情

### 文件: `lib/docmind-ai/api/storage.py`

#### 1. `save_upload()` 方法

**修改位置**: 第 131-194 行

**新增代码**:
```python
# Ensure directory exists (in case it was deleted)
self.uploads_dir.mkdir(parents=True, exist_ok=True)
```

**插入位置**: 在生成文件名之前（第 160 行附近）

---

#### 2. `save_parse_result()` 方法

**修改位置**: 第 213-249 行

**新增代码**:
```python
# Ensure directory exists (in case it was deleted)
self.parsed_dir.mkdir(parents=True, exist_ok=True)
```

**插入位置**: 在生成文件名之前（第 232 行附近）

---

#### 3. `save_audit_report()` 方法

**修改位置**: 第 251-275 行

**新增代码**:
```python
# Ensure directory exists (in case it was deleted)
self.parsed_dir.mkdir(parents=True, exist_ok=True)
```

**插入位置**: 在生成文件名之前（第 268 行附近）

---

## 修改后的代码结构

### save_upload()
```python
async def save_upload(self, file: UploadFile, max_size: Optional[int] = None):
    # ... 验证文件类型 ...
    
    # ✅ 新增：确保目录存在
    self.uploads_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成文件名并保存
    document_id = str(uuid.uuid4())
    # ...
```

### save_parse_result()
```python
def save_parse_result(self, document_id: str, tree_data: dict, stats_data: dict):
    import json
    
    # ✅ 新增：确保目录存在
    self.parsed_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成文件名并保存
    tree_filename = f"{document_id}_tree.json"
    # ...
```

### save_audit_report()
```python
def save_audit_report(self, document_id: str, audit_data: dict):
    import json
    
    # ✅ 新增：确保目录存在
    self.parsed_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成文件名并保存
    audit_filename = f"{document_id}_audit_report.json"
    # ...
```

---

## 测试验证

### 测试步骤:

1. **启动服务**
   ```bash
   python -m lib.docmind-ai.api.main
   ```

2. **删除目录**
   ```bash
   rm -rf data/uploads
   rm -rf data/parsed
   ```

3. **上传文档**
   - 通过前端或 API 上传一个 PDF 文档
   - 启用审计功能

4. **验证结果**
   - ✅ 上传成功，返回 200
   - ✅ `data/uploads/` 目录自动创建
   - ✅ `data/parsed/` 目录自动创建
   - ✅ 文件正常保存：
     - `data/uploads/{document_id}.pdf`
     - `data/parsed/{document_id}_tree.json`
     - `data/parsed/{document_id}_stats.json`
     - `data/parsed/{document_id}_audit_report.json`

---

## 影响范围

### ✅ 受益场景:
1. 用户手动删除目录后继续使用
2. 清理测试数据后重新上传
3. Docker容器重启后目录丢失
4. 多实例部署时目录同步问题

### ⚠️ 注意事项:
1. `mkdir(parents=True, exist_ok=True)` 是幂等操作，不会影响现有目录
2. 每次保存都会检查目录，性能开销极小（文件系统缓存）
3. 不影响并发安全性（多进程同时创建同一目录是安全的）

---

## 其他相关代码

### database.py 的目录创建

`database.py` 在初始化时也会创建目录：

```python
def _ensure_data_dir(self):
    """Ensure data directory exists."""
    self.data_dir.mkdir(parents=True, exist_ok=True)
    
    # Create subdirectories
    (self.data_dir / "uploads").mkdir(exist_ok=True)
    (self.data_dir / "parsed").mkdir(exist_ok=True)
```

这确保了服务启动时目录存在，但不能防止运行期间被删除的情况。

---

## 总结

通过在每个文件保存操作前检查并创建必要的目录，系统现在可以自动恢复被删除的目录，提高了鲁棒性和用户体验。

**修改时间**: 2026-02-06  
**修改文件**: `lib/docmind-ai/api/storage.py`  
**影响方法**: `save_upload()`, `save_parse_result()`, `save_audit_report()`
