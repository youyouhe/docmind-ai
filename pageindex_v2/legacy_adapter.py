"""
Legacy Adapter for PageIndex V2
兼容老 pageindex API 的适配层

提供与老版本 page_index_main 完全相同的接口，确保下游系统无需修改即可使用新算法。

Usage:
    from pageindex_v2.legacy_adapter import page_index_main, config, ConfigLoader
    
    opt = ConfigLoader().load({"model": "gpt-4o-2024-11-20"})
    result = page_index_main("path/to/file.pdf", opt)
"""

import os
import asyncio
import time
from io import BytesIO
from typing import Dict, Any, Optional, Union
from types import SimpleNamespace


def config(**kwargs):
    """
    兼容老版本的 config 对象（SimpleNamespace）
    """
    return SimpleNamespace(**kwargs)


class ConfigLoader:
    """
    兼容老版本的 ConfigLoader
    加载默认配置并与用户配置合并
    """
    
    DEFAULT_CONFIG = {
        "model": "gpt-4o-2024-11-20",
        "toc_check_page_num": 20,
        "max_page_num_each_node": 10,
        "max_token_num_each_node": 20000,
        "if_add_node_id": "yes",
        "if_add_node_summary": "no",
        "if_add_doc_description": "no",
        "if_add_node_text": "no",
        "custom_prompt": None
    }
    
    def load(self, user_opt: Optional[Union[Dict, SimpleNamespace]] = None) -> SimpleNamespace:
        """
        加载配置，合并用户选项与默认值
        
        Args:
            user_opt: 用户配置（dict 或 SimpleNamespace）
            
        Returns:
            SimpleNamespace 配置对象
        """
        if user_opt is None:
            user_dict = {}
        elif isinstance(user_opt, SimpleNamespace):
            user_dict = vars(user_opt)
        elif isinstance(user_opt, dict):
            user_dict = user_opt
        else:
            raise TypeError("user_opt must be dict, SimpleNamespace or None")
        
        # 合并配置
        merged = {**self.DEFAULT_CONFIG, **user_dict}
        return config(**merged)


def page_index_main(doc: Union[str, BytesIO], opt: Optional[SimpleNamespace] = None) -> Dict[str, Any]:
    """
    主入口函数 - 兼容老版本 pageindex.page_index_main API
    
    Args:
        doc: PDF文件路径（str）或 BytesIO 对象
        opt: 配置对象（由 ConfigLoader 生成）
        
    Returns:
        兼容老格式的输出：
        {
          "result": {
            "doc_name": "xxx.pdf",
            "structure": [...]
          },
          "performance": {...}
        }
    """
    # 加载默认配置
    if opt is None:
        opt = ConfigLoader().load()
    
    # 转换配置到 ProcessingOptions
    options = _convert_old_opt_to_v2(opt)
    
    # 处理 BytesIO 输入
    pdf_path, temp_file = _prepare_pdf_input(doc)
    
    try:
        # 导入新算法（使用相对导入）
        from .main import PageIndexV2
        
        # 设置 document_id（用于 progress callback）
        _setup_progress_callback()
        
        # 调用新算法
        start_time = time.time()
        processor = PageIndexV2(options)
        
        # 包装进度报告
        _wrap_progress_reporting(processor)
        
        # 执行处理（异步转同步）
        v2_result = asyncio.run(processor.process_pdf(pdf_path))
        
        total_time = time.time() - start_time
        
        # 转换输出格式
        old_format = _convert_v2_to_old_format(v2_result, opt, total_time)
        
        # 后处理：添加 node_id, text, summary（根据配置）
        structure = old_format["result"]["structure"]
        
        if getattr(opt, 'if_add_node_id', 'yes') == 'yes':
            _add_node_ids(structure)
        
        if getattr(opt, 'if_add_node_text', 'no') == 'yes':
            _add_node_text(structure, pdf_path)
        
        if getattr(opt, 'if_add_node_summary', 'no') == 'yes':
            # Summary 需要 text，如果之前没加，临时加上
            needs_temp_text = getattr(opt, 'if_add_node_text', 'no') == 'no'
            if needs_temp_text:
                _add_node_text(structure, pdf_path)
            
            # 生成 summaries（异步）
            asyncio.run(_add_node_summaries(structure, getattr(opt, 'model', 'gpt-4o-2024-11-20')))
            
            # 移除临时 text
            if needs_temp_text:
                _remove_node_text(structure)
        
        return old_format
        
    finally:
        # 清理临时文件
        if temp_file:
            try:
                os.unlink(temp_file)
            except:
                pass


