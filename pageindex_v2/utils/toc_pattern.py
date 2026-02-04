"""
TOC Pattern Extractor - Learn TOC format patterns from main TOC
Uses LLM to extract patterns, then regex matching to find nested TOCs
"""
import re
from typing import List, Dict, Tuple, Optional
from ..core.llm_client import LLMClient
import fitz  # PyMuPDF for fast PDF search

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


class TOCPatternExtractor:
    """
    Extract TOC formatting patterns from main TOC using LLM
    Use patterns to quickly find nested TOCs via regex
    """
    
    def __init__(self, llm: LLMClient, debug: bool = True):
        self.llm = llm
        self.debug = debug
        self.patterns = []
        self.max_nested_toc = 5  # 上限：最多找 5 个嵌套 TOC
    
    async def learn_from_main_toc(self, toc_text: str) -> List[str]:
        """
        使用 LLM 从主 TOC 中学习格式模式
        
        Returns:
            List of regex patterns
        """
        if self.debug:
            print(f"\n[TOC PATTERN] Learning patterns from main TOC using LLM...")
        
        # 取 TOC 的前 30 行作为样本
        lines = toc_text.strip().split('\n')
        sample_lines = [line.strip() for line in lines if line.strip()][:30]
        sample_text = '\n'.join(sample_lines)
        
        system_prompt = r"""你是一个文档格式分析专家。分析给定的目录（TOC）样本，提取其格式模式。

输出 JSON 格式：
{
    "patterns": [
        {
            "name": "模式名称",
            "description": "模式描述",
            "regex": "正则表达式",
            "example": "示例行"
        }
    ]
}

**要求**:
1. 识别目录条目的格式规律（编号、标题、页码的排列方式）
2. 生成能匹配该格式的正则表达式
3. 正则要足够宽松，能匹配同类型的其他目录
4. 最多提取 3-5 个主要模式

**常见模式示例**:
- 数字编号 + 标题 + 点线 + 页码: `^\d+(\.\d+)*\s+.+?\s+\.{3,}\s*\d+`
- 数字编号 + 标题 + 空格 + 页码: `^\d+(\.\d+)*\s+.+?\s{2,}\d+\s*$`
- 第X章 + 标题 + 点线 + 页码: `^第[一二三四五六七八九十\d]+章\s+.+?\s+\.{3,}\s*\d+`
- Chapter + 编号 + 标题: `^Chapter\s+\d+\s+.+?\s+\.{3,}\s*\d+`

返回 JSON only."""

        prompt = f"""目录样本：

{sample_text}

分析这个目录的格式模式，提取正则表达式。"""

        try:
            result = await self.llm.chat_json(
                prompt, 
                system=system_prompt,
                temperature=0.1,
                max_tokens=2000
            )
            
            patterns = result.get("patterns", [])
            
            if not patterns:
                if self.debug:
                    print("[TOC PATTERN] LLM returned no patterns")
                return []
            
            # 验证并清理模式
            valid_patterns = []
            for p in patterns:
                if 'regex' in p and 'name' in p:
                    # 测试正则是否有效
                    try:
                        re.compile(p['regex'])
                        valid_patterns.append(p)
                    except re.error as e:
                        if self.debug:
                            print(f"[TOC PATTERN] Invalid regex from LLM: {p['regex']}, error: {e}")
            
            self.patterns = valid_patterns
            
            if self.debug:
                print(f"[TOC PATTERN] Learned {len(valid_patterns)} valid patterns:")
                for p in valid_patterns:
                    print(f"  - {p['name']}: {p.get('description', 'N/A')}")
                    print(f"    Regex: {p['regex']}")
                    if 'example' in p:
                        print(f"    Example: {p['example']}")
            
            return [p['regex'] for p in valid_patterns]
            
        except Exception as e:
            if self.debug:
                print(f"[TOC PATTERN] Failed to learn patterns from LLM: {e}")
            return []
    
    def quick_scan_for_nested_tocs(
        self, 
        pages: List,
        start_page: int = 20
    ) -> List[Dict]:
        """
        使用学到的模式快速扫描嵌套 TOC
        
        Args:
            pages: PDFPage 对象列表
            start_page: 从第几页开始扫描（默认 20，跳过主 TOC）
        
        Returns:
            候选页列表（最多 max_nested_toc 个）
        """
        if not self.patterns:
            if self.debug:
                print("[TOC PATTERN] No patterns learned, skipping nested TOC scan")
            return []
        
        if self.debug:
            print(f"\n[TOC PATTERN] Quick scanning pages {start_page+1}-{len(pages)} for nested TOCs...")
            print(f"[TOC PATTERN] Using {len(self.patterns)} patterns")
            print(f"[TOC PATTERN] Max nested TOCs to find: {self.max_nested_toc}")
        
        candidates = []
        pages_scanned = 0
        
        for i in range(start_page, len(pages)):
            if len(candidates) >= self.max_nested_toc:
                if self.debug:
                    print(f"[TOC PATTERN] Reached max limit ({self.max_nested_toc}), stopping scan")
                break
            
            page = pages[i]
            page_text = page.text if hasattr(page, 'text') else str(page)
            pages_scanned += 1
            
            # 检查页面是否匹配任何模式
            matches = self._check_page_matches_patterns(page_text, i + 1)
            
            if matches['is_candidate']:
                candidates.append({
                    'page_idx': i,
                    'page_num': i + 1,
                    'matched_patterns': matches['matched_patterns'],
                    'match_count': matches['match_count'],
                    'confidence': matches['confidence']
                })
                
                if self.debug:
                    print(f"  ✓ Page {i+1}: {matches['match_count']} pattern matches "
                          f"(confidence: {matches['confidence']})")
        
        if self.debug:
            print(f"[TOC PATTERN] Scanned {pages_scanned} pages, found {len(candidates)} candidates")
            if candidates:
                print(f"  Candidate pages: {[c['page_num'] for c in candidates]}")
        
        return candidates
    
    def quick_scan_pdf_with_fitz(
        self,
        pdf_path: str,
        total_pages: int,
        start_page: int = 20
    ) -> List[Dict]:
        """
        **超快速扫描**: 使用 PyMuPDF (fitz) 的 search_for() 直接搜索关键词
        
        策略:
        1. 使用 PyMuPDF 的 search_for() 搜索 TOC 特征关键词(不提取全文!)
        2. 只对包含关键词的页面提取文本进行详细匹配
        
        这比提取全文快 100 倍!
        
        Args:
            pdf_path: PDF 文件路径
            total_pages: PDF 总页数
            start_page: 从第几页开始扫描 (0-indexed)
        
        Returns:
            候选页列表（最多 max_nested_toc 个）
        """
        if not self.patterns:
            if self.debug:
                print("[TOC PATTERN] No patterns learned, skipping nested TOC scan")
            return []
        
        if self.debug:
            print(f"\n[TOC PATTERN] Ultra-fast keyword search (pages {start_page+1}-{total_pages})...")
            print(f"[TOC PATTERN] Using {len(self.patterns)} patterns")
            print(f"[TOC PATTERN] Max nested TOCs to find: {self.max_nested_toc}")
        
        candidates = []
        
        try:
            doc = fitz.open(pdf_path)
            
            # Step 1: 使用 search_for() 快速查找包含章节编号的页面
            # 搜索常见的章节编号模式 (不需要提取全文!)
            search_patterns = [
                "1.1",   # 章节编号
                "2.1",
                "3.1",
                "第一章",  # 中文章节
                "第二章",
                "Chapter 1",  # 英文章节
                "Chapter 2",
            ]
            
            suspicious_pages = set()  # 包含关键词的页面
            
            if self.debug:
                print(f"[TOC PATTERN] Step 1: Ultra-fast keyword search (no text extraction)...")
            
            # 快速搜索关键词
            for keyword in search_patterns:
                for page_num in range(start_page, total_pages):
                    if page_num in suspicious_pages:
                        continue  # 已经标记为可疑
                    
                    page = doc[page_num]
                    # search_for() 直接在 PDF 中搜索,不提取文本!
                    hits = page.search_for(keyword)
                    
                    if len(hits) >= 2:  # 至少出现 2 次
                        suspicious_pages.add(page_num)
                        
                        if len(suspicious_pages) >= 20:  # 最多找 20 个可疑页面
                            break
                
                if len(suspicious_pages) >= 20:
                    break
                
                # 进度输出
                if self.debug and search_patterns.index(keyword) % 2 == 1:
                    print(f"  [PROGRESS] Searched {search_patterns.index(keyword)+1}/{len(search_patterns)} keywords, found {len(suspicious_pages)} suspicious pages...")
            
            if self.debug:
                print(f"[TOC PATTERN] Step 1 complete: {len(suspicious_pages)} suspicious pages")
                if suspicious_pages:
                    sorted_pages = sorted(list(suspicious_pages))
                    print(f"  Suspicious pages: {sorted_pages[:10]}{'...' if len(sorted_pages) > 10 else ''}")
            
            # Step 2: 只对可疑页面提取文本并进行详细匹配
            if self.debug:
                print(f"[TOC PATTERN] Step 2: Detailed pattern matching on {len(suspicious_pages)} pages (extracting text)...")
            
            for page_num in sorted(suspicious_pages):
                if len(candidates) >= self.max_nested_toc:
                    if self.debug:
                        print(f"[TOC PATTERN] Reached max limit ({self.max_nested_toc}), stopping")
                    break
                
                page = doc[page_num]
                page_text = page.get_text()  # 只有现在才提取文本
                
                # 使用学到的模式进行详细匹配
                matches = self._check_page_matches_patterns(page_text, page_num + 1)
                
                if matches['is_candidate']:
                    candidates.append({
                        'page_idx': page_num,
                        'page_num': page_num + 1,
                        'matched_patterns': matches['matched_patterns'],
                        'match_count': matches['match_count'],
                        'confidence': matches['confidence']
                    })
                    
                    if self.debug:
                        print(f"  ✓ Page {page_num+1}: {matches['match_count']} pattern matches "
                              f"(confidence: {matches['confidence']})")
            
            doc.close()
            
        except Exception as e:
            if self.debug:
                print(f"[TOC PATTERN] Error during ultra-fast scan: {e}")
                import traceback
                traceback.print_exc()
            return []
        
        if self.debug:
            print(f"[TOC PATTERN] Ultra-fast scan complete: found {len(candidates)} candidates")
            if candidates:
                print(f"  Candidate pages: {[c['page_num'] for c in candidates]}")
        
        return candidates
    
    def quick_scan_pdf_directly(
        self,
        pdf_path: str,
        total_pages: int,
        start_page: int = 20
    ) -> List[Dict]:
        """
        直接快速扫描 PDF 文件 (不创建完整 PDFPage 对象)
        用于大型 PDF 的嵌套 TOC 检测
        
        Args:
            pdf_path: PDF 文件路径
            total_pages: PDF 总页数
            start_page: 从第几页开始扫描 (0-indexed)
        
        Returns:
            候选页列表（最多 max_nested_toc 个）
        """
        if not self.patterns:
            if self.debug:
                print("[TOC PATTERN] No patterns learned, skipping nested TOC scan")
            return []
        
        if not HAS_PDFPLUMBER:
            if self.debug:
                print("[TOC PATTERN] pdfplumber not available, cannot quick scan")
            return []
        
        if self.debug:
            print(f"\n[TOC PATTERN] Quick scanning PDF directly (pages {start_page+1}-{total_pages})...")
            print(f"[TOC PATTERN] Using {len(self.patterns)} patterns")
            print(f"[TOC PATTERN] Max nested TOCs to find: {self.max_nested_toc}")
        
        candidates = []
        pages_scanned = 0
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for i in range(start_page, min(total_pages, len(pdf.pages))):
                    if len(candidates) >= self.max_nested_toc:
                        if self.debug:
                            print(f"[TOC PATTERN] Reached max limit ({self.max_nested_toc}), stopping scan")
                        break
                    
                    # 快速提取文本 (不解析表格)
                    page = pdf.pages[i]
                    page_text = page.extract_text() or ""
                    pages_scanned += 1
                    
                    # 每 100 页输出一次进度
                    if self.debug and pages_scanned % 100 == 0:
                        print(f"  [PROGRESS] Scanned {pages_scanned} pages, found {len(candidates)} candidates so far...")
                    
                    # 检查页面是否匹配任何模式
                    matches = self._check_page_matches_patterns(page_text, i + 1)
                    
                    if matches['is_candidate']:
                        candidates.append({
                            'page_idx': i,
                            'page_num': i + 1,
                            'matched_patterns': matches['matched_patterns'],
                            'match_count': matches['match_count'],
                            'confidence': matches['confidence']
                        })
                        
                        if self.debug:
                            print(f"  ✓ Page {i+1}: {matches['match_count']} pattern matches "
                                  f"(confidence: {matches['confidence']})")
        
        except Exception as e:
            if self.debug:
                print(f"[TOC PATTERN] Error during quick scan: {e}")
            return []
        
        if self.debug:
            print(f"[TOC PATTERN] Quick scan complete: scanned {pages_scanned} pages, found {len(candidates)} candidates")
            if candidates:
                print(f"  Candidate pages: {[c['page_num'] for c in candidates]}")
        
        return candidates
    
    def _check_page_matches_patterns(
        self, 
        page_text: str,
        page_num: int
    ) -> Dict:
        """
        检查页面是否匹配学到的模式
        
        Returns:
            {
                'is_candidate': bool,
                'matched_patterns': List[str],
                'match_count': int,
                'confidence': str
            }
        """
        lines = page_text.strip().split('\n')
        matched_patterns = []
        total_matches = 0
        
        for pattern_info in self.patterns:
            pattern = pattern_info['regex']
            pattern_name = pattern_info['name']
            
            matches = 0
            for line in lines:
                line = line.strip()
                if line and re.search(pattern, line):
                    matches += 1
            
            if matches >= 3:  # 至少 3 行匹配才算
                matched_patterns.append(pattern_name)
                total_matches += matches
        
        # 判断是否是候选页
        is_candidate = len(matched_patterns) > 0 and total_matches >= 3
        
        # 计算置信度
        if total_matches >= 10:
            confidence = 'high'
        elif total_matches >= 5:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        return {
            'is_candidate': is_candidate,
            'matched_patterns': matched_patterns,
            'match_count': total_matches,
            'confidence': confidence
        }
    
    def get_pattern_summary(self) -> Dict:
        """获取模式摘要"""
        return {
            'pattern_count': len(self.patterns),
            'patterns': [
                {
                    'name': p['name'],
                    'description': p['description']
                }
                for p in self.patterns
            ],
            'max_nested_toc': self.max_nested_toc
        }
