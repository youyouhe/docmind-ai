"""
EXPAND 操作执行器
Expand Executor for Re-analyzing Page Ranges

当检测到页码跨度过大的节点时，重新分析该区间的 PDF 内容，
生成更细粒度的子结构。
"""

from typing import Dict, List, Any, Optional
import json
import uuid
from ..core.llm_client import LLMClient


class ExpandExecutor:
    """
    EXPAND 操作执行器
    
    功能：
    1. 提取指定页码范围的 PDF 内容
    2. 使用 LLM 重新分析内容结构
    3. 生成细粒度的子节点
    4. 插入到树结构中
    """
    
    def __init__(self, llm: LLMClient, pdf_path: Optional[str] = None, debug: bool = False):
        """
        初始化 EXPAND 执行器
        
        Args:
            llm: LLM 客户端
            pdf_path: PDF 文件路径
            debug: 是否开启调试模式
        """
        self.llm = llm
        self.pdf_path = pdf_path
        self.debug = debug
        self.execution_log = []
    
    async def execute_expand(
        self,
        tree: Dict[str, Any],
        suggestion: Dict[str, Any]
    ) -> tuple[bool, str]:
        """
        执行 EXPAND 操作
        
        Args:
            tree: 树结构
            suggestion: EXPAND 建议
                {
                    "action": "EXPAND",
                    "node_id": "第二章",
                    "node_info": {
                        "page_range": [5, 50],
                        "target_depth": 3,
                        "expected_children": "5-10"
                    }
                }
        
        Returns:
            (success, message): 成功标志和消息
        """
        if self.debug:
            print(f"\n[EXPAND] 开始执行扩展操作")
            print(f"  节点ID: {suggestion.get('node_id')}")
        
        # 查找目标节点
        node = self._find_node(tree, suggestion.get("node_id", ""))
        if not node:
            msg = f"节点 {suggestion.get('node_id')} 未找到"
            self._log_execution(suggestion, "failed", msg)
            return False, msg
        
        # 获取扩展参数
        node_info = suggestion.get("node_info", {})
        page_range = node_info.get("page_range", [
            node.get("page_start", 0),
            node.get("page_end", 0)
        ])
        target_depth = node_info.get("target_depth", 3)
        
        if self.debug:
            print(f"  页码范围: {page_range}")
            print(f"  目标深度: {target_depth}")
        
        # 检查 PDF 路径
        if not self.pdf_path:
            msg = "未提供 PDF 文件路径，无法执行 EXPAND 操作"
            self._log_execution(suggestion, "failed", msg)
            return False, msg
        
        try:
            # Step 1: 提取 PDF 内容
            if self.debug:
                print(f"[EXPAND] 步骤 1: 提取 PDF 内容 (页 {page_range[0]}-{page_range[1]})")
            
            content = self._extract_pdf_content(page_range[0], page_range[1])
            
            if not content or len(content.strip()) < 100:
                msg = f"PDF 内容提取失败或内容过少"
                self._log_execution(suggestion, "failed", msg)
                return False, msg
            
            if self.debug:
                print(f"  提取内容长度: {len(content)} 字符")
            
            # Step 2: 使用 LLM 重新分析结构
            if self.debug:
                print(f"[EXPAND] 步骤 2: LLM 重新分析结构")
            
            new_children = await self._re_analyze_structure(
                content=content,
                parent_title=node.get("title", ""),
                page_range=page_range,
                target_depth=target_depth
            )
            
            if not new_children:
                msg = "LLM 未能识别出子结构"
                self._log_execution(suggestion, "failed", msg)
                return False, msg
            
            if self.debug:
                print(f"  识别到 {len(new_children)} 个子节点")
            
            # Step 3: 插入新的子节点
            if self.debug:
                print(f"[EXPAND] 步骤 3: 插入子节点到树结构")
            
            node["children"] = new_children
            
            msg = f"成功扩展节点，生成 {len(new_children)} 个子节点"
            self._log_execution(suggestion, "executed", msg, {
                "children_count": len(new_children),
                "children_titles": [c.get("title", "") for c in new_children[:5]]  # 最多显示5个
            })
            
            if self.debug:
                print(f"[EXPAND] ✅ 扩展完成")
            
            return True, msg
        
        except Exception as e:
            msg = f"执行 EXPAND 时发生异常: {str(e)}"
            self._log_execution(suggestion, "failed", msg)
            if self.debug:
                print(f"[EXPAND] ❌ {msg}")
            return False, msg
    
    def _extract_pdf_content(self, start_page: int, end_page: int) -> str:
        """
        提取 PDF 指定页码范围的内容
        
        Args:
            start_page: 起始页码（1-based）
            end_page: 结束页码（1-based）
        
        Returns:
            提取的文本内容
        """
        try:
            import pymupdf  # PyMuPDF
            
            doc = pymupdf.open(self.pdf_path)
            content_parts = []
            
            # 限制提取范围，避免处理过多页面
            actual_end = min(end_page, start_page + 30)  # 最多提取30页
            
            for page_num in range(start_page - 1, actual_end):
                if page_num >= len(doc):
                    break
                
                page = doc[page_num]
                text = page.get_text()
                
                if text and text.strip():
                    content_parts.append(f"=== 第 {page_num + 1} 页 ===\n{text}")
            
            doc.close()
            return "\n\n".join(content_parts)
        
        except ImportError:
            if self.debug:
                print("  ⚠️ PyMuPDF 未安装，尝试使用 pypdf")
            
            # 备用方案：使用 pypdf
            try:
                from pypdf import PdfReader
                
                reader = PdfReader(self.pdf_path)
                content_parts = []
                
                actual_end = min(end_page, start_page + 30)
                
                for page_num in range(start_page - 1, actual_end):
                    if page_num >= len(reader.pages):
                        break
                    
                    page = reader.pages[page_num]
                    text = page.extract_text()
                    
                    if text and text.strip():
                        content_parts.append(f"=== 第 {page_num + 1} 页 ===\n{text}")
                
                return "\n\n".join(content_parts)
            
            except ImportError:
                raise Exception("需要安装 PyMuPDF (pymupdf) 或 pypdf 库来提取 PDF 内容")
        
        except Exception as e:
            raise Exception(f"提取 PDF 内容失败: {str(e)}")
    
    async def _re_analyze_structure(
        self,
        content: str,
        parent_title: str,
        page_range: List[int],
        target_depth: int
    ) -> List[Dict[str, Any]]:
        """
        使用 LLM 重新分析内容结构
        
        Args:
            content: PDF 提取的文本内容
            parent_title: 父节点标题
            page_range: 页码范围
            target_depth: 目标深度（期望解析的层级）
        
        Returns:
            新的子节点列表
        """
        # 限制内容长度，避免超过 LLM token 限制
        max_chars = 15000  # 约 5000 tokens
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n... (内容过长，已截断)"
        
        prompt = f"""你是一个专业的文档结构分析专家。现在需要分析以下内容的结构。

**父节点信息:**
- 标题: {parent_title}
- 页码范围: 第 {page_range[0]} 页到第 {page_range[1]} 页

**任务:**
识别该区间内的所有章节标题，包括：
- 二级标题（如 "2.1 总体架构"、"第一节 概述"）
- 三级标题（如 "2.1.1 技术选型"、"1.1.1 背景介绍"）
- 四级标题（如有）

**提取的内容:**
{content}

**输出要求:**
1. 识别所有标题（包括编号和文本）
2. 判断标题的层级（level: 2, 3, 4）
3. 估算每个标题的页码范围（基于内容中的"=== 第 X 页 ==="标记）
4. 按照在文档中出现的顺序排列

**输出格式 (JSON):**
{{
  "children": [
    {{
      "title": "2.1 总体架构",
      "level": 2,
      "page_start": 5,
      "page_end": 10
    }},
    {{
      "title": "2.2 核心模块设计",
      "level": 2,
      "page_start": 11,
      "page_end": 25,
      "children": [
        {{
          "title": "2.2.1 数据层",
          "level": 3,
          "page_start": 11,
          "page_end": 15
        }},
        {{
          "title": "2.2.2 业务层",
          "level": 3,
          "page_start": 16,
          "page_end": 20
        }}
      ]
    }}
  ]
}}

**注意事项:**
1. 只识别明确的标题，不要臆测不存在的标题
2. 页码必须在范围 [{page_range[0]}, {page_range[1]}] 内
3. 如果无法准确判断页码，可以估算但要合理
4. 保持标题的原始文本，不要修改
5. 如果某个二级标题下有三级标题，将它们嵌套在 children 字段中
"""
        
        try:
            # 调用 LLM
            response = await self.llm.generate(
                prompt=prompt,
                response_format="json_object"
            )
            
            # 解析响应
            result = json.loads(response)
            children = result.get("children", [])
            
            # 转换为标准节点格式
            return self._convert_to_nodes(children, page_range)
        
        except Exception as e:
            if self.debug:
                print(f"  ❌ LLM 分析失败: {str(e)}")
            return []
    
    def _convert_to_nodes(
        self,
        children: List[Dict],
        page_range: List[int]
    ) -> List[Dict[str, Any]]:
        """
        将 LLM 返回的结构转换为标准节点格式
        
        Args:
            children: LLM 返回的子节点列表
            page_range: 父节点的页码范围（用于验证）
        
        Returns:
            标准格式的节点列表
        """
        nodes = []
        
        for child in children:
            # 生成节点 ID
            node_id = f"expand_{uuid.uuid4().hex[:8]}"
            
            # 验证和修正页码
            page_start = child.get("page_start", page_range[0])
            page_end = child.get("page_end", page_range[1])
            
            # 确保页码在合理范围内
            page_start = max(page_start, page_range[0])
            page_end = min(page_end, page_range[1])
            page_end = max(page_end, page_start)  # end >= start
            
            node = {
                "id": node_id,
                "title": child.get("title", "未命名节点"),
                "page_start": page_start,
                "page_end": page_end,
                "children": []
            }
            
            # 递归处理子节点
            if "children" in child and child["children"]:
                node["children"] = self._convert_to_nodes(
                    child["children"],
                    [page_start, page_end]
                )
            
            nodes.append(node)
        
        return nodes
    
    def _find_node(self, tree: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
        """
        在树中查找节点（返回引用，可直接修改）
        
        Args:
            tree: 树结构
            node_id: 节点 ID
        
        Returns:
            找到的节点，如果未找到返回 None
        """
        def search(node):
            if node.get("id") == node_id or node.get("node_id") == node_id:
                return node
            
            for child in node.get("children", node.get("nodes", [])):
                result = search(child)
                if result:
                    return result
            
            return None
        
        # 从根节点开始搜索
        structure = tree.get("children", tree.get("structure", [tree]))
        
        for root in (structure if isinstance(structure, list) else [structure]):
            result = search(root)
            if result:
                return result
        
        return None
    
    def _log_execution(
        self,
        suggestion: Dict,
        status: str,
        reason: str,
        details: Optional[Dict] = None
    ):
        """记录执行日志"""
        self.execution_log.append({
            "action": "EXPAND",
            "node_id": suggestion.get("node_id"),
            "status": status,
            "reason": reason,
            "details": details or suggestion
        })
    
    def get_execution_log(self) -> List[Dict]:
        """获取执行日志"""
        return self.execution_log
