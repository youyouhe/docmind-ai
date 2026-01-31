# PDF解析算法调试日志使用指南

## 概述

我们为PDF解析算法添加了详细的调试日志功能,可以帮助诊断解析过程中的问题。日志会记录算法各个步骤的详细信息,包括TOC检测、结构提取、标题验证、树构建等。

## 已识别的主要问题

通过分析测试文件 `dbfb9808-761c-4dc9-9acd-cb87aa8f028f.pdf` 的解析结果,发现了以下问题:

### 1. 内容重复问题 ⚠️
**症状**: 多个不同的节点包含相同的内容(都是耳机话筒组的技术规格)
- 例如: 节点 0006, 0007, 0008, 0009, 0010, 0012-0023 等都有相同或类似的内容
- **原因**: 内容分配算法可能将所有节点都指向了文档的最后几页

### 2. 页码范围异常 ⚠️
**症状**: 很多节点的 page_start 和 page_end 都是 9(最后一页)
- **影响**: 导致内容分配错误,所有节点都拿到了相同的页面内容
- **原因**: 页码检测算法 `check_title_appearance_in_start` 可能没有正确找到标题的实际位置

### 3. 层级结构混乱 ⚠️
**症状**: 
- 父节点(如"项目概况与招标范围") content为空
- 子节点却包含重复的无关内容
- **原因**: 树构建算法在分配内容时出现逻辑错误

### 4. 标题提取不当 ⚠️
**症状**: 部分标题过长,应该是从内容中错误提取的
- 例如: "采购内容：语言学习系统控制软件等，详见公告附件。" 这是内容而不是标题
- **原因**: 结构提取算法将详细描述误判为章节标题

## 日志功能说明

### 自动生成的日志文件

当运行PDF解析时,会在 `lib/docmind-ai/debug_logs/` 目录下生成两个文件:

1. **文本日志**: `{document_id}_debug_{timestamp}.log`
   - 人类可读的详细日志
   - 包含每个处理步骤的信息
   - 记录发现的问题和警告

2. **JSON日志**: `{document_id}_debug_{timestamp}.json`
   - 结构化的机器可读日志
   - 包含所有中间数据
   - 便于程序化分析

### 日志记录的阶段

日志会记录以下处理阶段:

1. **initialization** - 初始化
   - 文档基本信息(页数、token数)

2. **toc_detection** - TOC检测
   - 是否检测到目录
   - 目录所在页码
   - 是否包含页码引用

3. **structure_extraction** - 结构提取
   - 提取的结构项数量
   - 每个结构项的详细信息
   - 结构层级分布

4. **title_validation** - 标题验证
   - 验证了多少标题
   - 多少标题被确认
   - 哪些标题验证失败

5. **tree_building** - 树构建
   - 创建的节点数量
   - 树的深度
   - **内容分配问题检测** ⚠️
   - 每个节点的页码范围

### 问题检测

日志会自动检测并报告以下问题:

- ⚠️ 节点被分配到最后一页(可能的内容分配错误)
- ⚠️ 无效的页码范围(start > end)
- ⚠️ 内容重复(多个节点指向相同页面)
- ⚠️ 标题验证失败率过高

## 使用方法

### 1. 运行解析并生成日志

日志功能已自动集成到解析流程中,无需额外配置:

```python
from pageindex.page_index import page_index_main
from pageindex.utils import Options

# 正常调用,会自动生成日志
opt = Options()
result = page_index_main("path/to/your.pdf", opt=opt)
```

### 2. 查看日志

解析完成后,检查控制台输出:

```
[DEBUG] Log saved to: D:\BidSmart-Index\lib\docmind-ai\debug_logs\abc12345_debug_20260131_143022.log
[DEBUG] JSON log saved to: D:\BidSmart-Index\lib\docmind-ai\debug_logs\abc12345_debug_20260131_143022.json
```

### 3. 分析日志

#### 查看文本日志
```bash
# 打开文本日志文件
notepad debug_logs/{document_id}_debug_{timestamp}.log
```

