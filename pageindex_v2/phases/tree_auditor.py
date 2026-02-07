"""
Tree Quality Auditor - Post-processing quality control for tree structures
对生成的tree.json进行审核和修复

功能：
1. 规则检查：标题格式、长度、重复内容等
2. LLM深度审核：结构合理性、标题准确性
3. 自动修复：移除无效节点、合并重复内容、调整层级
4. 审核报告：详细记录发现的问题和修复操作
"""

import re
import json
from typing import List, Dict, Any, Optional, Tuple
from ..core.llm_client import LLMClient


def _get_children(node: Dict, default=None) -> List:
    """获取子节点，支持 nodes 和 children 两种字段名"""
    if default is None:
        default = []
    return node.get("children", node.get("nodes", default))


def _set_children(node: Dict, children: List) -> None:
    """设置子节点，优先使用已有的字段名"""
    if "children" in node:
        node["children"] = children
    else:
        node["nodes"] = children


def _has_children(node: Dict) -> bool:
    """检查节点是否有子节点"""
    return bool(_get_children(node))


class TreeAuditor:
    """
    树结构审核器
    
    审核内容：
    - 标题质量（格式、长度、完整性）
    - 内容重复检测
    - 层级结构合理性
    - 页码范围准确性
    """
    
    def __init__(self, llm: Optional[LLMClient] = None, debug: bool = True):
        self.llm = llm
        self.debug = debug
        self.issues = []  # 记录发现的问题
        self.fixes = []   # 记录应用的修复
    
    async def audit_and_fix(
        self,
        tree: Dict[str, Any],
        pdf_path: Optional[str] = None,
        document_type: str = "auto"
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        审核并修复树结构
        
        Args:
            tree: PageIndex输出的完整结果（包含structure字段）
            pdf_path: PDF文件路径（可选，用于高级审核）
            document_type: 文档类型 (auto/tender/academic/technical)
        
        Returns:
            (audited_tree, audit_report)
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[TREE AUDITOR] Starting tree quality audit")
            print(f"{'='*60}")
        
        # 重置记录
        self.issues = []
        self.fixes = []
        
        # 检测文档类型
        if document_type == "auto":
            document_type = self._detect_document_type(tree)
            if self.debug:
                print(f"[AUDIT] Detected document type: {document_type}")
        
        # 提取structure字段（树列表）
        # 支持两种格式：
        # 1. {"structure": [...]}  - 旧格式
        # 2. {"id": "root", "children": [...]} - 新格式
        structure = tree.get("structure", [])
        is_root_format = False
        if not structure and "children" in tree:
            # 新格式：使用children作为structure
            structure = tree.get("children", [])
            is_root_format = True
        
        if not structure:
            if self.debug:
                print("[AUDIT] ⚠ No structure found in tree")
            return tree, self._generate_report(tree, document_type)
        
        # Phase 1: 规则检查
        if self.debug:
            print("\n[AUDIT] Phase 1: Rule-based validation")
        structure = self._rule_based_validation(structure, document_type)
        
        # Phase 2: LLM深度审核（如果有LLM）
        if self.llm and len(structure) > 0:
            if self.debug:
                print("\n[AUDIT] Phase 2: LLM-based deep audit")
            structure = await self._llm_based_audit(structure, document_type)
        
        # Phase 3: 内容去重
        if self.debug:
            print("\n[AUDIT] Phase 3: Content deduplication")
        structure = self._deduplicate_content(structure)
        
        # 更新tree
        if is_root_format:
            audited_tree = {**tree, "children": structure}
        else:
            audited_tree = {**tree, "structure": structure}
        
        # 生成审核报告
        report = self._generate_report(audited_tree, document_type)
        
        if self.debug:
            print(f"\n[AUDIT] ✅ Audit complete")
            print(f"  - Issues found: {len(self.issues)}")
            print(f"  - Fixes applied: {len(self.fixes)}")
            print(f"{'='*60}\n")
        
        return audited_tree, report
    
    def _detect_document_type(self, tree: Dict) -> str:
        """检测文档类型"""
        source_file = tree.get("source_file", "").lower()
        
        # 从结构中提取一些标题样本
        structure = tree.get("structure", [])
        titles = []
        
        def collect_titles(node, depth=0):
            if depth > 2:  # 只看前3层
                return
            titles.append(node.get("title", ""))
            # 支持 "nodes" 和 "children" 两种字段名
            for child in node.get("nodes", node.get("children", [])):
                collect_titles(child, depth + 1)
        
        for node in structure[:5]:  # 只看前5个根节点
            collect_titles(node)
        
        all_text = " ".join(titles).lower()
        
        # 检测关键词
        if any(kw in all_text for kw in ["招标", "投标", "采购", "竞标"]):
            return "tender"  # 招标文件
        elif any(kw in all_text for kw in ["chapter", "section", "introduction"]):
            return "academic"  # 学术文档
        elif any(kw in all_text for kw in ["api", "function", "class", "method"]):
            return "technical"  # 技术文档
        else:
            return "general"  # 通用文档
    
    def _rule_based_validation(
        self,
        structure: List[Dict],
        document_type: str
    ) -> List[Dict]:
        """规则检查和修复"""
        
        # 获取文档类型特定的规则
        rules = self._get_validation_rules(document_type)
        
        def validate_and_fix_node(node: Dict, parent_title: str = "") -> Optional[Dict]:
            """递归验证并修复节点"""
            title = node.get("title", "")
            
            # 检查1: 标题长度
            if len(title) > rules["max_title_length"]:
                self.issues.append({
                    "type": "title_too_long",
                    "node_id": node.get("node_id", "unknown"),
                    "title": title,
                    "length": len(title)
                })
                
                # 尝试修复：截断或移除
                if len(title) > rules["max_title_length"] * 2:
                    # 太长，可能是错误提取，移除此节点
                    self.fixes.append({
                        "action": "remove_node",
                        "reason": "title_too_long",
                        "node_id": node.get("node_id"),
                        "title": title[:50] + "..."
                    })
                    return None  # 移除此节点
                else:
                    # 截断标题
                    original_title = title
                    node["title"] = title[:rules["max_title_length"]] + "..."
                    self.fixes.append({
                        "action": "truncate_title",
                        "node_id": node.get("node_id"),
                        "from": original_title,
                        "to": node["title"]
                    })
            
            # 检查2: 标题格式（针对招标文件）
            if document_type == "tender":
                if not self._is_valid_tender_title(title):
                    self.issues.append({
                        "type": "invalid_title_format",
                        "node_id": node.get("node_id"),
                        "title": title,
                        "reason": "not_matching_tender_patterns"
                    })
                    
                    # 如果是明显的条款内容（不是标题），移除
                    if self._is_clause_content(title):
                        self.fixes.append({
                            "action": "remove_node",
                            "reason": "clause_not_heading",
                            "node_id": node.get("node_id"),
                            "title": title
                        })
                        return None
            
            # 检查3: 标题以标点结尾
            if title.endswith('。') or title.endswith('，'):
                self.issues.append({
                    "type": "title_ends_with_punctuation",
                    "node_id": node.get("node_id"),
                    "title": title
                })
                
                # 修复：移除结尾标点
                node["title"] = title.rstrip('。，、；：')
                self.fixes.append({
                    "action": "remove_ending_punctuation",
                    "node_id": node.get("node_id"),
                    "from": title,
                    "to": node["title"]
                })
            
            # 检查4: 内容字段存在性
            if "content" in node:
                content_len = len(node.get("content", ""))
                if content_len == 0:
                    # 空内容，可以移除
                    del node["content"]
            
            # 递归处理子节点
            children = _get_children(node)
            if children:
                valid_children = []
                for child in children:
                    fixed_child = validate_and_fix_node(child, title)
                    if fixed_child is not None:
                        valid_children.append(fixed_child)
                
                if valid_children:
                    _set_children(node, valid_children)
                else:
                    # 如果所有子节点都被移除，删除子节点字段
                    if "children" in node:
                        del node["children"]
                    if "nodes" in node:
                        del node["nodes"]
            
            return node
        
        # 处理所有根节点
        validated_structure = []
        for root in structure:
            fixed_root = validate_and_fix_node(root)
            if fixed_root is not None:
                validated_structure.append(fixed_root)
        
        if self.debug:
            removed_count = len(structure) - len(validated_structure)
            if removed_count > 0:
                print(f"  - Removed {removed_count} invalid nodes")
            print(f"  - Issues found: {len(self.issues)}")
            print(f"  - Fixes applied: {len(self.fixes)}")
        
        return validated_structure
    
    def _is_valid_tender_title(self, title: str) -> bool:
        """检查是否为有效的招标文件标题"""
        # 有效的招标文件标题模式
        valid_patterns = [
            r'^第[一二三四五六七八九十\d]+章',      # 第一章、第1章
            r'^[一二三四五六七八九十]+、',          # 一、二、三、
            r'^（[一二三四五六七八九十]+）',        # （一）（二）
            r'^附件\s*\d*:?',                       # 附件1:、附件:
            r'^前言',                               # 前言
            r'^目\s*录',                            # 目录
            r'^Preface',                            # Preface
        ]
        
        for pattern in valid_patterns:
            if re.match(pattern, title):
                return True
        
        # 如果标题很短且没有标点，也可能是有效的
        if len(title) <= 15 and not re.search(r'[。，、；：]', title):
            return True
        
        return False
    
    def _is_clause_content(self, title: str) -> bool:
        """检查是否为条款内容（而非标题）"""
        # 条款内容的特征
        clause_indicators = [
            len(title) > 40,  # 太长
            title.endswith('。') or title.endswith('，'),  # 以标点结尾
            '不得' in title and len(title) > 25,  # 包含"不得"的长句
            '应当' in title and len(title) > 25,  # 包含"应当"的长句
            '必须' in title and len(title) > 25,  # 包含"必须"的长句
            re.match(r'^\d+、.{30,}', title),  # "1、..."开头且很长
        ]
        
        # 如果满足2个以上特征，判定为条款内容
        return sum(clause_indicators) >= 2
    
    def _get_validation_rules(self, document_type: str) -> Dict:
        """获取文档类型特定的验证规则"""
        rules_map = {
            "tender": {
                "max_title_length": 50,
                "allow_punctuation": False,
                "min_title_length": 2,
            },
            "academic": {
                "max_title_length": 100,
                "allow_punctuation": False,
                "min_title_length": 3,
            },
            "technical": {
                "max_title_length": 80,
                "allow_punctuation": False,
                "min_title_length": 2,
            },
            "general": {
                "max_title_length": 60,
                "allow_punctuation": False,
                "min_title_length": 2,
            }
        }
        
        return rules_map.get(document_type, rules_map["general"])
    
    async def _llm_based_audit(
        self,
        structure: List[Dict],
        document_type: str
    ) -> List[Dict]:
        """LLM深度审核"""
        
        # 扁平化结构，只看level <= 3的节点
        flat_nodes = []
        
        def flatten(node, level=0):
            if level <= 3:  # 只审核前3层
                flat_nodes.append({
                    "node_id": node.get("node_id", node.get("id", "")),
                    "title": node.get("title", ""),
                    "level": level,
                    "page_start": node.get("start_index", node.get("page_start")),
                    "page_end": node.get("end_index", node.get("page_end")),
                })
            
            for child in _get_children(node):
                flatten(child, level + 1)
        
        for root in structure:
            flatten(root)
        
        if len(flat_nodes) == 0:
            return structure
        
        # 限制审核的节点数量（避免token过多）
        if len(flat_nodes) > 30:
            # 优先审核level >= 2的节点（更可能有问题）
            flat_nodes.sort(key=lambda x: -x["level"])
            flat_nodes = flat_nodes[:30]
        
        # 构建审核Prompt
        doc_type_hints = {
            "tender": "Chinese government procurement/tender document (招标文件)",
            "academic": "Academic or technical book",
            "technical": "Technical documentation",
            "general": "General document"
        }
        
        prompt = f"""You are a document structure quality auditor. Review the following extracted table of contents.

Document Type: {doc_type_hints.get(document_type, "General document")}

Extracted TOC Structure:
{json.dumps(flat_nodes, ensure_ascii=False, indent=2)}

Task: Identify titles that are INCORRECTLY extracted (should not be headings).

For {document_type} documents:
{"- Valid headings: '第X章', '一、', '（一）', '附件', short phrases (<20 chars)" if document_type == "tender" else ""}
{"- Invalid: Numbered clauses '1、...', complete sentences, content descriptions" if document_type == "tender" else ""}

Review Criteria:
1. Is the title too long? (>50 chars = suspicious)
2. Does it end with punctuation? (。，= suspicious)
3. Is it a complete sentence rather than a heading?
4. Does the format match expected patterns for this document type?

Return JSON:
{{
  "invalid_nodes": [
    {{
      "node_id": "0005",
      "reason": "Complete sentence, not a heading",
      "confidence": "high",
      "suggested_action": "remove"
    }}
  ],
  "overall_quality": "good/fair/poor"
}}

Only flag nodes with HIGH confidence. Be conservative.
"""
        
        try:
            result = await self.llm.chat_json(prompt, max_tokens=2000)
            
            invalid_nodes = result.get("invalid_nodes", [])
            
            if self.debug:
                print(f"  - LLM identified {len(invalid_nodes)} invalid nodes")
            
            # 根据LLM的建议移除节点
            if invalid_nodes:
                invalid_ids = set(
                    node["node_id"] 
                    for node in invalid_nodes 
                    if node.get("confidence") == "high"
                )
                
                structure = self._remove_nodes_by_id(structure, invalid_ids)
                
                # 记录修复
                for node in invalid_nodes:
                    if node.get("confidence") == "high":
                        self.fixes.append({
                            "action": "remove_node",
                            "reason": f"llm_audit: {node.get('reason')}",
                            "node_id": node.get("node_id")
                        })
            
        except Exception as e:
            if self.debug:
                print(f"  ⚠ LLM audit failed: {e}")
        
        return structure
    
    def _remove_nodes_by_id(
        self,
        structure: List[Dict],
        invalid_ids: set
    ) -> List[Dict]:
        """根据node_id移除节点"""
        
        def filter_node(node):
            # 检查当前节点（支持 node_id 和 id 两种字段名）
            node_id = node.get("node_id", node.get("id"))
            if node_id in invalid_ids:
                return None  # 移除此节点
            
            # 递归过滤子节点
            children = _get_children(node)
            if children:
                valid_children = []
                for child in children:
                    filtered = filter_node(child)
                    if filtered is not None:
                        valid_children.append(filtered)
                
                if valid_children:
                    _set_children(node, valid_children)
                else:
                    # 删除子节点字段
                    if "children" in node:
                        del node["children"]
                    if "nodes" in node:
                        del node["nodes"]
            
            return node
        
        return [
            filtered
            for node in structure
            if (filtered := filter_node(node)) is not None
        ]
    
    def _deduplicate_content(self, structure: List[Dict]) -> List[Dict]:
        """去除重复的content字段"""
        
        # 收集所有节点的content
        content_hashes = {}
        
        def collect_content(node):
            if "content" in node:
                content = node.get("content", "")
                if content:
                    # 使用前200字符作为哈希键
                    hash_key = content[:200]
                    node_id = node.get("node_id", node.get("id"))
                    
                    if hash_key in content_hashes:
                        # 发现重复
                        content_hashes[hash_key].append(node_id)
                    else:
                        content_hashes[hash_key] = [node_id]
            
            for child in _get_children(node):
                collect_content(child)
        
        for root in structure:
            collect_content(root)
        
        # 找出重复的content
        duplicates = {k: v for k, v in content_hashes.items() if len(v) > 1}
        
        if duplicates:
            if self.debug:
                print(f"  - Found {len(duplicates)} duplicate content groups")
            
            # 对于重复的content，只保留第一个，其他的移除content字段
            for hash_key, node_ids in duplicates.items():
                # 保留第一个，移除其他的
                for node_id in node_ids[1:]:
                    self._remove_content_field(structure, node_id)
                    
                    self.issues.append({
                        "type": "duplicate_content",
                        "node_ids": node_ids,
                        "hash": hash_key[:50]
                    })
                    
                    self.fixes.append({
                        "action": "remove_duplicate_content",
                        "node_id": node_id,
                        "kept_in": node_ids[0]
                    })
        
        return structure
    
    def _remove_content_field(self, structure: List[Dict], target_id: str):
        """移除指定节点的content字段"""
        
        def remove_from_node(node):
            node_id = node.get("node_id", node.get("id"))
            if node_id == target_id:
                if "content" in node:
                    del node["content"]
                return True
            
            for child in _get_children(node):
                if remove_from_node(child):
                    return True
            
            return False
        
        for root in structure:
            if remove_from_node(root):
                break
    
    def _generate_report(
        self,
        tree: Dict,
        document_type: str
    ) -> Dict[str, Any]:
        """生成审核报告"""
        
        structure = tree.get("structure", tree.get("children", []))
        
        # 统计信息
        def count_nodes(node):
            count = 1
            for child in _get_children(node):
                count += count_nodes(child)
            return count
        
        total_nodes = sum(count_nodes(root) for root in structure)
        
        # 分类问题
        issues_by_type = {}
        for issue in self.issues:
            issue_type = issue.get("type", "unknown")
            if issue_type not in issues_by_type:
                issues_by_type[issue_type] = []
            issues_by_type[issue_type].append(issue)
        
        # 分类修复
        fixes_by_action = {}
        for fix in self.fixes:
            action = fix.get("action", "unknown")
            if action not in fixes_by_action:
                fixes_by_action[action] = []
            fixes_by_action[action].append(fix)
        
        # 质量评分
        quality_score = self._calculate_quality_score(
            total_nodes,
            len(self.issues),
            len(self.fixes)
        )
        
        report = {
            "document_type": document_type,
            "total_nodes": total_nodes,
            "quality_score": quality_score,
            "summary": {
                "issues_found": len(self.issues),
                "fixes_applied": len(self.fixes),
                "nodes_removed": len([f for f in self.fixes if f["action"] == "remove_node"]),
                "content_deduplicated": len([f for f in self.fixes if f["action"] == "remove_duplicate_content"])
            },
            "issues_by_type": {
                k: len(v) for k, v in issues_by_type.items()
            },
            "fixes_by_action": {
                k: len(v) for k, v in fixes_by_action.items()
            },
            "detailed_issues": self.issues[:20],  # 只保留前20个
            "detailed_fixes": self.fixes[:20],    # 只保留前20个
            "recommendations": self._generate_recommendations(
                issues_by_type,
                document_type
            )
        }
        
        return report
    
    def _calculate_quality_score(
        self,
        total_nodes: int,
        issues_count: int,
        fixes_count: int
    ) -> float:
        """计算质量评分 (0-100)"""
        
        if total_nodes == 0:
            return 0.0
        
        # 基础分数
        score = 100.0
        
        # 每个问题扣分
        issue_penalty = min(issues_count * 2, 40)  # 最多扣40分
        score -= issue_penalty
        
        # 移除节点的比例
        nodes_removed = len([f for f in self.fixes if f["action"] == "remove_node"])
        removal_rate = nodes_removed / total_nodes
        removal_penalty = min(removal_rate * 50, 30)  # 最多扣30分
        score -= removal_penalty
        
        return max(score, 0.0)
    
    def _generate_recommendations(
        self,
        issues_by_type: Dict,
        document_type: str
    ) -> List[str]:
        """生成改进建议"""
        
        recommendations = []
        
        if "title_too_long" in issues_by_type:
            recommendations.append(
                "Many titles are too long. Consider improving TOC extraction or Gap Filler prompts."
            )
        
        if "invalid_title_format" in issues_by_type:
            if document_type == "tender":
                recommendations.append(
                    "Invalid title formats detected. Gap Filler may be extracting content clauses as headings. "
                    "Consider adding stricter heading pattern validation."
                )
        
        if "duplicate_content" in issues_by_type:
            recommendations.append(
                "Duplicate content detected across nodes. Consider improving page range calculation "
                "to avoid overlapping content extraction."
            )
        
        if not recommendations:
            recommendations.append("Tree structure quality is good. No major issues detected.")
        
        return recommendations


async def audit_tree_file(
    tree_file_path: str,
    output_dir: Optional[str] = None,
    llm: Optional[LLMClient] = None,
    debug: bool = True
) -> Tuple[str, str]:
    """
    审核tree.json文件并保存结果
    
    Args:
        tree_file_path: _tree.json文件路径
        output_dir: 输出目录（默认与输入文件同目录）
        llm: LLM客户端（可选）
        debug: 是否输出调试信息
    
    Returns:
        (audited_tree_path, report_path)
    """
    import os
    
    # 读取原始tree
    with open(tree_file_path, 'r', encoding='utf-8') as f:
        tree = json.load(f)
    
    # 创建审核器
    auditor = TreeAuditor(llm=llm, debug=debug)
    
    # 执行审核
    audited_tree, report = await auditor.audit_and_fix(tree)
    
    # 确定输出路径
    if output_dir is None:
        output_dir = os.path.dirname(tree_file_path)
    
    base_name = os.path.basename(tree_file_path).replace("_tree.json", "")
    audited_path = os.path.join(output_dir, f"{base_name}_tree_audited.json")
    report_path = os.path.join(output_dir, f"{base_name}_audit_report.json")
    
    # 保存审核后的tree
    with open(audited_path, 'w', encoding='utf-8') as f:
        json.dump(audited_tree, f, indent=2, ensure_ascii=False)
    
    # 保存审核报告
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    if debug:
        print(f"\n✅ Audit complete!")
        print(f"  - Audited tree: {audited_path}")
        print(f"  - Report: {report_path}")
        print(f"  - Quality score: {report['quality_score']:.1f}/100")
    
    return audited_path, report_path