def _convert_old_opt_to_v2(opt: SimpleNamespace):
    """
    将老配置转换为新的 ProcessingOptions
    
    映射关系：
    - model: 直接映射
    - toc_check_page_num -> toc_check_pages
    - max_page_num_each_node -> max_pages_per_node
    - max_token_num_each_node -> max_tokens_per_node
    """
    from .main import ProcessingOptions
    
    # 确定 provider（根据 model 推断）
    model = getattr(opt, 'model', 'gpt-4o-2024-11-20')
    if 'deepseek' in model.lower():
        provider = 'deepseek'
    else:
        provider = 'openai'
    
    return ProcessingOptions(
        provider=provider,
        model=model,
        max_depth=4,  # 新算法固定为4层
        toc_check_pages=getattr(opt, 'toc_check_page_num', 20),
        debug=False,  # 关闭调试输出，避免干扰老系统日志
        progress=True,  # 保持进度输出
        output_dir="./results",
        enable_recursive_processing=True,
        skip_verification_for_large_pdf=True,
        large_pdf_threshold=200,
        max_pages_per_node=getattr(opt, 'max_page_num_each_node', 10),
        max_tokens_per_node=getattr(opt, 'max_token_num_each_node', 20000),
        max_verify_count=100,
        verification_concurrency=20
    )


def _prepare_pdf_input(doc: Union[str, BytesIO]) -> tuple:
    """
    处理 PDF 输入，支持文件路径和 BytesIO
    
    Returns:
        (pdf_path, temp_file_path)
        - pdf_path: 实际的文件路径
        - temp_file_path: 如果是 BytesIO，返回临时文件路径；否则返回 None
    """
    if isinstance(doc, BytesIO):
        # BytesIO 需要保存到临时文件
        import tempfile
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', mode='wb') as tmp:
            tmp.write(doc.getvalue())
            temp_path = tmp.name
        
        return temp_path, temp_path
    
    elif isinstance(doc, str):
        # 字符串路径
        if not os.path.isfile(doc):
            raise FileNotFoundError(f"PDF file not found: {doc}")
        return doc, None
    
    else:
        raise TypeError(f"Unsupported input type: {type(doc)}. Expected str or BytesIO.")


def _setup_progress_callback():
    """
    设置进度回调（兼容老系统的 progress_callback 模块）
    """
    try:
        from pageindex.progress_callback import get_document_id
        doc_id = get_document_id()
        # document_id 已通过 pageindex.progress_callback 设置
        return doc_id
    except ImportError:
        # progress_callback 模块不可用，跳过
        return None


def _wrap_progress_reporting(processor):
    """
    包装 PageIndexV2 的进度报告，转发到老系统的 progress_callback
    
    Args:
        processor: PageIndexV2 实例
    """
    try:
        from pageindex.progress_callback import report_progress, get_document_id
        
        doc_id = get_document_id()
        if not doc_id:
            return  # 没有 document_id，跳过
        
        # 保存原始函数
        original_log_progress = processor.log_progress
        
        def wrapped_log_progress(message: str, force: bool = False):
            """包装后的进度报告函数"""
            # 调用原始函数
            original_log_progress(message, force)
            
            # 解析消息提取阶段和进度
            stage, progress_pct, clean_msg = _parse_progress_message(message)
            
            if stage and progress_pct is not None:
                # 转发到老系统
                report_progress(doc_id, stage, progress=progress_pct, message=clean_msg)
        
        # 替换函数
        processor.log_progress = wrapped_log_progress
        
    except ImportError:
        # progress_callback 不可用，跳过
        pass


def _parse_progress_message(message: str) -> tuple:
    """
    解析进度消息，提取阶段名和进度百分比
    
    Args:
        message: 如 "📄 [1/6] PDF Parsing... (30 pages)"
        
    Returns:
        (stage, progress_percent, clean_message)
    """
    import re
    
    # 默认值
    stage = "processing"
    progress_pct = None
    clean_msg = message
    
    # 匹配模式: [X/Y]
    match = re.search(r'\[(\d+)/(\d+)\]', message)
    if match:
        current = int(match.group(1))
        total = int(match.group(2))
        # 映射到 0-100 的进度
        progress_pct = (current - 1) / total * 100
        
        # 提取阶段名
        stage_match = re.search(r'\[(\d+)/\d+\]\s*([^.]+)', message)
        if stage_match:
            stage_name = stage_match.group(2).strip()
            # 映射到老系统的阶段名
            stage_mapping = {
                'PDF Parsing': 'pdf_parsing',
                'TOC Detection': 'toc_detection',
                'Structure Extraction': 'toc_transformation',
                'Page Mapping': 'page_mapping',
                'Verification': 'toc_verification',
                'Tree Building': 'tree_building'
            }
            stage = stage_mapping.get(stage_name, 'processing')
    
    return stage, progress_pct, clean_msg


