"""
树结构智能审核建议系统
Tree Structure Audit Advisor

基于文档类型和LLM知识，提供结构化的审核建议
"""

import json
from typing import Dict, List, Any, Optional
from ..core.llm_client import LLMClient


class TreeAuditAdvisor:
    """
    树结构审核顾问
    
    根据文档类型提供审核建议：
    1. DELETE - 删除标题（误识别的内容）
    2. MODIFY_FORMAT - 修改标题格式/编号
    3. MODIFY_PAGE - 修正页码范围
    4. ADD - 添加缺失的标题
    5. KEEP - 保持不变
    
    注意：标题的文本内容不能修改，只能调整格式/编号/页码
    """
    
    def __init__(self, llm: LLMClient, debug: bool = False):
        self.llm = llm
        self.debug = debug
    
    async def generate_audit_advice(
        self,
        tree: Dict[str, Any],
        document_type: str,
        doc_classification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成审核建议
        
        Args:
            tree: 文档树结构
            document_type: 文档类型 (tender/academic/technical等)
            doc_classification: 文档分类详细信息
        
        Returns:
            {
                "advice": [
                    {
                        "action": "DELETE",
                        "node_id": "0005",
                        "reason": "这是正文内容，不是标题",
                        "confidence": "high"
                    },
                    {
                        "action": "MODIFY_FORMAT",
                        "node_id": "0003",
                        "current_title": "1.1 背景",
                        "suggested_format": "（一）背景",
                        "reason": "标题编号格式不符合招标文件规范",
                        "confidence": "medium"
                    },
                    {
                        "action": "MODIFY_PAGE",
                        "node_id": "0008",
                        "current_pages": [10, 15],
                        "suggested_pages": [10, 12],
                        "reason": "页码范围包含了下一节的内容",
                        "confidence": "medium"
                    },
                    {
                        "action": "ADD",
                        "parent_id": "0001",
                        "suggested_title": "二、评标办法",
                        "suggested_level": 2,
                        "suggested_pages": [15, 20],
                        "reason": "目录中提到但未提取到此节",
                        "confidence": "low"
                    }
                ],
                "summary": {
                    "total_nodes": 25,
                    "to_delete": 5,
                    "to_modify_format": 3,
                    "to_modify_page": 2,
                    "to_add": 1,
                    "to_keep": 14
                }
            }
        """
        if self.debug:
            print("\n" + "="*60)
            print("[ADVISOR] Generating Audit Advice")
            print(f"[ADVISOR] Document Type: {document_type}")
            print("="*60)
        
        # 提取树结构
        structure = tree.get("children", tree.get("structure", []))
        
        if not structure:
            return {"advice": [], "summary": {}}
        
        # 扁平化节点（便于LLM处理）
        flat_nodes = self._flatten_tree(structure, max_depth=3, max_nodes=50)
        
        if self.debug:
            print(f"[ADVISOR] Extracted {len(flat_nodes)} nodes for review")
        
        # 生成提示词
        prompt = self._build_prompt(flat_nodes, document_type, doc_classification)
        
        # 调用LLM获取建议
        try:
            response = await self.llm.chat_json(
                prompt,
                temperature=0.2,
                max_retries=3
            )
            
            advice_list = response.get("advice", [])
            
            if self.debug:
                print(f"[ADVISOR] Received {len(advice_list)} pieces of advice")
                summary = self._summarize_advice(advice_list, len(flat_nodes))
                print(f"[ADVISOR] Summary: {summary}")
            
            return {
                "advice": advice_list,
                "summary": self._summarize_advice(advice_list, len(flat_nodes))
            }
            
        except Exception as e:
            if self.debug:
                print(f"[ADVISOR] ❌ Failed to generate advice: {e}")
            return {"advice": [], "summary": {}, "error": str(e)}
    
    def _flatten_tree(
        self,
        structure: List[Dict],
        max_depth: int = 3,
        max_nodes: int = 50
    ) -> List[Dict]:
        """扁平化树结构"""
        flat_nodes = []
        
        def traverse(node, level=1, parent_id=None):
            if len(flat_nodes) >= max_nodes or level > max_depth:
                return
            
            node_id = node.get("id", node.get("node_id", f"node_{len(flat_nodes)}"))
            
            flat_nodes.append({
                "id": node_id,
                "title": node.get("title", ""),
                "level": level,
                "parent_id": parent_id,
                "page_start": node.get("page_start", node.get("start_index")),
                "page_end": node.get("page_end", node.get("end_index")),
                "has_children": bool(node.get("children", node.get("nodes", [])))
            })
            
            # 递归处理子节点
            for child in node.get("children", node.get("nodes", [])):
                traverse(child, level + 1, node_id)
        
        for root in structure:
            traverse(root)
        
        return flat_nodes
    
    def _build_prompt(
        self,
        flat_nodes: List[Dict],
        document_type: str,
        doc_classification: Dict[str, Any]
    ) -> str:
        """构建审核提示词"""
        
        # 文档类型特定的规范说明
        type_guidelines = self._get_type_guidelines(document_type)
        
        # 节点列表JSON
        nodes_json = json.dumps(flat_nodes, ensure_ascii=False, indent=2)
        
        prompt = f"""你是一个专业的文档结构质量审核专家。请审核以下文档的目录结构，提供改进建议。

# 文档信息
- 文档类型: {document_type} ({doc_classification.get('name', '')})
- 置信度: {doc_classification.get('confidence', 0):.2f}
- 特征: {doc_classification.get('characteristics', {}).get('title_style', '未知')}

# 文档类型规范
{type_guidelines}

# 提取的目录结构
共 {len(flat_nodes)} 个节点（前3层）：
```json
{nodes_json}
```

# 审核任务
请仔细审核每个节点，识别以下问题：

1. **DELETE (删除)** - 标题误识别
   - 完整的句子被当作标题（如："4、投标人不得相互串通..."）
   - 正文内容被当作标题
   - 重复的标题
   - 页眉页脚被当作标题

2. **MODIFY_FORMAT (格式修改)** - 标题格式问题
   - 编号格式不规范（如："1.1"应为"（一）"）
   - 标题结尾有标点符号（如："第一章。"）
   - 大小写不一致
   - 注意：只建议修改格式/编号，不要修改标题的实际内容文本

3. **MODIFY_PAGE (页码修正)** - 页码范围问题
   - 页码范围明显过大（如：一个小节跨越20页）
   - 页码范围明显过小（如：一章只有1页）
   - 页码范围与层级不匹配

4. **ADD (添加标题)** - 缺失重要标题
   - 根据文档类型规范，应该存在但缺失的标题
   - 两个标题之间页码跨度过大，可能缺失子标题
   - 注意：只建议添加置信度高的标题

5. **KEEP (保持)** - 标题正确
   - 不需要提及保持的标题，只提出需要修改的

# 返回格式
返回JSON格式的建议列表，每条建议包含：

```json
{{
  "advice": [
    {{
      "action": "DELETE|MODIFY_FORMAT|MODIFY_PAGE|ADD",
      "node_id": "节点ID (对于ADD操作，使用parent_id)",
      "reason": "简短的理由说明（为什么要这样操作）",
      "confidence": "high|medium|low",
      
      // 如果是 MODIFY_FORMAT
      "current_title": "当前标题",
      "suggested_format": "建议的格式（仅调整编号/标点，不改内容）",
      
      // 如果是 MODIFY_PAGE
      "current_pages": [起始页, 结束页],
      "suggested_pages": [建议起始页, 建议结束页],
      
      // 如果是 ADD
      "parent_id": "父节点ID",
      "suggested_title": "建议的标题文本",
      "suggested_level": 层级数字,
      "suggested_pages": [建议起始页, 建议结束页],
      "insert_position": "before_node_id或after_node_id"
    }}
  ]
}}
```

# 重要原则
1. **保守原则**: 只提出有把握的建议（confidence >= medium）
2. **内容不变**: MODIFY_FORMAT 只能调整编号/格式，不能改变标题的实际内容
3. **验证原则**: 所有建议都需要能通过PDF核实
4. **层级一致**: 保持标题的层级关系逻辑正确
5. **高置信度优先**: 优先提出 confidence=high 的建议

请返回审核建议："""

        return prompt
    
    def _get_type_guidelines(self, document_type: str) -> str:
        """获取文档类型的规范说明"""
        guidelines = {
            "tender": """
招标文件标准结构：
- 第一章 招标公告
- 第二章 投标人须知
  - 一、总则
    - （一）适用范围
    - （二）定义
  - 二、招标文件
- 第三章 评标办法及评分标准
- 第四章 采购需求
- 第五章 合同文本
- 第六章 投标文件格式附件

标题规范：
- 章节：第X章
- 一级标题：一、二、三、
- 二级标题：（一）（二）（三）
- 三级标题：1、2、3、
- 不应有完整的句子作为标题
- 标题不应以标点符号结尾
""",
            "bid": """
投标文件标准结构：
- 投标函
- 开标一览表
- 技术部分
  - 技术方案
  - 技术响应
  - 产品介绍
- 商务部分
  - 商务响应
  - 报价明细
- 资格证明
  - 营业执照
  - 资质证书

标题规范：
- 简洁明了
- 不使用完整句子
- 编号可以是数字或文字
""",
            "academic": """
学术论文标准结构：
- Abstract
- Introduction
- Related Work / Literature Review
- Methodology
- Experiments / Results
- Discussion
- Conclusion
- References

标题规范：
- 英文论文：首字母大写
- 中文论文：第X章 / X.X
- 层级清晰（Chapter > Section > Subsection）
""",
            "technical": """
技术文档标准结构：
- Getting Started
- Installation
- Configuration
- API Reference
  - Classes
  - Functions
  - Endpoints
- Examples
- Troubleshooting

标题规范：
- 使用技术术语
- 清晰的层级（Module > Class > Method）
- 可以包含代码相关符号
""",
            "general": """
通用文档规范：
- 标题应简洁明了
- 不应有完整的句子
- 层级结构合理
- 编号连续一致
"""
        }
        
        return guidelines.get(document_type, guidelines["general"])
    
    def _summarize_advice(self, advice_list: List[Dict], total_nodes: int) -> Dict:
        """汇总建议统计"""
        summary = {
            "total_nodes": total_nodes,
            "to_delete": 0,
            "to_modify_format": 0,
            "to_modify_page": 0,
            "to_add": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0
        }
        
        for advice in advice_list:
            action = advice.get("action", "").upper()
            confidence = advice.get("confidence", "low")
            
            if action == "DELETE":
                summary["to_delete"] += 1
            elif action == "MODIFY_FORMAT":
                summary["to_modify_format"] += 1
            elif action == "MODIFY_PAGE":
                summary["to_modify_page"] += 1
            elif action == "ADD":
                summary["to_add"] += 1
            
            if confidence == "high":
                summary["high_confidence"] += 1
            elif confidence == "medium":
                summary["medium_confidence"] += 1
            else:
                summary["low_confidence"] += 1
        
        summary["to_keep"] = total_nodes - summary["to_delete"]
        
        return summary
