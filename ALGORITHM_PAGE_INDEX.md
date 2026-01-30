# 页码索引算法说明文档

## 1. 核心概念

### 1.1 索引系统

- **索引系统**：1-based（页码从1开始）
- **physical_index**：LLM提取的章节起始页码，格式如 `<physical_index_3>` 表示第3页
- **start_index**：章节的起始页码（1-based）
- **end_index**：章节的结束页码（1-based）

### 1.2 数据结构

```python
# 扁平化TOC结构（LLM输出）
{
    "structure": "1.2",        # 层级编号
    "title": "章节标题",
    "physical_index": 3        # 起始页码
}

# 树形结构（最终输出）
{
    "title": "章节标题",
    "start_index": 3,          # 起始页
    "end_index": 5,            # 结束页
    "nodes": [...]             # 子章节
}
```

## 2. start_index 计算规则

### 规则

```
start_index = physical_index（来自LLM提取）
```

### 边界情况处理

| 情况 | 处理方式 |
|------|----------|
| physical_index 为 None | 使用前一项的 end_index + 1，首项则用 1 |
| physical_index < 1 | 修正为 1 |
| physical_index > 文档总页数 | 修正为文档总页数 |

### 代码逻辑

```python
start_idx = item.get('physical_index')

if start_idx is None or not isinstance(start_idx, int) or start_idx < 1:
    if i > 0:
        prev_end = structure[i - 1].get('end_index', end_physical_index)
        start_idx = min(prev_end + 1, end_physical_index)
    else:
        start_idx = 1

start_idx = min(start_idx, end_physical_index)
item['start_index'] = start_idx
```

## 3. end_index 计算规则

### 核心规则

```
end_index = 下一兄弟章节的 start_index（或 start_index - 1）
```

### 详细规则

| 情况 | 计算方式 | 说明 |
|------|----------|------|
| 有下一章 | 下一章的 start_index | 下一章从新页面开始 |
| 有下一章，且下一章从页面中间开始 | 下一章的 start_index - 1 | 当前章在下一章开始前结束 |
| 最后一章 | 文档总页数 | 延伸到文档末尾 |
| 多章节同页起始 | 均为该页码 | start_index == end_index |

### appear_start 字段

- `appear_start = 'yes'`：下一章从页面中间开始（非页首）
- `appear_start = 'no'` 或不存在：下一章从页面开始

### 代码逻辑

```python
if i < len(structure) - 1:
    next_item = structure[i + 1]
    next_start_idx = next_item.get('physical_index')

    if next_start_idx is not None and isinstance(next_start_idx, int):
        if next_item.get('appear_start') == 'yes':
            end_idx = next_start_idx - 1
        else:
            end_idx = next_start_idx
        end_idx = max(end_idx, start_idx)  # 确保不小于start_index
        item['end_index'] = min(end_idx, end_physical_index)
    else:
        item['end_index'] = max(start_idx, end_physical_index)
else:
    item['end_index'] = max(start_idx, end_physical_index)
```

## 4. 父子节点页码关系规则

### 核心原则

**父节点的页码范围必须覆盖所有子节点的页码范围**

### 计算顺序

1. 先为每个节点独立计算 start_index 和 end_index（基于兄弟章节关系）
2. 构建树形结构后，根据子节点调整父节点范围

### 调整规则

```
父节点.start_index = min(父节点.start_index, 所有子节点.start_index的最小值)
父节点.end_index = max(父节点.end_index, 所有子节点.end_index的最大值)
```

### 代码逻辑

```python
def clean_node(node, parent_start=None, parent_end=None):
    # 先递归处理子节点
    if node['nodes']:
        for child in node['nodes']:
            clean_node(child, node['start_index'], node['end_index'])

        # 根据子节点调整当前节点范围
        child_min_start = min(child['start_index'] for child in node['nodes'])
        child_max_end = max(child['end_index'] for child in node['nodes'])

        node['start_index'] = min(node['start_index'], child_min_start)
        node['end_index'] = max(node['end_index'], child_max_end)

    # 子节点保持其计算范围，不强制限制在父节点范围内
    # 父节点会扩展以覆盖子节点的范围
    if parent_start is not None and parent_end is not None:
        # 仅记录日志，不进行clamping
        # 父节点将在其自身的扩展步骤中覆盖子节点的范围
        if node['start_index'] < parent_start or node['end_index'] > parent_end:
            logger.info(f"Child range [{node['start_index']},{node['end_index']}] exceeds parent's original range [{parent_start},{parent_end}]")
            logger.info(f"Parent will expand to cover this range (Option A)")

    return node
```

