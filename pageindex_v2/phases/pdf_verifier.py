"""
PDF核实器 - 回到原文验证审核建议
PDF Verifier - Verify audit advice against original PDF

通过读取PDF原文，验证LLM提出的审核建议是否准确
"""

from typing import Dict, List, Any, Optional, Tuple
from ..core.pdf_parser import PDFParser


class PDFVerifier:
    """
    PDF核实器
    
    功能：
    1. 根据页码读取PDF原文
    2. 验证标题是否真实存在
    3. 验证页码范围是否准确
    4. 为ADD建议提供依据
    """
    
    def __init__(self, pdf_path: str, debug: bool = False):
        self.pdf_path = pdf_path
        self.debug = debug
        self.parser = PDFParser(pdf_path)
        self.page_cache = {}  # 缓存已读取的页面
    
    async def verify_advice(
        self,
        advice_list: List[Dict],
        tree: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证审核建议
        
        Args:
            advice_list: LLM提供的审核建议列表
            tree: 当前的树结构
        
        Returns:
            {
                "verified_advice": [
                    {
                        ...原建议内容...,
                        "verification": {
                            "verified": True/False,
                            "evidence": "PDF原文摘录",
                            "confidence_adjusted": 0.9,
                            "notes": "验证说明"
                        }
                    }
                ],
                "summary": {
                    "total": 10,
                    "verified": 8,
                    "rejected": 2,
                    "verification_rate": 0.8
                }
            }
        """
        if self.debug:
            print("\n" + "="*60)
            print("[VERIFIER] Verifying advice against PDF")
            print(f"[VERIFIER] Total advice to verify: {len(advice_list)}")
            print("="*60)
        
        verified_list = []
        verified_count = 0
        rejected_count = 0
        
        for i, advice in enumerate(advice_list, 1):
            action = advice.get("action", "")
            
            if self.debug:
                print(f"\n[{i}/{len(advice_list)}] Verifying {action} for node {advice.get('node_id', 'N/A')}")
            
            # 根据不同的action类型进行验证
            if action == "DELETE":
                verification = await self._verify_delete(advice, tree)
            elif action == "MODIFY_FORMAT":
                verification = await self._verify_modify_format(advice, tree)
            elif action == "MODIFY_PAGE":
                verification = await self._verify_modify_page(advice, tree)
            elif action == "ADD":
                verification = await self._verify_add(advice, tree)
            else:
                verification = {
                    "verified": False,
                    "evidence": "",
                    "confidence_adjusted": 0.0,
                    "notes": f"Unknown action: {action}"
                }
            
            verified_advice = {**advice, "verification": verification}
            verified_list.append(verified_advice)
            
            if verification["verified"]:
                verified_count += 1
            else:
                rejected_count += 1
            
            if self.debug:
                status = "✅" if verification["verified"] else "❌"
                print(f"  {status} Verified: {verification['verified']}")
                print(f"  Confidence: {verification['confidence_adjusted']:.2f}")
        
        summary = {
            "total": len(advice_list),
            "verified": verified_count,
            "rejected": rejected_count,
            "verification_rate": verified_count / len(advice_list) if advice_list else 0
        }
        
        if self.debug:
            print(f"\n[VERIFIER] ✅ Verification complete")
            print(f"  Verified: {verified_count}/{len(advice_list)}")
            print(f"  Rate: {summary['verification_rate']:.1%}")
            print("="*60 + "\n")
        
        return {
            "verified_advice": verified_list,
            "summary": summary
        }
    
    async def _verify_delete(self, advice: Dict, tree: Dict) -> Dict:
        """验证DELETE建议"""
        node_id = advice.get("node_id")
        node = self._find_node_by_id(tree, node_id)
        
        if not node:
            return {
                "verified": False,
                "evidence": "",
                "confidence_adjusted": 0.0,
                "notes": "Node not found in tree"
            }
        
        title = node.get("title", "")
        page_start = node.get("page_start", node.get("start_index", 1))
        
        # 读取该标题所在页的内容
        page_text = await self._get_page_text(page_start)
        
        # 检查1: 标题是否太长（超过80字符，很可能是正文）
        is_too_long = len(title) > 80
        
        # 检查2: 标题是否包含多个句子（包含2个以上句号）
        has_multiple_sentences = title.count('。') >= 2 or title.count('.') >= 2
        
        # 检查3: 标题是否在PDF中以正文形式出现（不在页首）
        title_in_page = title[:30] in page_text  # 检查标题前30字符
        is_at_page_start = page_text.find(title[:30]) < 100 if title_in_page else False
        
        # 检查4: 标题是否以编号开头（如"1、"、"（一）"等）
        has_numbering = bool(
            title.startswith(('一、', '二、', '三、', '四、', '五、', '六、', '七、', '八、', '九、', '十、')) or
            title.startswith(('（一）', '（二）', '（三）', '（四）', '（五）')) or
            title.startswith(('1、', '2、', '3、', '4、', '5、', '6、', '7、', '8、', '9、'))
        )
        
        # 综合判断
        should_delete = False
        confidence = float(advice.get("confidence", "medium") == "high") * 0.5 + 0.3
        evidence_parts = []
        
        if is_too_long:
            should_delete = True
            confidence += 0.2
            evidence_parts.append(f"标题过长({len(title)}字)")
        
        if has_multiple_sentences:
            should_delete = True
            confidence += 0.2
            evidence_parts.append("包含多个句子")
        
        if title_in_page and not is_at_page_start:
            should_delete = True
            confidence += 0.1
            evidence_parts.append("在PDF中位于正文位置")
        
        if has_numbering and len(title) > 50:
            # 有编号但很长，可能是条款内容
            should_delete = True
            confidence += 0.1
            evidence_parts.append("编号+长文本，疑似条款")
        
        # 调整置信度（最高0.95）
        confidence = min(0.95, confidence)
        
        # 提取证据（标题前后的文本）
        if title_in_page:
            idx = page_text.find(title[:30])
            evidence = page_text[max(0, idx-50):idx+len(title)+50]
        else:
            evidence = page_text[:200]
        
        return {
            "verified": should_delete,
            "evidence": evidence,
            "confidence_adjusted": confidence,
            "notes": "; ".join(evidence_parts) if evidence_parts else "标题格式正常，建议保留"
        }
    
    async def _verify_modify_format(self, advice: Dict, tree: Dict) -> Dict:
        """验证MODIFY_FORMAT建议"""
        node_id = advice.get("node_id")
        node = self._find_node_by_id(tree, node_id)
        
        if not node:
            return {
                "verified": False,
                "evidence": "",
                "confidence_adjusted": 0.0,
                "notes": "Node not found"
            }
        
        current_title = advice.get("current_title", node.get("title", ""))
        suggested_format = advice.get("suggested_format", "")
        page_start = node.get("page_start", node.get("start_index", 1))
        
        # 读取PDF原文
        page_text = await self._get_page_text(page_start)
        
        # 检查当前标题是否在PDF中
        current_in_pdf = current_title[:20] in page_text
        
        # 检查建议格式是否更合理
        # 例如：将"1.1 背景"改为"（一）背景"
        # 验证逻辑：建议的格式是否保持了标题的核心内容
        
        # 提取核心内容（去掉编号）
        import re
        current_core = re.sub(r'^[\d\.\、（）一二三四五六七八九十]+\s*', '', current_title)
        suggested_core = re.sub(r'^[\d\.\、（）一二三四五六七八九十]+\s*', '', suggested_format)
        
        # 核心内容应该一致
        core_matches = current_core == suggested_core
        
        # 检查是否只是格式调整（去掉标点等）
        is_format_only = (
            current_title.rstrip('。，、；：') == suggested_format or
            core_matches
        )
        
        confidence = 0.7 if is_format_only else 0.4
        
        return {
            "verified": is_format_only,
            "evidence": page_text[:200] if current_in_pdf else "",
            "confidence_adjusted": confidence,
            "notes": "格式调整合理" if is_format_only else "建议的格式改变了标题内容，不采纳"
        }
    
    async def _verify_modify_page(self, advice: Dict, tree: Dict) -> Dict:
        """验证MODIFY_PAGE建议"""
        node_id = advice.get("node_id")
        node = self._find_node_by_id(tree, node_id)
        
        if not node:
            return {
                "verified": False,
                "evidence": "",
                "confidence_adjusted": 0.0,
                "notes": "Node not found"
            }
        
        current_pages = advice.get("current_pages", [])
        suggested_pages = advice.get("suggested_pages", [])
        
        if len(current_pages) != 2 or len(suggested_pages) != 2:
            return {
                "verified": False,
                "evidence": "",
                "confidence_adjusted": 0.0,
                "notes": "Invalid page range format"
            }
        
        current_span = current_pages[1] - current_pages[0] + 1
        suggested_span = suggested_pages[1] - suggested_pages[0] + 1
        
        # 读取建议页码范围的内容
        start_page_text = await self._get_page_text(suggested_pages[0])
        end_page_text = await self._get_page_text(suggested_pages[1])
        
        # 简单验证：检查建议的页码范围是否合理
        # （这里可以加入更复杂的逻辑，比如检查是否有新的章节标题出现）
        
        title = node.get("title", "")
        title_in_start = title[:20] in start_page_text
        
        # 页码调整是否合理：
        # 1. 如果当前跨度太大（>15页），建议缩小是合理的
        # 2. 建议的起始页应该包含标题
        
        is_reasonable = (
            (current_span > 15 and suggested_span < current_span) or
            (current_span < 3 and suggested_span > current_span)
        ) and title_in_start
        
        confidence = 0.6 if is_reasonable else 0.3
        
        return {
            "verified": is_reasonable,
            "evidence": start_page_text[:200],
            "confidence_adjusted": confidence,
            "notes": f"页码调整{'合理' if is_reasonable else '需要更多证据'}（{current_span}页 → {suggested_span}页）"
        }
    
    async def _verify_add(self, advice: Dict, tree: Dict) -> Dict:
        """验证ADD建议"""
        suggested_title = advice.get("suggested_title", "")
        suggested_pages = advice.get("suggested_pages", [])
        
        if len(suggested_pages) != 2:
            return {
                "verified": False,
                "evidence": "",
                "confidence_adjusted": 0.0,
                "notes": "Invalid page range"
            }
        
        # 读取建议页码的内容
        page_text = await self._get_page_text(suggested_pages[0])
        
        # 检查建议的标题是否在PDF中出现
        title_exists = suggested_title[:15] in page_text
        
        # 对于ADD操作，保守处理（置信度不高则不采纳）
        confidence = 0.8 if title_exists else 0.2
        
        return {
            "verified": title_exists,
            "evidence": page_text[:200] if title_exists else "",
            "confidence_adjusted": confidence,
            "notes": f"{'在PDF中找到该标题' if title_exists else '未在PDF中找到该标题'}"
        }
    
    async def _get_page_text(self, page_num: int) -> str:
        """获取指定页面的文本（带缓存）"""
        if page_num in self.page_cache:
            return self.page_cache[page_num]
        
        try:
            # 使用PDF Parser读取页面
            page_text = self.parser.get_page_text(page_num - 1)  # 0-based index
            self.page_cache[page_num] = page_text
            return page_text
        except Exception as e:
            if self.debug:
                print(f"  ⚠ Failed to read page {page_num}: {e}")
            return ""
    
    def _find_node_by_id(self, tree: Dict, node_id: str) -> Optional[Dict]:
        """在树中查找指定ID的节点"""
        def search(node):
            if node.get("id") == node_id or node.get("node_id") == node_id:
                return node
            
            for child in node.get("children", node.get("nodes", [])):
                result = search(child)
                if result:
                    return result
            
            return None
        
        # 从根节点开始搜索
        structure = tree.get("children", tree.get("structure", []))
        for root in structure:
            result = search(root)
            if result:
                return result
        
        return None
