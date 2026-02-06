"""
审核建议执行器
Audit Advice Executor

执行经过PDF验证的审核建议，生成最终版本的tree.json
"""

from typing import Dict, List, Any, Optional
import copy


class AdviceExecutor:
    """
    审核建议执行器
    
    执行经过验证的审核建议：
    1. DELETE - 删除节点
    2. MODIFY_FORMAT - 修改标题格式（只改编号，不改内容）
    3. MODIFY_PAGE - 修正页码范围
    4. ADD - 添加缺失的标题（暂不实现，需要更多PDF上下文）
    
    执行原则：
    - 只执行高置信度（confidence >= 0.7）的建议
    - 保持标题内容不变（只调整格式/编号）
    - 保持树结构的层级关系
    - 生成详细的执行日志
    """
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.execution_log = []
    
    def execute_advice(
        self,
        tree: Dict[str, Any],
        verified_advice: List[Dict],
        confidence_threshold: float = 0.7
    ) -> Dict[str, Any]:
        """
        执行审核建议
        
        Args:
            tree: 原始树结构
            verified_advice: 经过PDF验证的建议列表
            confidence_threshold: 置信度阈值（只执行高于此值的建议）
        
        Returns:
            {
                "tree": 更新后的树结构,
                "execution_log": [
                    {
                        "action": "DELETE",
                        "node_id": "0005",
                        "status": "executed|skipped",
                        "reason": "...",
                        "details": {...}
                    }
                ],
                "summary": {
                    "total_advice": 10,
                    "executed": 7,
                    "skipped": 3,
                    "deleted_nodes": 5,
                    "modified_formats": 2,
                    "modified_pages": 0
                }
            }
        """
        if self.debug:
            print("\n" + "="*60)
            print("[EXECUTOR] Executing Verified Advice")
            print(f"[EXECUTOR] Confidence threshold: {confidence_threshold}")
            print("="*60)
        
        # 深拷贝树，避免修改原始数据
        updated_tree = copy.deepcopy(tree)
        self.execution_log = []
        
        # 统计信息
        stats = {
            "total_advice": len(verified_advice),
            "executed": 0,
            "skipped": 0,
            "deleted_nodes": 0,
            "modified_formats": 0,
            "modified_pages": 0,
            "failed": 0
        }
        
        # 按优先级排序：先执行DELETE，再MODIFY_PAGE，最后MODIFY_FORMAT
        priority = {"DELETE": 1, "MODIFY_PAGE": 2, "MODIFY_FORMAT": 3, "ADD": 4}
        sorted_advice = sorted(
            verified_advice,
            key=lambda x: (priority.get(x.get("action", ""), 999), -x.get("verification", {}).get("confidence_adjusted", 0.5))
        )
        
        # 置信度映射：将字符串转为数值
        confidence_map = {"high": 0.9, "medium": 0.7, "low": 0.5}
        
        for i, advice in enumerate(sorted_advice, 1):
            action = advice.get("action", "")
            node_id = advice.get("node_id", advice.get("parent_id"))
            verification = advice.get("verification", {})
            
            # 如果没有verification key（PDF验证被跳过），使用advice自带的confidence
            if not verification:
                conf_raw = advice.get("confidence", "high")
                # 转换字符串confidence为数值
                if isinstance(conf_raw, str):
                    confidence = confidence_map.get(conf_raw.lower(), 0.5)
                else:
                    confidence = conf_raw
                verified = True  # 没有PDF验证时，假设已验证
            else:
                confidence = verification.get("confidence_adjusted", 0.0)
                verified = verification.get("verified", False)
            
            if self.debug:
                print(f"\n[{i}/{len(sorted_advice)}] Processing {action} for node {node_id}")
                print(f"  Confidence: {confidence:.2f}, Verified: {verified}")
            
            # 检查是否应该执行
            should_execute = verified and confidence >= confidence_threshold
            
            if not should_execute:
                self.execution_log.append({
                    "action": action,
                    "node_id": node_id,
                    "status": "skipped",
                    "reason": f"Confidence {confidence:.2f} < threshold {confidence_threshold}" if verified else "Not verified",
                    "details": advice
                })
                stats["skipped"] += 1
                
                if self.debug:
                    print(f"  ⏭️  Skipped: {'low confidence' if verified else 'not verified'}")
                continue
            
            # 执行建议
            try:
                if action == "DELETE":
                    success = self._execute_delete(updated_tree, advice)
                    if success:
                        stats["deleted_nodes"] += 1
                elif action == "MODIFY_FORMAT":
                    success = self._execute_modify_format(updated_tree, advice)
                    if success:
                        stats["modified_formats"] += 1
                elif action == "MODIFY_PAGE":
                    success = self._execute_modify_page(updated_tree, advice)
                    if success:
                        stats["modified_pages"] += 1
                elif action == "ADD":
                    # ADD操作需要更复杂的逻辑，暂时跳过
                    success = False
                    self.execution_log.append({
                        "action": action,
                        "node_id": node_id,
                        "status": "skipped",
                        "reason": "ADD operation not yet implemented",
                        "details": advice
                    })
                    stats["skipped"] += 1
                    if self.debug:
                        print(f"  ⏭️  Skipped: ADD not implemented")
                    continue
                else:
                    success = False
                
                if success:
                    stats["executed"] += 1
                    if self.debug:
                        print(f"  ✅ Executed successfully")
                else:
                    stats["failed"] += 1
                    if self.debug:
                        print(f"  ❌ Execution failed")
                
            except Exception as e:
                self.execution_log.append({
                    "action": action,
                    "node_id": node_id,
                    "status": "failed",
                    "reason": f"Exception: {str(e)}",
                    "details": advice
                })
                stats["failed"] += 1
                
                if self.debug:
                    print(f"  ❌ Exception: {e}")
        
        if self.debug:
            print(f"\n[EXECUTOR] ✅ Execution complete")
            print(f"  Executed: {stats['executed']}/{stats['total_advice']}")
            print(f"  Deleted: {stats['deleted_nodes']}, Modified Format: {stats['modified_formats']}, Modified Page: {stats['modified_pages']}")
            print("="*60 + "\n")
        
        return {
            "tree": updated_tree,
            "execution_log": self.execution_log,
            "summary": stats
        }
    
    def _execute_delete(self, tree: Dict, advice: Dict) -> bool:
        """执行DELETE操作"""
        node_id = advice.get("node_id")
        
        def delete_node(parent, children_key):
            """从父节点中删除指定子节点"""
            children = parent.get(children_key, [])
            for i, child in enumerate(children):
                child_id = child.get("id", child.get("node_id"))
                if child_id == node_id:
                    # 找到目标节点，删除
                    deleted = children.pop(i)
                    # 安全获取reason（可能没有verification key）
                    verification = advice.get("verification", {})
                    reason = verification.get("notes", advice.get("reason", "Deleted as advised"))
                    
                    self.execution_log.append({
                        "action": "DELETE",
                        "node_id": node_id,
                        "status": "executed",
                        "reason": reason,
                        "details": {
                            "deleted_title": deleted.get("title", ""),
                            "deleted_pages": [deleted.get("page_start"), deleted.get("page_end")]
                        }
                    })
                    return True
                
                # 递归搜索子节点
                if delete_node(child, "children") or delete_node(child, "nodes"):
                    return True
            
            return False
        
        # 从根节点开始删除
        if delete_node(tree, "children") or delete_node(tree, "structure"):
            return True
        
        # 如果没找到，记录失败
        self.execution_log.append({
            "action": "DELETE",
            "node_id": node_id,
            "status": "failed",
            "reason": "Node not found in tree",
            "details": advice
        })
        return False
    
    def _execute_modify_format(self, tree: Dict, advice: Dict) -> bool:
        """执行MODIFY_FORMAT操作"""
        node_id = advice.get("node_id")
        suggested_format = advice.get("suggested_format", "")
        
        if not suggested_format:
            self.execution_log.append({
                "action": "MODIFY_FORMAT",
                "node_id": node_id,
                "status": "failed",
                "reason": "No suggested format provided",
                "details": advice
            })
            return False
        
        node = self._find_node(tree, node_id)
        if not node:
            self.execution_log.append({
                "action": "MODIFY_FORMAT",
                "node_id": node_id,
                "status": "failed",
                "reason": "Node not found",
                "details": advice
            })
            return False
        
        old_title = node.get("title", "")
        node["title"] = suggested_format
        
        # 安全获取reason（可能没有verification key）
        verification = advice.get("verification", {})
        reason = verification.get("notes", advice.get("reason", "Format modified"))
        
        self.execution_log.append({
            "action": "MODIFY_FORMAT",
            "node_id": node_id,
            "status": "executed",
            "reason": reason,
            "details": {
                "from": old_title,
                "to": suggested_format
            }
        })
        return True
    
    def _execute_modify_page(self, tree: Dict, advice: Dict) -> bool:
        """执行MODIFY_PAGE操作"""
        node_id = advice.get("node_id")
        suggested_pages = advice.get("suggested_pages", [])
        
        if len(suggested_pages) != 2:
            self.execution_log.append({
                "action": "MODIFY_PAGE",
                "node_id": node_id,
                "status": "failed",
                "reason": "Invalid suggested page range",
                "details": advice
            })
            return False
        
        node = self._find_node(tree, node_id)
        if not node:
            self.execution_log.append({
                "action": "MODIFY_PAGE",
                "node_id": node_id,
                "status": "failed",
                "reason": "Node not found",
                "details": advice
            })
            return False
        
        old_pages = [
            node.get("page_start", node.get("start_index")),
            node.get("page_end", node.get("end_index"))
        ]
        
        # 更新页码
        if "page_start" in node:
            node["page_start"] = suggested_pages[0]
            node["page_end"] = suggested_pages[1]
        elif "start_index" in node:
            node["start_index"] = suggested_pages[0]
            node["end_index"] = suggested_pages[1]
        
        # 安全获取reason（可能没有verification key）
        verification = advice.get("verification", {})
        reason = verification.get("notes", advice.get("reason", "Page range corrected"))
        
        self.execution_log.append({
            "action": "MODIFY_PAGE",
            "node_id": node_id,
            "status": "executed",
            "reason": reason,
            "details": {
                "from": old_pages,
                "to": suggested_pages
            }
        })
        return True
    
    def _find_node(self, tree: Dict, node_id: str) -> Optional[Dict]:
        """在树中查找节点（返回引用，可以直接修改）"""
        def search(node):
            if node.get("id") == node_id or node.get("node_id") == node_id:
                return node
            
            for child in node.get("children", node.get("nodes", [])):
                result = search(child)
                if result:
                    return result
            
            return None
        
        structure = tree.get("children", tree.get("structure", []))
        for root in structure:
            result = search(root)
            if result:
                return result
        
        return None
