# Gap Filler - 页面补丁功能

## 概述

Gap Filler 是 pageindex_v2 的后处理模块，用于自动检测和填充 TOC 提取过程中遗漏的页面。

## 问题背景

某些 PDF 文档的 embedded TOC（嵌入式目录）可能不完整，例如：
- TOC 只覆盖主要章节（1-66 页）
- 附录、参考文献等内容（67-78 页）未包含在 TOC 中

如果只依赖 embedded TOC，会导致这些页面完全遗漏，影响文档检索的完整性。

## 解决方案

### 设计思路

1. **检测 Gap（页面缺口）**
   - 分析生成的 tree structure
   - 找出所有未被覆盖的页面范围

2. **生成补丁 TOC**
   - 对每个缺口调用 LLM 分析内容
   - 生成该范围的目录结构

3. **追加到 Tree**
   - 将补丁节点追加到 structure 末尾
   - 标记为 `is_gap_fill: true`

### 工作流程

```
┌─────────────────┐
│  Original Tree  │  (Pages 1-66 covered)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Analyze Gap    │  → Detect: Pages 67-78 missing
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Generate Patch │  → LLM analyzes Pages 67-78
└────────┬────────┘  → Extracts TOC structure
         │
         ▼
┌─────────────────┐
│  Append Patch   │  → Add nodes to tree
└────────┬────────┘  → Mark as gap_fill: true
         │
         ▼
┌─────────────────┐
│  Complete Tree  │  (All 78 pages covered)
└─────────────────┘
```

## 使用方法

### 自动启用

Gap Filler 在 `pageindex_v2` 的 Phase 7 自动执行：

```python
from pageindex_v2 import page_index_main, config

opt = config(model='deepseek-chat')
result = page_index_main('document.pdf', opt)

# result 自动包含 gap_fill_info
print(result['gap_fill_info'])
```

### 手动调用

也可以单独使用 Gap Filler 对已有结构进行后处理：

```python
from pageindex_v2.utils.gap_filler import fill_structure_gaps
from pageindex_v2.core.llm_client import LLMClient
from pageindex_v2.core.pdf_parser import PDFParser

llm = LLMClient(provider='deepseek', model='deepseek-chat')
parser = PDFParser()

# 加载已有结构
with open('structure.json') as f:
    structure_data = json.load(f)

# 填充 gap
updated_data = await fill_structure_gaps(
    structure_data=structure_data,
    pdf_path='document.pdf',
    llm=llm,
    parser=parser,
    debug=True
)

# 保存更新后的结构
with open('structure_complete.json', 'w') as f:
    json.dump(updated_data, f, indent=2)
```

## 输出格式

### gap_fill_info 字段

```json
{
  "gap_fill_info": {
    "gaps_found": 1,
    "gaps_filled": [[67, 78]],
    "original_coverage": "66/78",
    "coverage_percentage": 84.6
  }
}
```

### 补丁节点标记

所有由 Gap Filler 生成的节点都包含 `is_gap_fill: true` 标记：

```json
{
  "title": "附录 A - 技术规格",
  "start_index": 67,
  "end_index": 70,
  "node_id": "gap_67_0000",
  "is_gap_fill": true,  ⬅️ 补丁标记
  "nodes": [...]
}
```

## 测试工具

使用 `test_gap_filler.py` 分析结构的 gap 填充情况：

```bash
python test_gap_filler.py results/document_structure.json
```

输出示例：

```
======================================================================
GAP FILLER ANALYSIS REPORT
======================================================================

📄 Source File: document.pdf
📊 Total Pages: 78

🔧 Gap Fill Information:
   Gaps Found: 1
   Original Coverage: 66/78 (84.6%)

   Gap Ranges:
      • Pages 67-78 (12 pages)

📋 Structure:
   Total Nodes: 65
   Regular Nodes: 61
   Gap Fill Nodes: 4

✅ Final Coverage:
   Pages Covered: 78/78 (100.0%)
   ✓ All pages covered!
======================================================================
```

## 配置选项

Gap Filler 当前没有额外配置选项，自动在 Phase 7 执行。未来可能添加：

- `enable_gap_fill`: 是否启用 gap filling (默认 true)
- `gap_threshold`: 最小 gap 大小（小于此值的 gap 不处理）
- `max_gap_size`: 最大 gap 大小（超过此值的 gap 跳过）

## 技术细节

### 核心类：GapFiller

位置：`pageindex_v2/utils/gap_filler.py`

主要方法：

1. **analyze_coverage(tree, total_pages)**
   - 输入：tree structure, 总页数
   - 输出：覆盖分析（covered_pages, missing_pages, gaps）

2. **generate_gap_toc(pdf_path, gap_start, gap_end)**
   - 输入：PDF 路径，gap 范围
   - 输出：LLM 生成的 TOC 列表

3. **fill_gaps(tree, pdf_path, total_pages)**
   - 输入：原始 tree, PDF 路径，总页数
   - 输出：填充后的 tree + gap_info

### LLM Prompt 示例

```
Analyze the following content from pages 67 to 78 of a PDF document.

Generate a table of contents (TOC) for this section. For each entry:
1. Identify main topics, sections, or headings
2. Assign a page number where the topic appears
3. Create a hierarchical structure if subsections exist

Content:
=== Page 67 ===
[page content here]

=== Page 68 ===
[page content here]

...

Respond with a JSON array of TOC items. Each item should have:
- "title": The section/topic title
- "page": The page number where it appears (67 to 78)
- "level": Hierarchy level (1 for main topics, 2 for subtopics, etc.)
```

## 优势

1. **非侵入式**：不修改核心算法，保持稳定性
2. **智能化**：LLM 自动理解内容结构
3. **完整性**：确保 100% 页面覆盖
4. **可追溯**：补丁节点明确标记，便于区分
5. **灵活性**：可选择性地忽略补丁节点

## 使用场景

### 适用场景
- Embedded TOC 不完整的文档
- 只有部分章节有目录的文档
- 附录、参考文献未包含在目录中的文档

### 不适用场景
- 完整 TOC 已覆盖所有页面（Gap Filler 自动跳过）
- 极大的文档（>1000 页），gap 太大时会跳过

## 前端集成建议

### 显示补丁节点

可以在前端用不同样式展示补丁节点：

```typescript
const renderNode = (node) => {
  const className = node.is_gap_fill 
    ? 'node-gap-fill'  // 补丁节点（灰色/虚线）
    : 'node-regular';   // 常规节点
  
  return (
    <div className={className}>
      <NodeTitle>{node.title}</NodeTitle>
      {node.is_gap_fill && <Badge>补充</Badge>}
    </div>
  );
};
```

### 过滤选项

可以提供选项让用户选择是否显示补丁节点：

```typescript
const [showGapFill, setShowGapFill] = useState(true);

const filteredNodes = showGapFill 
  ? allNodes 
  : allNodes.filter(node => !node.is_gap_fill);
```

## 性能考虑

- **时间开销**：每个 gap 调用一次 LLM（~2-5 秒）
- **最坏情况**：多个小 gap → 多次 LLM 调用
- **优化**：合并相邻的小 gap，减少 LLM 调用次数

## 未来改进

1. **批量处理**：多个 gap 合并一次 LLM 调用
2. **缓存机制**：相同 PDF 的 gap 结果缓存
3. **增量更新**：只处理新增的 gap
4. **智能合并**：自动识别相关的 gap 范围

## 相关文件

- `pageindex_v2/utils/gap_filler.py` - 核心实现
- `pageindex_v2/main.py` - Phase 7 集成
- `test_gap_filler.py` - 测试工具
- `GAP_FILLER.md` - 本文档
