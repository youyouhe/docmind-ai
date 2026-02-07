# Tree Quality Auditor 🔍

**后处理质量控制Agent** - 审核并自动修复pageindex_v2生成的tree.json

---

## 🎯 设计理念

PageIndex V2算法是**通用文档解析器**，针对各种文档类型设计。但对于特定领域（如招标文件、学术论文）可能会产生一些问题。

Tree Auditor作为**后处理层**，专门负责：
- ✅ 检测并修复常见问题（标题过长、格式错误、内容重复）
- ✅ 针对文档类型优化结构
- ✅ 生成详细的审核报告

**优势**：
1. **不破坏主算法** - 保持pageindex_v2的通用性
2. **可持续优化** - 独立迭代，添加新规则
3. **可见性高** - 清楚知道修复了什么

---

## 📦 功能特性

### 1. **规则检查**（Rule-based Validation）

- **标题长度检查** - 移除过长的标题（可能是内容误判）
- **格式验证** - 针对招标文件检查标题格式
- **标点检查** - 移除标题末尾的标点符号
- **条款识别** - 区分"标题"和"条款内容"

### 2. **LLM深度审核**（AI-powered Audit）

- 利用DeepSeek模型进行语义理解
- 识别"伪标题"（完整句子误判为标题）
- 高置信度修复建议

### 3. **内容去重**（Content Deduplication）

- 检测重复的content字段
- 自动移除重复内容，只保留一份

### 4. **审核报告**（Audit Report）

生成详细的JSON报告：
```json
{
  "quality_score": 85.5,
  "summary": {
    "issues_found": 12,
    "fixes_applied": 10,
    "nodes_removed": 5
  },
  "issues_by_type": {
    "title_too_long": 3,
    "invalid_title_format": 2
  },
  "recommendations": [
    "Many titles are too long. Consider improving Gap Filler prompts."
  ]
}
```

---

## 🚀 使用方法

### **方法1: 独立运行（推荐测试）**

```bash
cd lib/docmind-ai
python test_tree_auditor.py
```

输出：
```
📄 Audited tree: data/parsed/xxx_tree_audited.json
📊 Report: data/parsed/xxx_audit_report.json
📈 Quality Score: 85.5/100
```

### **方法2: 集成到API**

在`api/document_routes.py`中添加：

```python
from pageindex_v2.phases.tree_auditor import TreeAuditor

async def parse_document_background(...):
    # ... 现有的解析流程 ...
    
    # Phase 8: Tree Auditing (新增)
    auditor = TreeAuditor(llm=llm_client, debug=True)
    audited_tree, report = await auditor.audit_and_fix(
        tree=page_index_tree,
        document_type="auto"  # 自动检测文档类型
    )
    
    # 保存审核报告
    report_path = storage.save_audit_report(document_id, report)
    
    # 使用审核后的tree
    api_tree = ParseService.convert_page_index_to_api_format(audited_tree)
```

### **方法3: 命令行工具**

```bash
# 审核单个文件
python -m pageindex_v2.phases.tree_auditor \
  --input data/parsed/xxx_tree.json \
  --output data/parsed/xxx_tree_audited.json
```

---

## 📊 审核效果对比

### **原始输出示例**

```json
{
  "id": "0005",
  "title": "4、投标人不得相互串通投标报价，不得妨碍其他投标人的公平竞争，不得损害采购人或其他投标人的合法权益，",
  "level": 3,
  "content": "一、总则\n（一）适用范围\n本招标文件适用于...",
  "page_start": 10,
  "page_end": 11
}
```

### **审核后输出**

```json
{
  "id": "0003",
  "title": "（一）适用范围",
  "level": 3,
  "content": "本招标文件适用于...",
  "page_start": 10,
  "page_end": 10
}
```

**改进点**：
- ❌ 移除了"4、投标人不得..."（识别为条款内容）
- ✅ 保留了"（一）适用范围"（真正的小节标题）
- ✅ 移除了重复的content

---

## 🔧 配置选项

### **文档类型检测**

```python
auditor.audit_and_fix(
    tree=tree,
    document_type="tender"  # tender/academic/technical/general
)
```

