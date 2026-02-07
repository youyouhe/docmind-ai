# EXPAND Action Design - 页码跨度过大的智能处理方案

## 问题描述

### 当前问题
当前的 `MODIFY_PAGE` 操作只是简单修改页码范围，但这存在严重问题：

**场景示例：**
```json
{
  "id": "第二章",
  "title": "第二章 技术方案",
  "page_start": 5,
  "page_end": 50,  // 跨度 45 页，明显过大
  "children": []   // 没有子节点
}
```

**当前处理（MODIFY_PAGE）：**
- LLM 建议：将页码改为 `[5, 15]`
- 结果：第 16-50 页的内容**丢失**了！
- 根本原因：这个章节应该有更细的子结构，但初始解析时颗粒度不够

---

## 解决方案：引入 EXPAND 动作

### 概念定义

**EXPAND (扩展分析)**：对页码跨度过大的节点进行重新分析，生成更细粒度的子结构。

### 与现有动作的区别

| 动作类型 | 目的 | 是否改变结构 | 数据来源 |
|---------|------|------------|---------|
| `DELETE` | 删除错误节点 | 是（减少节点） | 无 |
| `ADD` | 添加缺失节点 | 是（增加节点） | LLM 推理 |
| `MODIFY_FORMAT` | 修正编号格式 | 否 | LLM 推理 |
| `MODIFY_PAGE` | 修正页码错误 | 否 | LLM 推理 |
| **`EXPAND`** ⭐ | 细化粗糙结构 | 是（增加子节点） | **PDF 重新解析** |

---

## 设计方案

### 1. 检测触发条件

在审计阶段，LLM 检测以下情况应生成 `EXPAND` 建议：

```python
def should_expand(node: dict) -> bool:
    """判断节点是否需要扩展分析"""
    page_span = node["page_end"] - node["page_start"] + 1
    has_children = len(node.get("children", [])) > 0
    
    # 触发条件：
    # 1. 页码跨度 > 15 页
    # 2. 没有子节点或子节点很少
    # 3. 节点层级 <= 2（顶层章节）
    
    if page_span > 15 and not has_children:
        return True, "页码跨度过大且无子结构"
    
    if page_span > 25 and len(node.get("children", [])) < 3:
        return True, "页码跨度过大但子结构过于粗糙"
    
    return False, ""
```

### 2. LLM 生成建议

**Prompt 示例：**
```
检测到节点 "第二章 技术方案" 页码跨度为 45 页（5-50），但没有子节点。
这表明初始解析的颗粒度不够细。

建议执行 EXPAND 操作：
- 重新分析 PDF 第 5-50 页
- 识别该章节内的所有二级、三级标题
- 生成细粒度的树状结构
```

**LLM 输出：**
```json
{
  "action": "EXPAND",
  "node_id": "第二章",
  "reason": "页码跨度 45 页过大，需要提取更细粒度的子结构",
  "confidence": "high",
  "expand_params": {
    "page_range": [5, 50],
    "target_depth": 3,  // 期望解析到第3级标题
    "expected_children_count": "5-10"  // 预期子节点数量
  }
}
```

### 3. 执行 EXPAND 操作

#### 步骤 A：提取 PDF 页面内容
```python
def extract_page_content(pdf_path: str, start_page: int, end_page: int) -> str:
    """提取指定页面范围的 PDF 内容"""
    import pymupdf  # PyMuPDF
    
    doc = pymupdf.open(pdf_path)
    content = []
    
    for page_num in range(start_page - 1, end_page):
        page = doc[page_num]
        content.append(page.get_text())
    
    return "\n\n".join(content)
```

#### 步骤 B：使用 LLM 重新分析结构
```python
async def re_analyze_structure(
    content: str, 
    parent_title: str,
    page_range: List[int]
) -> List[Dict]:
    """
    使用 LLM 重新分析内容，生成细粒度结构
    """
    prompt = f"""
你是一个文档结构分析专家。现在需要分析以下内容（来自 "{parent_title}"，页码 {page_range[0]}-{page_range[1]}）：

{content[:5000]}  // 限制长度，避免超过 token 限制

请识别所有章节标题，包括：
- 二级标题（如 "2.1 总体架构"）
- 三级标题（如 "2.1.1 技术选型"）
- 四级标题（如有）

对于每个标题，提供：
1. 标题文本
2. 层级（level）
3. 页码范围（估算）

输出 JSON 格式：
{{
  "children": [
    {{
      "title": "2.1 总体架构",
      "level": 2,
      "page_start": 5,
      "page_end": 10
    }},
    ...
  ]
}}
"""
    
    response = await llm.generate(prompt, response_format="json")
    return json.loads(response)["children"]
```

