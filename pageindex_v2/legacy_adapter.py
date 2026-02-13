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
        doc_id = _setup_progress_callback()
        
        # 调用新算法
        start_time = time.time()
        processor = PageIndexV2(options, document_id=doc_id)
        
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
    
    # 确定 provider（根据 model 推断或从环境变量读取）
    import os
    model = getattr(opt, 'model', 'gpt-4o-2024-11-20')
    model_lower = model.lower()

    # 根据 model 名称识别 provider
    if 'deepseek' in model_lower:
        provider = 'deepseek'
    elif 'openrouter' in model_lower or any(x in model_lower for x in ['arcee-ai', 'mimo', 'xiaomi']):
        provider = 'openrouter'
    elif 'gemini' in model_lower:
        provider = 'gemini'
    elif 'glm' in model_lower or 'zhipu' in model_lower:
        provider = 'zhipu'
    else:
        # 默认从环境变量读取
        provider = os.getenv('LLM_PROVIDER', 'deepseek')
    
    return ProcessingOptions(
        provider=provider,
        model=model,
        max_depth=4,  # 新算法固定为4层
        toc_check_pages=getattr(opt, 'toc_check_page_num', 20),
        debug=getattr(opt, 'debug', False),  # 由调用方控制调试输出
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

def _add_node_ids(structure: list, node_id: int = 0, use_hierarchical: bool = True):
    """
    递归添加 node_id

    Args:
        structure: 树结构（列表）
        node_id: 当前节点ID计数器（仅用于顺序模式）
        use_hierarchical: 是否使用多级编号 (1, 1.1, 1.1.1)
                          False 则使用顺序编号 (0000, 0001, 0002)
    """
    if use_hierarchical:
        # Use the hierarchical numbering from helpers.py
        from .utils.helpers import add_node_ids
        add_node_ids(structure, use_hierarchical=True)
        # Return a dummy value (not used in hierarchical mode)
        return 0
    else:
        # Original sequential numbering
        for item in structure:
            item['node_id'] = str(node_id).zfill(4)
            node_id += 1

            if 'nodes' in item and item['nodes']:
                node_id = _add_node_ids(item['nodes'], node_id, use_hierarchical=False)

        return node_id


def _find_title_in_text(text: str, title: str) -> int:
    """
    在页面文本中查找标题位置，支持多种匹配策略。

    策略优先级：
    1. 精确匹配
    2. 去除空白差异后匹配
    3. 去除编号前缀后匹配核心内容
    4. 标题前缀匹配（前8个有效字符）

    Args:
        text: 页面文本
        title: 节点标题

    Returns:
        标题在文本中的起始位置，未找到返回 -1
    """
    import re

    if not text or not title:
        return -1

    title = title.strip()

    # 策略1：精确匹配
    pos = text.find(title)
    if pos >= 0:
        return pos

    # 策略2：规范化空白后匹配（将连续空白替换为单空格）
    normalized_title = re.sub(r'\s+', ' ', title).strip()
    if normalized_title != title:
        pos = text.find(normalized_title)
        if pos >= 0:
            return pos

    # 策略3：去除常见编号前缀后匹配核心内容
    # 匹配：（一）、（二）、(1)、(2)、1.、1、第X章、第X节 等
    core_patterns = [
        r'^[（(]\s*[一二三四五六七八九十百零\d]+\s*[）)]\s*',  # （一）、(1)
        r'^第[一二三四五六七八九十百零\d]+[章节部分条款]\s*',    # 第一章、第1节
        r'^[一二三四五六七八九十]+\s*[、．.]\s*',              # 一、二、
        r'^\d+\s*[、．.]\s*',                                 # 1、2.
        r'^\d+(\.\d+)*\s+',                                   # 1.1 、1.1.1
        r'^[A-Z]\s*[、．.]\s*',                                # A、B.
    ]

    for pattern in core_patterns:
        core = re.sub(pattern, '', title).strip()
        if core and len(core) >= 2 and core != title:
            pos = text.find(core)
            if pos >= 0:
                # 回退查找：在 core 之前可能有编号前缀，向前搜索一行
                line_start = text.rfind('\n', max(0, pos - 50), pos)
                if line_start >= 0:
                    return line_start + 1  # +1 跳过 \n
                return max(0, pos - 30)  # 粗略回退到可能的行首

    # 策略4：标题前缀匹配（取前8个有效字符）
    if len(title) > 4:
        prefix = title[:min(8, len(title))]
        pos = text.find(prefix)
        if pos >= 0:
            return pos

    return -1


def _extract_section_text(
    node_title: str,
    next_sibling_title: str,
    start_page: int,
    end_page: int,
    get_page_fn,
    max_chars: int = 2000
) -> str:
    """
    提取节点的段落级文本，在共享页面上根据标题位置切分。

    Args:
        node_title: 当前节点标题
        next_sibling_title: 下一个兄弟节点标题（用于确定结束边界），可为 None
        start_page: 起始页码（1-indexed）
        end_page: 结束页码（1-indexed）
        get_page_fn: 获取页面文本的函数 (page_num) -> str
        max_chars: 最大字符数限制

    Returns:
        提取的文本内容
    """
    text_parts = []

    for page_num in range(start_page, end_page + 1):
        page_text = get_page_fn(page_num)
        if not page_text:
            continue

        # 在起始页：从当前标题位置开始
        if page_num == start_page and node_title:
            title_pos = _find_title_in_text(page_text, node_title)
            if title_pos > 0:
                page_text = page_text[title_pos:]

        # 在结束页：在下一个兄弟标题位置截断
        if page_num == end_page and next_sibling_title:
            next_pos = _find_title_in_text(page_text, next_sibling_title)
            if next_pos > 0:
                page_text = page_text[:next_pos]

        stripped = page_text.strip()
        if stripped:
            text_parts.append(stripped)

    full_text = "\n".join(text_parts)

    # 截断到 max_chars
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars]

    return full_text