**支持的类型**：
- `tender` - 招标文件（严格的标题格式检查）
- `academic` - 学术文档（宽松的标题要求）
- `technical` - 技术文档（允许API/函数名作为标题）
- `general` - 通用文档
- `auto` - 自动检测（默认）

### **LLM配置**

```python
# 使用DeepSeek（推荐）
llm = LLMClient(provider="deepseek", model="deepseek-chat")

# 使用OpenAI
llm = LLMClient(provider="openai", model="gpt-4o-mini")

# 不使用LLM（仅规则检查）
auditor = TreeAuditor(llm=None)
```

---

## 📈 性能数据

**测试文件**: 62页招标文件，25个节点

| 阶段 | 耗时 | 说明 |
|------|------|------|
| 规则检查 | <1s | 快速本地验证 |
| LLM审核 | 3-5s | DeepSeek API调用 |
| 内容去重 | <1s | 哈希匹配 |
| **总计** | **~5s** | 可接受的开销 |

**效果**：
- 移除5个无效节点（20%）
- 修复3个标题格式问题
- 去重4个重复content
- 质量评分：85.5/100

---

## 🎨 自定义规则

### **添加新的验证规则**

编辑`tree_auditor.py`：

```python
def _rule_based_validation(self, structure, document_type):
    # ... 现有规则 ...
    
    # 新增：检查标题是否包含特定关键词
    if document_type == "tender":
        forbidden_keywords = ["投标人不得", "采购人有权"]
        if any(kw in title for kw in forbidden_keywords):
            self.issues.append({
                "type": "forbidden_keyword_in_title",
                "node_id": node.get("node_id"),
                "title": title
            })
            return None  # 移除节点
```

### **调整LLM Prompt**

修改`_llm_based_audit`中的prompt：

```python
prompt = f"""Review these TOC entries from a {document_type} document.

Custom Rules:
- Reject titles containing "不得" or "应当" (these are clauses)
- Accept only titles < 30 chars
...
"""
```

---

## 🐛 常见问题

### Q1: 为什么有些节点被移除了？

**A**: 审核器会移除以下类型的节点：
1. 标题过长（>50字符）
2. 标题为完整句子（包含"不得"、"应当"等）
3. LLM高置信度判定为非标题

查看`_audit_report.json`中的`detailed_fixes`了解详情。

### Q2: 如何关闭LLM审核？

**A**: 传入`llm=None`：
```python
auditor = TreeAuditor(llm=None, debug=True)
```

只会执行规则检查，不调用LLM。

### Q3: 审核会修改原始文件吗？

**A**: **不会**。审核器会生成：
- `xxx_tree_audited.json` - 审核后的tree
- `xxx_audit_report.json` - 审核报告

原始`xxx_tree.json`保持不变。

---

## 🔮 未来改进

- [ ] 支持更多文档类型（合同、报告、手册）
- [ ] 添加交互式审核模式（让用户确认修复）
- [ ] 集成到Web UI（可视化审核流程）
- [ ] 支持自定义规则配置文件（YAML）
- [ ] 添加A/B测试比较工具

---

## 📝 示例输出

### **审核报告示例**

```json
{
  "document_type": "tender",
  "total_nodes": 20,
  "quality_score": 85.5,
  "summary": {
    "issues_found": 12,
    "fixes_applied": 10,
    "nodes_removed": 5,
    "content_deduplicated": 4
  },
  "issues_by_type": {
    "title_too_long": 3,
    "invalid_title_format": 2,
    "title_ends_with_punctuation": 2,
    "duplicate_content": 4
  },
  "recommendations": [
    "Invalid title formats detected. Gap Filler may be extracting content clauses as headings.",
    "Duplicate content detected. Consider improving page range calculation."
  ]
}
```

---

## 👥 贡献

欢迎贡献新的验证规则和文档类型支持！

**贡献方向**：
1. 添加新文档类型的识别规则
2. 优化LLM审核Prompt
3. 提供更多测试样本

---

## 📄 许可

MIT License

---

**Happy Auditing!** 🎉