#### 步骤 C：插入新的子结构
```python
def apply_expand(tree: Dict, suggestion: Dict, new_children: List[Dict]) -> bool:
    """将重新分析的子结构插入树中"""
    node = find_node(tree, suggestion["node_id"])
    
    if not node:
        return False
    
    # 清空旧的子节点（如果有）
    node["children"] = []
    
    # 插入新的细粒度子结构
    for child_data in new_children:
        child_node = {
            "id": generate_node_id(),
            "title": child_data["title"],
            "page_start": child_data["page_start"],
            "page_end": child_data["page_end"],
            "children": []
        }
        node["children"].append(child_node)
    
    return True
```

---

## 完整流程示例

### 输入（初始树结构）
```json
{
  "id": "第二章",
  "title": "第二章 技术方案",
  "page_start": 5,
  "page_end": 50,
  "children": []
}
```

### 审计建议
```json
{
  "action": "EXPAND",
  "node_id": "第二章",
  "reason": "页码跨度 45 页，需要重新分析以生成细粒度结构",
  "confidence": "high",
  "expand_params": {
    "page_range": [5, 50],
    "target_depth": 3
  }
}
```

### 执行结果（扩展后的树结构）
```json
{
  "id": "第二章",
  "title": "第二章 技术方案",
  "page_start": 5,
  "page_end": 50,
  "children": [
    {
      "id": "2.1",
      "title": "2.1 总体架构",
      "page_start": 5,
      "page_end": 10,
      "children": [
        {
          "id": "2.1.1",
          "title": "2.1.1 技术选型",
          "page_start": 5,
          "page_end": 7
        },
        {
          "id": "2.1.2",
          "title": "2.1.2 架构设计",
          "page_start": 8,
          "page_end": 10
        }
      ]
    },
    {
      "id": "2.2",
      "title": "2.2 核心模块设计",
      "page_start": 11,
      "page_end": 25,
      "children": [
        {
          "id": "2.2.1",
          "title": "2.2.1 数据层",
          "page_start": 11,
          "page_end": 15
        },
        {
          "id": "2.2.2",
          "title": "2.2.2 业务层",
          "page_start": 16,
          "page_end": 20
        },
        {
          "id": "2.2.3",
          "title": "2.2.3 表现层",
          "page_start": 21,
          "page_end": 25
        }
      ]
    },
    {
      "id": "2.3",
      "title": "2.3 接口设计",
      "page_start": 26,
      "page_end": 35
    },
    {
      "id": "2.4",
      "title": "2.4 安全机制",
      "page_start": 36,
      "page_end": 50
    }
  ]
}
```

---

## 实现步骤

### Phase 1: 修改 TreeAuditorV2 生成 EXPAND 建议

**文件**: `lib/docmind-ai/pageindex_v2/phases/tree_auditor_v2.py`

```python
# 在审计阶段检测需要扩展的节点
def detect_expand_candidates(tree: Dict) -> List[Dict]:
    """检测需要扩展分析的节点"""
    candidates = []
    
    def traverse(node, level=0):
        page_span = node.get("page_end", 0) - node.get("page_start", 0) + 1
        children_count = len(node.get("children", []))
        
        # 触发条件
        if level <= 2 and page_span > 15 and children_count == 0:
            candidates.append({
                "action": "EXPAND",
                "node_id": node["id"],
                "reason": f"页码跨度 {page_span} 页，但无子结构，建议重新分析",
                "confidence": "high",
                "expand_params": {
                    "page_range": [node["page_start"], node["page_end"]],
                    "target_depth": min(level + 2, 4)
                }
            })
        
        for child in node.get("children", []):
            traverse(child, level + 1)
    
    traverse(tree)
    return candidates
```

### Phase 2: 创建 ExpandExecutor

**新文件**: `lib/docmind-ai/pageindex_v2/phases/expand_executor.py`

```python
class ExpandExecutor:
    """执行 EXPAND 操作的执行器"""
    
    def __init__(self, llm: LLMClient, pdf_path: str):
        self.llm = llm
        self.pdf_path = pdf_path
    
    async def execute_expand(
        self, 
        tree: Dict, 
        suggestion: Dict
    ) -> bool:
        """
        执行 EXPAND 操作
        
        1. 提取 PDF 页面内容
        2. 使用 LLM 重新分析结构
        3. 插入新的子节点
        """
        node = self._find_node(tree, suggestion["node_id"])
        if not node:
            return False
        
        # 步骤 1: 提取内容
        page_range = suggestion["expand_params"]["page_range"]
        content = self._extract_pdf_content(page_range[0], page_range[1])
        
        # 步骤 2: 重新分析
        new_children = await self._re_analyze_structure(
            content=content,
            parent_title=node["title"],
            page_range=page_range,
            target_depth=suggestion["expand_params"]["target_depth"]
        )
        
        # 步骤 3: 插入子节点
        node["children"] = new_children
        
        return True
    
    def _extract_pdf_content(self, start_page: int, end_page: int) -> str:
        """提取 PDF 页面内容"""
        # 实现 PDF 提取逻辑
        pass
    
    async def _re_analyze_structure(
        self,
        content: str,
        parent_title: str,
        page_range: List[int],
        target_depth: int
    ) -> List[Dict]:
        """使用 LLM 重新分析结构"""
        # 实现 LLM 分析逻辑
        pass
```