def _convert_v2_to_old_format(v2_result: Dict, opt: SimpleNamespace, total_time: float) -> Dict[str, Any]:
    """
    转换新算法输出为老格式
    
    Args:
        v2_result: 新算法的输出
        opt: 配置对象
        total_time: 总处理时间
        
    Returns:
        老格式输出：
        {
          "result": {
            "doc_name": "...",
            "structure": [...]
          },
          "performance": {...}
        }
    """
    # 提取基本信息
    doc_name = v2_result.get("source_file", "unknown.pdf")
    structure = v2_result.get("structure", [])
    stats = v2_result.get("statistics", {})
    
    # 根据配置添加 doc_description（如果需要）
    result_dict = {
        "doc_name": doc_name,
        "structure": structure
    }
    
    if getattr(opt, 'if_add_doc_description', 'no') == 'yes' and v2_result.get("doc_description"):
        result_dict["doc_description"] = v2_result.get("doc_description")
    
    # 构造性能数据（兼容老格式）
    performance = {
        "total_time": total_time,
        "tree_building": {
            "duration": total_time * 0.7,  # 估算：树构建占70%
            "items_processed": stats.get("total_nodes", 0)
        },
        "toc_detection": {
            "duration": total_time * 0.1,  # 估算：TOC检测占10%
        },
        "toc_transformation": {
            "duration": total_time * 0.1,  # 估算：转换占10%
        },
        "verification": {
            "duration": total_time * 0.1,  # 估算：验证占10%
            "accuracy": v2_result.get("verification_accuracy", 1.0)
        },
        "summary": {
            "total_nodes": stats.get("total_nodes", 0),
            "max_depth": stats.get("max_depth", 0),
            "root_nodes": stats.get("root_nodes", 0),
            "mapping_accuracy": v2_result.get("mapping_validation_accuracy", 1.0),
            "verification_accuracy": v2_result.get("verification_accuracy", 1.0)
        }
    }
    
    # 返回兼容格式
    return {
        "result": result_dict,
        "performance": performance
    }


# ============================================================================
# 辅助函数：添加 node_id, text, summary
# ============================================================================

def _add_node_ids(structure: list, node_id: int = 0):
    """
    递归添加 node_id（格式：0000, 0001, 0002...）
    
    Args:
        structure: 树结构（列表）
        node_id: 当前节点ID计数器
    """
    for item in structure:
        item['node_id'] = str(node_id).zfill(4)
        node_id += 1
        
        if 'nodes' in item and item['nodes']:
            node_id = _add_node_ids(item['nodes'], node_id)
    
    return node_id


def _add_node_text(structure: list, pdf_path: str):
    """
    添加节点文本内容
    
    策略：
    - 叶子节点：添加截断的内容（前500字符）
    - 父节点：不添加内容（使用 summary 替代）
    
    Args:
        structure: 树结构
        pdf_path: PDF文件路径
    """
    import fitz  # PyMuPDF
    
    # 打开PDF
    doc = fitz.open(pdf_path)
    
    def extract_text_from_pages(start: int, end: int) -> str:
        """提取指定页面范围的文本"""
        text_parts = []
        for page_num in range(start - 1, min(end, len(doc))):
            if page_num >= 0:
                page = doc[page_num]
                text_parts.append(page.get_text())
        return "\n".join(text_parts)
    
    def add_text_recursive(node):
        """递归添加文本"""
        has_children = 'nodes' in node and node['nodes']
        
        if not has_children:
            # 叶子节点：添加文本
            start = node.get('start_index', 1)
            end = node.get('end_index', 1)
            full_text = extract_text_from_pages(start, end)
            # 截断到500字符
            node['text'] = full_text[:500] if len(full_text) > 500 else full_text
        else:
            # 父节点：空文本
            node['text'] = ""
            
            # 递归处理子节点
            for child in node['nodes']:
                add_text_recursive(child)
    
    # 处理所有根节点
    for root in structure:
        add_text_recursive(root)
    
    doc.close()


async def _add_node_summaries(structure: list, model: str):
    """
    异步生成节点摘要
    
    Args:
        structure: 树结构
        model: LLM模型名称
    """
    from .core.llm_client import LLMClient
    
    # 初始化 LLM client
    if 'deepseek' in model.lower():
        provider = 'deepseek'
    else:
        provider = 'openai'
    
    llm = LLMClient(provider=provider, model=model, debug=False)
    
    async def generate_summary(node):
        """为单个节点生成摘要"""
        text = node.get('text', '')
        title = node.get('title', '')
        
        if not text or len(text.strip()) < 10:
            node['summary'] = ""
            return
        
        # 截断文本（避免token超限）
        truncated_text = text[:3000]
        
        prompt = f"""Summarize the following section from a document in 1-2 sentences.

Section Title: {title}

Content:
{truncated_text}

Provide a concise summary that captures the main points."""
        
        try:
            summary = await llm.chat(prompt)
            node['summary'] = summary.strip() if summary else ""
        except Exception as e:
            print(f"Error generating summary for '{title}': {e}")
            node['summary'] = ""
    
    async def process_node_recursive(node):
        """递归处理节点"""
        # 为当前节点生成摘要
        await generate_summary(node)
        
        # 递归处理子节点
        if 'nodes' in node and node['nodes']:
            tasks = [process_node_recursive(child) for child in node['nodes']]
            await asyncio.gather(*tasks)
    
    # 并发处理所有根节点
    tasks = [process_node_recursive(root) for root in structure]
    await asyncio.gather(*tasks)


def _remove_node_text(structure: list):
    """
    递归移除节点的 text 字段
    
    Args:
        structure: 树结构
    """
    for node in structure:
        if 'text' in node:
            del node['text']
        
        if 'nodes' in node and node['nodes']:
            _remove_node_text(node['nodes'])


# ============================================================================
# 导出接口（与老版本 pageindex 完全一致）
# ============================================================================

__all__ = [
    'page_index_main',
    'config',
    'ConfigLoader',
]