关键信息查找:
- 搜索 `⚠️ ISSUE` 找到所有检测到的问题
- 搜索 `Content Assignment Issues` 找到内容分配问题
- 查看 `Node details` 部分了解每个节点的页码范围

#### 分析JSON日志
```python
import json

# 加载JSON日志
with open('debug_logs/xxx_debug_xxx.json', 'r', encoding='utf-8') as f:
    log_data = json.load(f)

# 查看结构提取结果
structure_info = log_data['stages']['structure_extraction'][0]
print(f"提取了 {structure_info['data']['total_items']} 个结构项")
print(f"有页码的: {structure_info['data']['items_with_page']}")
print(f"无页码的: {structure_info['data']['items_without_page']}")

# 查看标题验证结果
validation_info = log_data['stages']['title_validation'][0]
print(f"验证成功率: {validation_info['data']['confirmation_rate']}")

# 查看树构建问题
tree_info = log_data['stages']['tree_building'][0]
if tree_info['data']['content_issues_count'] > 0:
    print(f"⚠️ 发现 {tree_info['data']['content_issues_count']} 个内容分配问题")
```

## 下一步诊断建议

基于当前测试文件的问题,建议按以下顺序调查:

### 1. 检查页码检测算法
**文件**: `pageindex/page_index.py`
**函数**: `check_title_appearance_in_start_concurrent`

查看日志中的 `title_validation` 部分:
- 有多少标题验证失败?
- 失败的标题有什么共同特征?

### 2. 检查内容分配逻辑
**文件**: `pageindex/utils.py`
**函数**: `post_processing`

查看日志中的 `tree_building` 部分:
- 节点的 start_index 和 end_index 是否合理?
- 是否有很多节点都指向相同的页码?

### 3. 检查结构提取
**文件**: `pageindex/page_index.py`
**函数**: `generate_toc_continue`, `generate_toc_init`

查看日志中的 `structure_extraction` 部分:
- 提取的标题是否合理?
- 是否有过长的标题?
- physical_index 是否正确?

## 日志样例

### 正常的日志输出
```
[0.52s] TOC_DETECTION
--------------------------------------------------------------------------------
No TOC detected - will auto-generate structure

Data:
  total_pages: 9
  has_toc: False

[2.15s] STRUCTURE_EXTRACTION
--------------------------------------------------------------------------------
Extracted 34 structure items using mode: process_no_toc

Data:
  total_items: 34
  items_with_page: 28
  items_without_page: 6

[3.87s] TITLE_VALIDATION
--------------------------------------------------------------------------------
Title validation: 23/28 titles confirmed (82.1%)

[4.21s] TREE_BUILDING
--------------------------------------------------------------------------------
Tree built: 34 nodes, depth 3

⚠️  Content Assignment Issues (15):
  - '投标人资格要求' assigned to last page only
  - '报名方式' assigned to last page only
  ...
```

### 问题指标
- **确认率 < 70%**: 标题检测有严重问题
- **content_issues_count > 5**: 内容分配有严重问题
- **很多节点的页码都是最后一页**: 页码检测算法失败

## 常见问题诊断

### Q: 为什么很多节点都有相同的内容?
**A**: 检查 `tree_building` 日志,看节点的页码范围。如果很多节点都指向最后几页,说明页码检测失败。

### Q: 为什么标题验证失败率很高?
**A**: 可能原因:
1. LLM提取的标题与实际页面中的标题格式不匹配
2. physical_index 不准确
3. 模糊匹配阈值设置不当

### Q: 如何修复内容重复问题?
**A**: 
1. 先修复页码检测(`check_title_appearance_in_start`)
2. 确保每个标题都能正确匹配到其出现的页面
3. 检查树构建时的内容分配逻辑(`post_processing`)

## 总结

调试日志系统可以帮助你:
1. ✅ 快速定位算法问题
2. ✅ 了解每个处理步骤的详细信息
3. ✅ 发现内容分配、页码检测等常见错误
4. ✅ 优化算法性能

遇到问题时,先查看日志中的 `⚠️ ISSUE` 标记,这些通常是最需要关注的问题点。