### Phase 3: 集成到 API

**文件**: `lib/docmind-ai/api/audit_routes.py`

```python
# 在应用建议时处理 EXPAND 操作
elif suggestion.action == "EXPAND":
    # 执行扩展分析
    expand_executor = ExpandExecutor(llm, pdf_path)
    if await expand_executor.execute_expand(tree_data, suggestion.to_dict()):
        applied_count += 1
    else:
        warnings.append(f"无法扩展节点 {suggestion.node_id}")
```

---

## 优势分析

### 与 MODIFY_PAGE 对比

| 方面 | MODIFY_PAGE（当前） | EXPAND（新方案） |
|-----|-------------------|-----------------|
| **处理方式** | 修改页码范围 | 重新分析生成子结构 |
| **数据完整性** | ❌ 可能丢失内容 | ✅ 保留所有内容 |
| **结构精细度** | ❌ 保持粗糙 | ✅ 生成细粒度结构 |
| **用户体验** | ⚠️ 需要手动补充 | ✅ 自动完善 |
| **执行复杂度** | 低（只改属性） | 高（需调用 LLM） |

### 实际场景对比

**场景：**投标文档的"第二章 技术方案"跨度 45 页

**MODIFY_PAGE 结果：**
```
第二章 [5-15]  ← 其他 35 页内容丢失！
```

**EXPAND 结果：**
```
第二章 [5-50]
├── 2.1 总体架构 [5-10]
├── 2.2 核心模块 [11-25]
│   ├── 2.2.1 数据层 [11-15]
│   ├── 2.2.2 业务层 [16-20]
│   └── 2.2.3 表现层 [21-25]
├── 2.3 接口设计 [26-35]
└── 2.4 安全机制 [36-50]
```

---

## 潜在挑战与解决方案

### 挑战 1: LLM Token 限制
**问题**: 45 页内容可能超过 LLM 上下文限制

**解决方案**:
- 分段处理：每次分析 10-15 页
- 使用长上下文模型（如 GPT-4-32k, Claude-100k）
- 只提取标题和段落首句，不传递全文

### 挑战 2: PDF 提取质量
**问题**: 扫描 PDF 或复杂排版可能提取不准

**解决方案**:
- 使用 OCR（如 Tesseract、PaddleOCR）
- 结合 PyMuPDF 的表格、图像识别
- 提供"人工辅助"选项，让用户确认结构

### 挑战 3: 页码估算准确性
**问题**: LLM 重新分析时页码可能不准确

**解决方案**:
- 使用 PDF 的页面定位信息（坐标、字体大小）
- 交叉验证：检查子节点页码是否覆盖父节点范围
- 允许用户手动调整

### 挑战 4: 性能问题
**问题**: EXPAND 操作需要调用 LLM，耗时较长

**解决方案**:
- 异步执行，显示进度条
- 批量处理：一次性扩展多个节点
- 缓存机制：相似结构不重复分析

---

## 渐进式实现计划

### Phase 1: MVP（最小可行产品）
- [ ] 检测页码跨度过大的节点
- [ ] 生成 EXPAND 建议
- [ ] 简单的 PDF 内容提取
- [ ] 基础的 LLM 结构重分析
- [ ] 插入新子节点

### Phase 2: 增强功能
- [ ] 支持多层级扩展（递归）
- [ ] 页码验证与修正
- [ ] 进度追踪与取消
- [ ] 失败重试机制

### Phase 3: 高级特性
- [ ] 智能分段（避免 token 限制）
- [ ] OCR 集成
- [ ] 人工辅助确认
- [ ] 性能优化与缓存

---

## 总结

**核心洞察**: 页码跨度过大的根本原因是**解析颗粒度不足**，而不是页码错误。

**解决方案**: 引入 `EXPAND` 动作，通过重新分析 PDF 内容来生成更细粒度的树状结构。

**优势**:
- ✅ 数据完整性：不丢失任何内容
- ✅ 结构精细度：自动生成多层级结构
- ✅ 用户体验：减少手动修正工作
- ✅ 智能化：利用 LLM 理解文档语义

**挑战**:
- 实现复杂度较高
- 需要处理 PDF 提取和 LLM token 限制
- 性能优化需要考虑

这是一个更加智能和彻底的解决方案！🚀