## 5. 示例

### 示例1：基础情况

```
文档总页数：10页

章节           physical_index    start_index    end_index    说明
1. 第一章      1                 1             3           第1章从页1开始，第2章从页4开始
  1.1 小节A    1                 1             1
  1.2 小节B    2                 2             2
  1.3 小节C    3                 3             3
2. 第二章      4                 4             7
  2.1 小节D    4                 4             5
  2.2 小节E    6                 6             7
3. 第三章      8                 8             10          最后一章
```

### 示例2：多章节同页

```
章节           physical_index    start_index    end_index    说明
1. 概述        1                 1             1           短章节，只占第1页
2. 需求        1                 1             3           同页起始，但内容延续到第3页
  2.1 功能需求  1                 1             2
  2.2 性能需求  3                 3             3
3. 设计        4                 4             5
```

### 示例3：父子节点范围调整

```
# 原始计算（基于兄弟关系）
章节              start_index    end_index
第一章            1              2           ← 基于下一章从页3开始
  1.1 概述        1              1
  1.2 详细说明    1              3           ← 内容实际延续到页3

# 调整后（父节点覆盖子节点）
章节              start_index    end_index
第一章            1              3           ← 扩展以覆盖子节点
  1.1 概述        1              1
  1.2 详细说明    1              3
```

## 6. 边界情况处理

### 情况1：LLM未识别页码

```python
# physical_index 为 None 的处理
if physical_index is None:
    # 使用前一项的结束页 + 1
    start_idx = prev_end + 1 if i > 0 else 1
```

### 情况2：页码超出文档范围

```python
# physical_index > 总页数
if physical_index > end_physical_index:
    start_idx = end_physical_index
```

### 情况3：子节点页码超出父节点原始范围

**处理方式（Option A：父节点对齐子节点）**

```python
# 子节点保持其计算范围，不进行clamping
# 父节点扩展以覆盖子节点的完整范围
parent_start = min(parent_start, child_start)
parent_end = max(parent_end, child_end)
```

**说明**：
- 子节点保留其基于兄弟关系计算的页码范围
- 父节点扩展其范围以覆盖所有子节点的范围
- 这确保了子节点的内容不会丢失

## 7. API输出格式转换

### PageIndex 内部格式

```python
{
    "start_index": 1,  # 1-based
    "end_index": 3
}
```

### API 输出格式

```python
{
    "page_start": 1,   # 1-based，无需转换
    "page_end": 3
}
```

**注意**：PageIndex 内部已使用 1-based 索引，API 输出时**不需要**再 +1。

## 8. 验证规则

### 必须满足的条件

1. `1 <= start_index <= end_index <= 文档总页数`
2. 对于任何父节点：`父节点.start_index <= 所有子节点.start_index`
3. 对于任何父节点：`父节点.end_index >= 所有子节点.end_index`
4. 兄弟节点的页码范围不应重叠（除了同页起始的情况）

### 调试验证代码

```python
def validate_tree(tree, total_pages):
    errors = []

    def check_node(node, parent_range=None):
        # 验证基本范围
        if node['start_index'] < 1 or node['start_index'] > total_pages:
            errors.append(f"{node['title']}: start_index 超出范围")
        if node['end_index'] < node['start_index'] or node['end_index'] > total_pages:
            errors.append(f"{node['title']}: end_index 超出范围")

        # 验证父子关系
        if parent_range:
            p_start, p_end = parent_range
            if node['start_index'] < p_start or node['end_index'] > p_end:
                errors.append(f"{node['title']}: 超出父节点范围 {p_start}-{p_end}")

        # 递归检查子节点
        if 'nodes' in node and node['nodes']:
            child_range = (
                min(child['start_index'] for child in node['nodes']),
                max(child['end_index'] for child in node['nodes'])
            )
            if node['start_index'] > child_range[0] or node['end_index'] < child_range[1]:
                errors.append(f"{node['title']}: 未覆盖子节点范围 {child_range}")

            for child in node['nodes']:
                check_node(child, (node['start_index'], node['end_index']))

    check_node(tree)
    return errors
```

## 9. 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| 1.1 | 2025-01-30 | 修正父子节点页码关系：实现Option A（父节点对齐子节点），移除子节点clamping逻辑，防止数据丢失 |
| 1.0 | 2025-01-30 | 初始版本，定义基础算法规则 |
