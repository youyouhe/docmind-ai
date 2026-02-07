# 对话信息增强功能

## 概述

本次更新增强了对话历史记录功能，在保存对话时收集并存储以下额外信息：
1. **系统提示词（system_prompt）**：完整的系统提示词，包括上下文和历史对话
2. **模型原始输出（raw_output）**：大模型的原始输出内容（截断至500字符）

## 主要更改

### 1. 数据库表结构更新

在 `conversations` 表中新增两个字段：

```sql
-- 系统提示词（完整）
system_prompt TEXT NULL

-- 模型原始输出（截断至500字符）
raw_output TEXT NULL
```

### 2. 后端API更新

#### 文件：`lib/docmind-ai/api/database.py`
- 更新了 `Conversation` 模型，添加了 `system_prompt` 和 `raw_output` 字段
- 更新了 `save_conversation_message()` 方法，支持保存新字段
- 实现了自动截断功能，将 `raw_output` 限制在500字符以内
- 更新了 `get_conversation_history()` 方法，返回新字段

#### 文件：`lib/docmind-ai/api/document_routes.py`
- 更新了 `ConversationMessage` Pydantic模型，添加新字段
- 更新了 `SaveConversationRequest` 模型，接受新字段
- 更新了 `save_conversation_message` API端点，传递新字段到数据库

#### 文件：`lib/docmind-ai/api/services.py`
- 更新了 `chat_with_document()` 方法，在返回结果中包含 `system_prompt` 和 `raw_output`

### 3. 前端更新

#### 文件：`types.ts`
- 更新了 `ChatResponse` 接口，添加 `system_prompt` 和 `raw_output` 字段

#### 文件：`services/apiService.ts`
- 更新了 `saveConversationMessage()` 函数签名，支持传递新参数

#### 文件：`App.tsx`
- 更新了保存AI消息的代码，传递 `system_prompt` 和 `raw_output`

## 数据库迁移

### 运行迁移脚本

对于现有数据库，需要运行迁移脚本来添加新字段：

```bash
cd lib/docmind-ai
python migrate_conversation_fields.py
```

迁移脚本会：
1. 检查数据库是否存在
2. 检查新字段是否已存在
3. 如果需要，添加 `system_prompt` 和 `raw_output` 字段
4. 验证迁移成功

### 新数据库

对于新创建的数据库，表结构会自动包含这些字段，无需运行迁移脚本。

## 测试

### 运行测试脚本

```bash
cd lib/docmind-ai
python test_conversation_fields.py
```

测试脚本会：
1. 创建一个测试文档
2. 保存一条包含系统提示词和原始输出的对话消息
3. 验证字段正确保存
4. 验证 `raw_output` 被正确截断到500字符
5. 清理测试数据

## 使用示例

### 后端保存对话

```python
db.save_conversation_message(
    message_id=message_id,
    document_id=document_id,
    role='assistant',
    content="这是回答内容",
    sources=[{"id": "ch-1", "title": "章节1"}],
    debug_path=["ch-1"],
    system_prompt="你是一个助手...",  # 完整的系统提示词
    raw_output="这是模型的原始输出..."  # 会自动截断到500字符
)
```

### 前端保存对话

```typescript
await saveConversationMessage(
  documentId,
  'assistant',
  response.answer,
  response.sources,
  response.debug_path,
  response.system_prompt,  // 系统提示词
  response.raw_output      // 原始输出（会被后端截断）
);
```

## 数据格式

### 系统提示词示例

```
You are a helpful assistant that answers questions based on the provided document content. The user may ask follow-up questions that reference previous parts of the conversation.

Conversation History:
User: 质保期是多久？
Assistant: 根据文档内容，质保期为12个月。

Current User Question: 从什么时候开始计算？

Relevant Document Content:
质保期为12个月，从交付之日起计算。

Instructions:
1. Answer the question using ONLY the provided document content
2. Consider the conversation history for context and pronoun references
3. If the answer cannot be found in the content, say so clearly
4. Be concise but thorough

Answer:
```

### 原始输出示例（截断到500字符）

```
根据文档内容，质保期从交付之日起计算。这意味着从您收到产品的那一天开始，12个月内出现的任何质量问题都在保修范围内。需要注意的是，这里的"交付之日"是指实际收货日期，而不是下单日期。[截断...]
```

## 注意事项

1. **向后兼容性**：新字段为可选（nullable），不会影响现有功能
2. **自动截断**：`raw_output` 在保存到数据库前会自动截断到500字符
3. **系统提示词完整性**：`system_prompt` 不会被截断，会完整保存
4. **性能影响**：新增字段对查询性能影响极小
5. **存储空间**：每条对话消息会额外占用存储空间（平均 1-2 KB）

## 未来改进

可能的扩展方向：
1. 添加模型参数记录（temperature, max_tokens等）
2. 记录响应时间和token使用量
3. 支持导出对话数据用于分析
4. 添加对话质量评分功能