def _add_node_text(structure: list, pdf_path: str):
    """
    添加节点文本内容（段落级切分版本）

    改进策略：
    - 同页多节点：根据标题位置在页面文本内切分，每个节点只拿到自己的段落
    - 跨页节点：起始页从标题处开始，结束页在下一节标题处截断
    - 父节点：不添加内容（使用 summary 替代）
    - 文本上限提升到 2000 字符

    Args:
        structure: 树结构
        pdf_path: PDF文件路径
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)

    # 缓存页面文本，避免重复提取
    page_cache = {}

    def get_page_text(page_num: int) -> str:
        """获取指定页码的文本（带缓存，1-indexed）"""
        if page_num not in page_cache:
            idx = page_num - 1
            if 0 <= idx < len(doc):
                page_cache[page_num] = doc[idx].get_text()
            else:
                page_cache[page_num] = ""
        return page_cache[page_num]

    def process_siblings(siblings: list):
        """处理一组兄弟节点，利用兄弟信息做段落级切分"""
        for i, node in enumerate(siblings):
            has_children = 'nodes' in node and node['nodes']

            if has_children:
                # 父节点：空文本，递归处理子节点
                node['text'] = ""
                process_siblings(node['nodes'])
            else:
                # 叶子节点：提取段落级文本
                start = node.get('start_index', 1)
                end = node.get('end_index', start)

                # 确定下一个兄弟节点的标题（用于结束边界检测）
                next_sibling_title = None
                if i + 1 < len(siblings):
                    next_sib = siblings[i + 1]
                    next_sib_start = next_sib.get('start_index', end + 1)
                    # 只有当下一个兄弟的起始页在当前节点的结束页范围内时才需要切分
                    if next_sib_start <= end:
                        next_sibling_title = next_sib.get('title', '')

                node['text'] = _extract_section_text(
                    node_title=node.get('title', ''),
                    next_sibling_title=next_sibling_title,
                    start_page=start,
                    end_page=end,
                    get_page_fn=get_page_text,
                    max_chars=2000
                )

    # 根节点本身就是一组兄弟
    process_siblings(structure)

    doc.close()


async def _add_node_summaries(structure: list, model: str):
    """
    异步生成节点摘要
    
    Args:
        structure: 树结构
        model: LLM模型名称
    """
    from .core.llm_client import LLMClient
    
    # 初始化 LLM client - 根据 model 名称识别 provider
    model_lower = model.lower()
    if 'deepseek' in model_lower:
        provider = 'deepseek'
    elif 'openrouter' in model_lower or any(x in model_lower for x in ['arcee-ai', 'mimo', 'xiaomi']):
        provider = 'openrouter'
    elif 'gemini' in model_lower:
        provider = 'gemini'
    elif 'glm' in model_lower or 'zhipu' in model_lower:
        provider = 'zhipu'
    else:
        # 默认从环境变量读取
        import os
        provider = os.getenv('LLM_PROVIDER', 'deepseek')

    llm = LLMClient(provider=provider, model=model, debug=False)
    
    def _detect_language(text: str) -> str:
        """检测文本主要语言：'zh' 或 'en'"""
        import re
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text[:500]))
        total_alpha = len(re.findall(r'[a-zA-Z]', text[:500]))
        return 'zh' if chinese_chars > total_alpha else 'en'

    # 检测文档语言（取第一个有文本的叶子节点）
    doc_lang = 'en'
    def _find_first_text(nodes):
        for n in nodes:
            t = n.get('text', '')
            if t and len(t.strip()) > 20:
                return t
            children = n.get('nodes', [])
            if children:
                result = _find_first_text(children)
                if result:
                    return result
        return None

    sample_text = _find_first_text(structure)
    if sample_text:
        doc_lang = _detect_language(sample_text)

    async def generate_summary(node):
        """为单个节点生成摘要"""
        text = node.get('text', '')
        title = node.get('title', '')

        if not text or len(text.strip()) < 10:
            node['summary'] = ""
            return

        truncated_text = text[:3000]

        if doc_lang == 'zh':
            prompt = f"""请用1-2句中文概括以下章节的核心内容。

章节标题：{title}

内容：
{truncated_text}

请直接给出摘要，不要添加前缀。"""
        else:
            prompt = f"""Summarize the following section in 1-2 sentences.

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
    
    # Clean up LLM client
    await llm.close()


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
