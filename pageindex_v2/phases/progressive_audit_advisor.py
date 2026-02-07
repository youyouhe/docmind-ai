"""
渐进式审核建议生成器
Progressive Audit Advisor

分多轮次渐进式生成审核建议，每轮专注一个任务
"""

import json
from typing import Dict, List, Any, Optional, Tuple
from ..core.llm_client import LLMClient


class ProgressiveAuditAdvisor:
    """
    渐进式审核顾问
    
    审核流程：
    Round 1: 删除明显错误的节点（DELETE）
    Round 2: 修正标题格式（MODIFY_FORMAT）
    Round 3: 检查编号连续性，发现缺失节点
    Round 4: 添加缺失节点（ADD）- 需要PDF核实
    Round 5: 调整页码范围（MODIFY_PAGE）
    """
    
    def __init__(self, llm: LLMClient, debug: bool = False):
        self.llm = llm
        self.debug = debug
    
    async def generate_progressive_advice(
        self,
        tree: Dict[str, Any],
        document_type: str,
        doc_classification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        渐进式生成审核建议
        
        Returns:
            {
                "rounds": [
                    {
                        "round": 1,
                        "focus": "DELETE",
                        "advice": [...],
                        "summary": {...}
                    },
                    ...
                ],
                "final_advice": [...],  # 所有建议的合集
                "summary": {...}
            }
        """
        if self.debug:
            print("\n" + "="*60)
            print("[PROGRESSIVE ADVISOR] Starting Progressive Audit")
            print("="*60)
        
        all_rounds = []
        current_tree = tree
        
        # Round 1: DELETE - 删除明显错误的节点
        round1_result = await self._round1_delete(current_tree, document_type, doc_classification)
        all_rounds.append(round1_result)
        
        if self.debug:
            print(f"\n[OK] Round 1 complete: {len(round1_result['advice'])} DELETE suggestions")
        
        # Round 2: MODIFY_FORMAT - 修正格式
        round2_result = await self._round2_format(current_tree, document_type, doc_classification)
        all_rounds.append(round2_result)
        
        if self.debug:
            print(f"[OK] Round 2 complete: {len(round2_result['advice'])} FORMAT suggestions")
        
        # Round 3: CHECK_SEQUENCE - 检查编号连续性
        round3_result = await self._round3_sequence(current_tree, document_type, doc_classification)
        all_rounds.append(round3_result)
        
        if self.debug:
            print(f"[OK] Round 3 complete: Found {len(round3_result['missing_sequences'])} missing sequences")
        
        # Round 4: ADD - 基于缺失编号添加节点
        round4_result = await self._round4_add(
            current_tree, 
            round3_result['missing_sequences'],
            document_type,
            doc_classification
        )
        all_rounds.append(round4_result)
        
        if self.debug:
            print(f"[OK] Round 4 complete: {len(round4_result['advice'])} ADD suggestions")
        
        # Round 5: MODIFY_PAGE - 调整页码范围
        round5_result = await self._round5_pages(current_tree, document_type, doc_classification)
        all_rounds.append(round5_result)
        
        if self.debug:
            print(f"[OK] Round 5 complete: {len(round5_result['advice'])} PAGE suggestions")
        
        # Round 6: EXPAND - 检测需要扩展分析的节点
        round6_result = self._round6_expand(current_tree, document_type, doc_classification)
        all_rounds.append(round6_result)
        
        if self.debug:
            print(f"[OK] Round 6 complete: {len(round6_result['advice'])} EXPAND suggestions")
        
        # 汇总所有建议
        final_advice = []
        for round_result in all_rounds:
            final_advice.extend(round_result.get('advice', []))
        
        if self.debug:
            print(f"\n[SUMMARY] Total advice generated: {len(final_advice)}")
            print("="*60 + "\n")
        
        return {
            "rounds": all_rounds,
            "final_advice": final_advice,
            "summary": self._summarize_rounds(all_rounds)
        }
    
    async def _round1_delete(
        self,
        tree: Dict,
        document_type: str,
        doc_classification: Dict
    ) -> Dict:
        """Round 1: 删除明显错误的节点"""
        
        flat_nodes = self._flatten_tree(tree)
        type_guidelines = self._get_type_guidelines(document_type)
        
        prompt = f"""你是文档结构审核专家。

# 任务
第1轮审核：**只关注删除明显错误的节点**

# 文档信息
- 类型: {document_type} ({doc_classification.get('name', '')})
- 标准编号规范: {type_guidelines}

# 提取的目录（前50个节点）
{json.dumps(flat_nodes[:50], ensure_ascii=False, indent=2)}

# 需要删除的情况
1. **完整句子** - 长度过长且包含完整语义的正文句子
2. **正文条款** - 以编号开头的详细条款内容（非标题）
3. **页眉页脚** - 重复出现的页码、文件名等元信息
4. **重复标题** - 完全相同的标题重复出现多次
5. **明显不是标题** - 日期、签名、表格标签等非标题内容
6. **检查子节点** - 如果一个节点有子节点，通常说明它是真实的章节标题，不应删除

# 返回格式
{{
  "advice": [
    {{
      "action": "DELETE",
      "node_id": "节点ID",
      "reason": "删除理由",
      "confidence": "high|medium|low",
      "evidence": "支持删除的证据"
    }}
  ]
}}

# 原则
- **保守原则**: 只删除明显错误的节点（confidence >= medium）
- **宁可漏删**: 不确定的保留，后续轮次再处理
- **不要管格式**: 这一轮不关心格式问题，只删除明显的误识别
- **检查上下文**: 考虑节点的层级关系和子节点情况

请返回建议："""

        try:
            response = await self.llm.chat_json(prompt, temperature=0.1)
            advice_list = response.get("advice", [])
            
            return {
                "round": 1,
                "focus": "DELETE",
                "advice": advice_list,
                "summary": {
                    "total": len(advice_list),
                    "high_confidence": sum(1 for a in advice_list if a.get("confidence") == "high"),
                    "medium_confidence": sum(1 for a in advice_list if a.get("confidence") == "medium")
                }
            }
        except Exception as e:
            if self.debug:
                print(f"[PROGRESSIVE ADVISOR] Round 1 error: {e}")
            return {"round": 1, "focus": "DELETE", "advice": [], "summary": {"error": str(e)}}
    
    def _round6_expand(
        self,
        tree: Dict,
        document_type: str,
        doc_classification: Dict
    ) -> Dict:
        """
        Round 6: 检测需要扩展分析的节点
        
        检测页码跨度过大且无/少子结构的节点，建议进行 EXPAND 操作
        """
        flat_nodes = self._flatten_tree(tree)
        expand_candidates = []
        
        for node in flat_nodes:
            page_start = node.get("page_start")
            page_end = node.get("page_end")
            
            if not page_start or not page_end:
                continue
            
            span = page_end - page_start + 1
            level = node.get("level", 1)
            children_count = len(node.get("children", []))
            
            # 检测规则1: 页码跨度 > 15 页，且无子节点
            if span > 15 and children_count == 0 and level <= 2:
                expand_candidates.append({
                    "node_id": node["id"],
                    "title": node["title"],
                    "span": span,
                    "level": level,
                    "children_count": 0,
                    "reason": f"页码跨度 {span} 页，但无子结构，建议重新分析以提取细粒度结构"
                })
            
            # 检测规则2: 页码跨度 > 25 页，且子节点很少 (< 3个)
            elif span > 25 and children_count < 3 and level <= 2:
                expand_candidates.append({
                    "node_id": node["id"],
                    "title": node["title"],
                    "span": span,
                    "level": level,
                    "children_count": children_count,
                    "reason": f"页码跨度 {span} 页，但仅有 {children_count} 个子节点，结构过于粗糙"
                })
        
        # 生成 EXPAND 建议
        advice_list = []
        for candidate in expand_candidates[:10]:  # 最多处理10个
            advice_list.append({
                "action": "EXPAND",
                "node_id": candidate["node_id"],
                "reason": candidate["reason"],
                "confidence": "high",  # EXPAND 建议通常置信度较高
                "node_info": {
                    "page_range": [
                        # 从 flat_nodes 中找到对应节点获取页码
                        next((n.get("page_start") for n in flat_nodes if n["id"] == candidate["node_id"]), 0),
                        next((n.get("page_end") for n in flat_nodes if n["id"] == candidate["node_id"]), 0)
                    ],
                    "target_depth": candidate["level"] + 2,  # 期望解析到当前层级+2
                    "current_span": candidate["span"],
                    "current_children": candidate["children_count"]
                }
            })
        
        return {
            "round": 6,
            "focus": "EXPAND",
            "advice": advice_list,
            "summary": {
                "total": len(advice_list),
                "candidates_found": len(expand_candidates)
            }
        }
    
    async def _round2_format(
        self,
        tree: Dict,
        document_type: str,
        doc_classification: Dict
    ) -> Dict:
        """Round 2: 修正标题格式"""
        
        flat_nodes = self._flatten_tree(tree)
        type_guidelines = self._get_type_guidelines(document_type)
        
        prompt = f"""你是文档结构审核专家。

# 任务
第2轮审核：**只关注标题格式问题**

# 文档信息
- 类型: {document_type} ({doc_classification.get('name', '')})
- 规范: {type_guidelines}

# 提取的目录（前50个节点）
{json.dumps(flat_nodes[:50], ensure_ascii=False, indent=2)}

# 需要修正的格式问题
1. **编号格式不规范** - 不符合文档类型的标准编号格式
2. **标点符号错误** - 标题结尾有标点符号
3. **大小写不一致** - 英文标题的大小写问题
4. **空格问题** - 多余或缺失的空格

# 返回格式
{{
  "advice": [
    {{
      "action": "MODIFY_FORMAT",
      "node_id": "节点ID",
      "reason": "修改理由",
      "confidence": "high|medium|low",
      "current_title": "当前标题",
      "suggested_format": "建议的格式"
    }}
  ]
}}

# 原则
- **只关注格式**: 这一轮只处理格式问题
- **不改内容**: 只能调整编号/标点，不能改变标题的实际内容
- **保守原则**: 只修正明显的格式错误

请返回建议："""

        try:
            response = await self.llm.chat_json(prompt, temperature=0.1)
            advice_list = response.get("advice", [])
            
            return {
                "round": 2,
                "focus": "MODIFY_FORMAT",
                "advice": advice_list,
                "summary": {
                    "total": len(advice_list),
                    "high_confidence": sum(1 for a in advice_list if a.get("confidence") == "high")
                }
            }
        except Exception as e:
            if self.debug:
                print(f"[PROGRESSIVE ADVISOR] Round 2 error: {e}")
            return {"round": 2, "focus": "MODIFY_FORMAT", "advice": [], "summary": {"error": str(e)}}
    
    async def _round3_sequence(
        self,
        tree: Dict,
        document_type: str,
        doc_classification: Dict
    ) -> Dict:
        """Round 3: 检查编号连续性，发现缺失节点"""
        
        flat_nodes = self._flatten_tree(tree)
        
        # 分析编号连续性，找出缺失的编号
        missing_sequences = []
        
        # 按层级分组
        by_level = {}
        for node in flat_nodes:
            level = node.get("level", 1)
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(node)
        
        # 检查每个层级的编号连续性
        for level, nodes in by_level.items():
            if level > 3:  # 只检查前3层
                continue
            
            # 提取编号
            sequences = []
            for node in nodes:
                title = node.get("title", "")
                # 简单的编号提取（可以根据文档类型优化）
                import re
                # 匹配: "第X章", "一、", "（一）", "1、", "1.1" 等
                patterns = [
                    r'第([零一二三四五六七八九十百]+)章',
                    r'^([一二三四五六七八九十百]+)、',
                    r'（([一二三四五六七八九十百]+)）',
                    r'^(\d+)、',
                    r'^(\d+)\.(\d+)',
                ]
                for pattern in patterns:
                    match = re.search(pattern, title)
                    if match:
                        sequences.append({
                            "node": node,
                            "number": match.group(0),
                            "title": title
                        })
                        break
            
            # 检测缺失（简单实现：如果编号不连续，记录可能缺失的）
            # 这里只是一个示例，实际实现需要更复杂的逻辑
            if len(sequences) < len(nodes):
                missing_sequences.append({
                    "level": level,
                    "reason": f"层级 {level} 可能有缺失节点",
                    "checked_nodes": len(sequences)
                })
        
        return {
            "round": 3,
            "focus": "CHECK_SEQUENCE",
            "advice": [],  # 这一轮不生成建议，只是分析
            "missing_sequences": missing_sequences,
            "summary": {
                "levels_checked": len(by_level),
                "potential_gaps": len(missing_sequences)
            }
        }
    
    async def _round4_add(
        self,
        tree: Dict,
        missing_sequences: List[Dict],
        document_type: str,
        doc_classification: Dict
    ) -> Dict:
        """Round 4: 基于缺失编号添加节点"""
        
        if not missing_sequences:
            return {
                "round": 4,
                "focus": "ADD",
                "advice": [],
                "summary": {"total": 0}
            }
        
        flat_nodes = self._flatten_tree(tree)
        type_guidelines = self._get_type_guidelines(document_type)
        
        prompt = f"""你是文档结构审核专家。

# 任务
第4轮审核：**基于编号缺失和文档规范，建议添加缺失的标题**

# 文档信息
- 类型: {document_type} ({doc_classification.get('name', '')})
- 规范: {type_guidelines}

# 当前目录结构
{json.dumps(flat_nodes[:50], ensure_ascii=False, indent=2)}

# 检测到的潜在缺失
{json.dumps(missing_sequences, ensure_ascii=False, indent=2)}

# 添加建议的条件
1. **符合文档规范** - 根据文档类型，应该存在的标准章节
2. **编号连续性** - 编号序列中明显的缺失
3. **页码跨度大** - 两个标题之间页码跨度过大（>15页）

# 返回格式
{{
  "advice": [
    {{
      "action": "ADD",
      "parent_id": "父节点ID",
      "reason": "添加理由",
      "confidence": "high|medium|low",
      "node_info": {{
        "title": "建议的标题",
        "level": 层级数字,
        "page_start": 起始页,
        "page_end": 结束页,
        "position": "after_node_id 或 before_node_id"
      }}
    }}
  ]
}}

# 原则
- **高置信度优先**: 只建议 confidence >= medium 的添加
- **需要验证**: 所有添加都需要能从PDF中验证
- **保守原则**: 不确定的不要建议

请返回建议："""

        try:
            response = await self.llm.chat_json(prompt, temperature=0.1)
            advice_list = response.get("advice", [])
            
            return {
                "round": 4,
                "focus": "ADD",
                "advice": advice_list,
                "summary": {
                    "total": len(advice_list),
                    "high_confidence": sum(1 for a in advice_list if a.get("confidence") == "high")
                }
            }
        except Exception as e:
            if self.debug:
                print(f"[PROGRESSIVE ADVISOR] Round 4 error: {e}")
            return {"round": 4, "focus": "ADD", "advice": [], "summary": {"error": str(e)}}
    
    async def _round5_pages(
        self,
        tree: Dict,
        document_type: str,
        doc_classification: Dict
    ) -> Dict:
        """Round 5: 调整页码范围"""
        
        flat_nodes = self._flatten_tree(tree)
        
        prompt = f"""你是文档结构审核专家。

# 任务
第5轮审核：**只关注页码范围问题**

# 文档信息
- 类型: {document_type} ({doc_classification.get('name', '')})

# 提取的目录（前50个节点）
{json.dumps(flat_nodes[:50], ensure_ascii=False, indent=2)}

# 需要调整的页码问题
1. **页码范围明显过大** - 一个小节跨越过多页面
2. **页码范围明显过小** - 一章只有很少页面（不合理）
3. **页码重叠** - 同级节点的页码范围有重叠
4. **页码不连续** - 相邻节点的页码有间隙

# 返回格式
{{
  "advice": [
    {{
      "action": "MODIFY_PAGE",
      "node_id": "节点ID",
      "reason": "调整理由",
      "confidence": "high|medium|low",
      "current_pages": [起始页, 结束页],
      "suggested_pages": [建议起始页, 建议结束页]
    }}
  ]
}}

# 原则
- **只关注明显错误**: 这一轮只处理明显的页码问题
- **考虑层级**: 高层级标题应该有更大的页码范围
- **保守原则**: 不确定的不要调整

请返回建议："""

        try:
            response = await self.llm.chat_json(prompt, temperature=0.1)
            advice_list = response.get("advice", [])
            
            return {
                "round": 5,
                "focus": "MODIFY_PAGE",
                "advice": advice_list,
                "summary": {
                    "total": len(advice_list),
                    "high_confidence": sum(1 for a in advice_list if a.get("confidence") == "high")
                }
            }
        except Exception as e:
            if self.debug:
                print(f"[PROGRESSIVE ADVISOR] Round 5 error: {e}")
            return {"round": 5, "focus": "MODIFY_PAGE", "advice": [], "summary": {"error": str(e)}}
    
    def _flatten_tree(
        self,
        tree: Dict,
        max_depth: int = 3,
        max_nodes: int = 100
    ) -> List[Dict]:
        """扁平化树结构，提取节点信息"""
        flat_nodes = []
        
        def traverse(node, level=1, parent_id=None):
            if len(flat_nodes) >= max_nodes or level > max_depth:
                return
            
            # 获取节点ID
            node_id = node.get("id", node.get("node_id", f"node_{len(flat_nodes)}"))
            
            # 提取节点信息
            flat_nodes.append({
                "id": node_id,
                "title": node.get("title", ""),
                "level": node.get("level", level),
                "parent_id": parent_id,
                "page_start": node.get("page_start", node.get("start_index")),
                "page_end": node.get("page_end", node.get("end_index")),
                "children": node.get("children", [])
            })
            
            # 递归处理子节点
            for child in node.get("children", []):
                traverse(child, level + 1, node_id)
        
        # 处理根节点或children列表
        if "children" in tree:
            for root in tree["children"]:
                traverse(root)
        elif "structure" in tree:
            for root in tree["structure"]:
                traverse(root)
        elif isinstance(tree, list):
            for root in tree:
                traverse(root)
        else:
            traverse(tree)
        
        return flat_nodes
    
    def _get_type_guidelines(self, document_type: str) -> str:
        """获取文档类型的规范说明"""
        guidelines = {
            "tender": """招标文件标准编号: 第X章 -> 一、二、 -> （一）（二） -> 1、2、""",
            "bid": """投标文件：灵活编号，清晰层级""",
            "academic": """学术论文：Chapter > Section > Subsection""",
            "technical": """技术文档：清晰的模块层级""",
            "general": """通用文档：简洁明了的层级结构"""
        }
        return guidelines.get(document_type, guidelines["general"])
    
    def _count_by_level(self, missing_sequences: List[Dict]) -> Dict:
        """按层级统计缺失数量"""
        counts = {}
        for seq in missing_sequences:
            level = seq.get("level", 0)
            counts[level] = counts.get(level, 0) + 1
        return counts
    
    def _summarize_rounds(self, rounds: List[Dict]) -> Dict:
        """汇总所有轮次"""
        total_delete = sum(len(r.get("advice", [])) for r in rounds if r.get("focus") == "DELETE")
        total_format = sum(len(r.get("advice", [])) for r in rounds if r.get("focus") == "MODIFY_FORMAT")
        total_add = sum(len(r.get("advice", [])) for r in rounds if r.get("focus") == "ADD")
        total_page = sum(len(r.get("advice", [])) for r in rounds if r.get("focus") == "MODIFY_PAGE")
        total_expand = sum(len(r.get("advice", [])) for r in rounds if r.get("focus") == "EXPAND")
        
        return {
            "total_rounds": len(rounds),
            "by_action": {
                "DELETE": total_delete,
                "MODIFY_FORMAT": total_format,
                "ADD": total_add,
                "MODIFY_PAGE": total_page,
                "EXPAND": total_expand
            },
            "total_advice": total_delete + total_format + total_add + total_page + total_expand
        }
