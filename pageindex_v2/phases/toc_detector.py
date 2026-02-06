"""
TOC Detector - Detect Table of Contents pages with Chinese optimization
Supports both Chinese and English TOC formats
"""
from typing import List, Optional, Tuple
from ..core.llm_client import LLMClient
from ..utils.toc_pattern import TOCPatternExtractor
from ..utils.error_handler import is_fatal_llm_error, handle_fatal_error


class TOCDetector:
    """
    Detect TOC pages in PDF with Chinese document support
    """
    
    def __init__(self, llm: LLMClient, debug: bool = True):
        self.llm = llm
        self.debug = debug
        self.pattern_extractor = TOCPatternExtractor(llm, debug=debug)
    
    async def detect_toc_pages(
        self,
        pages: List,
        check_first_n: int = 20
    ) -> List[int]:
        """
        Detect which pages contain Table of Contents
        
        Args:
            pages: List of PDFPage objects
            check_first_n: Check first N pages for TOC
        
        Returns:
            List of page indices (0-indexed) that contain TOC
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[TOC DETECTOR] Searching for Table of Contents")
            print(f"{'='*60}")
            print(f"[TOC] Checking first {min(check_first_n, len(pages))} pages")
        
        toc_pages = []
        last_was_toc = False
        
        check_limit = min(check_first_n, len(pages))
        
        for i in range(check_limit):
            page = pages[i]
            is_toc = await self._check_single_page(page)
            
            if is_toc:
                toc_pages.append(i)
                last_was_toc = True
                if self.debug:
                    print(f"  ✓ Page {i + 1}: TOC detected")
            elif last_was_toc:
                # TOC ended
                if self.debug:
                    print(f"  ✗ Page {i + 1}: TOC ended")
                break
            else:
                if self.debug and i < 3:  # Show first few non-TOC pages
                    print(f"  ✗ Page {i + 1}: Not TOC")
        
        if self.debug:
            if toc_pages:
                print(f"\n[TOC] Found TOC on pages: {[p + 1 for p in toc_pages]}")
            else:
                print(f"\n[TOC] ⚠ No TOC detected in first {check_limit} pages")
            print(f"{'='*60}\n")
        
        return toc_pages
    
    async def _check_single_page(self, page) -> bool:
        """Check if single page contains TOC using LLM"""
        
        system_prompt = """
        You are a document analysis expert. Determine if the given page contains a Table of Contents (目录).

        ⚠️ **CRITICAL**: When extracting TOC titles, copy exact text from PDF - DO NOT modify any text.

        **What counts as TOC:**
        - Explicit "目录", "Table of Contents", "目次" headings
        - List of chapters/sections with or without page numbers
        - Numbered or bulleted lists of document sections
        - Hierarchical structure showing document organization

        **What does NOT count:**
        - Abstract, summary, executive summary
        - List of figures, tables, or appendices alone
        - Bibliography or references
        - Preface or introduction content
        - Body text of the document

        **Chinese document patterns:**
        - "第一章", "第二章", "第X章" (Chapters)
        - "1.1", "1.2", "2.1" (Numbered sections)
        - "第一节", "第二节" (Chinese numbered sections)
        - Mixed Chinese-English headings

        Reply in JSON format:
        {
            "reasoning": "Brief explanation of your decision",
            "is_toc": "yes" or "no"
        }

        Only return the JSON structure, nothing else.
        """
        
        # Use labeled content but strip the label for detection
        content = page.text[:2000]  # First 2000 chars
        
        prompt = f"""
        Does this page contain a Table of Contents (目录)?

        Page content (first 2000 characters):
        ---
        {content}
        ---

        Analyze and respond with JSON.
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt)
            return result.get("is_toc", "no").lower() == "yes"
        except Exception as e:
            # Check if this is a fatal error that should stop execution
            if is_fatal_llm_error(e):
                handle_fatal_error(e, "TOC detection")
            
            # Non-fatal error - log and continue
            if self.debug:
                print(f"  [ERROR] TOC check failed for page {page.page_number}: {e}")
            return False
    
    async def detect_all_toc_pages_lazy(
        self,
        pdf_path: str,
        total_pages: int,
        initial_pages: List,
        check_first_n: int = 20
    ) -> dict:
        """
        **优化版本**: 延迟解析 - 只解析必要的页面
        
        Detect ALL TOC pages but only parse pages as needed:
        Phase 1: Use already-parsed initial pages for main TOC detection
        Phase 2: Quick scan PDF directly using pdfplumber (no full parsing)
        Phase 3: Return candidate page numbers (caller decides whether to parse them)
        
        Args:
            pdf_path: PDF 文件路径
            total_pages: PDF 总页数
            initial_pages: 已解析的前 N 页 (用于主 TOC 检测)
            check_first_n: 前 N 页用于主 TOC 检测
        
        Returns:
            {
                'toc_pages': [5, 34, ...],  # 1-indexed
                'toc_info': {...},
                'candidate_pages_for_parsing': [34, 156, ...]  # 需要完整解析的候选页
            }
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[TOC DETECTOR V2] Lazy Parsing Mode - Smart Two-Phase Detection")
            print(f"{'='*60}")
        
        all_toc_pages = []
        all_toc_info = {}
        candidate_pages_for_parsing = []
        
        # ===== PHASE 1: Check first N pages for main TOC =====
        if self.debug:
            print(f"[TOC V2 - Phase 1] Checking first {check_first_n} pages for main TOC...")
        
        main_toc_pages = await self.detect_toc_pages(initial_pages, check_first_n)
        
        if main_toc_pages:
            for page_idx in main_toc_pages:
                page_num = page_idx + 1  # Convert to 1-indexed
                all_toc_pages.append(page_num)
                all_toc_info[page_num] = {
                    'type': 'main',
                    'reason': 'Main TOC detected in first pages',
                    'confidence': 'high',
                    'parent': None
                }
        
        # ===== PHASE 2: Quick scan PDF directly for nested TOCs =====
        if total_pages > check_first_n and main_toc_pages:
            if self.debug:
                print(f"[TOC V2 - Phase 2] Pattern-based nested TOC detection (lazy mode)...")
            
            # Step 1: 从主 TOC 学习格式模式（使用 LLM）
            main_toc_text = "\n".join([initial_pages[i].text for i in main_toc_pages])
            patterns = await self.pattern_extractor.learn_from_main_toc(main_toc_text)
            
            if patterns:
                # Step 2: 超快速扫描 PDF (使用 PyMuPDF 直接搜索,不提取全文)
                candidates = self.pattern_extractor.quick_scan_pdf_with_fitz(
                    pdf_path,
                    total_pages,
                    start_page=check_first_n
                )
                
                if self.debug:
                    print(f"[TOC V2 - Phase 2] Pattern matching found {len(candidates)} candidates")
                    if candidates:
                        print(f"  Candidate pages: {[c['page_num'] for c in candidates]}")
                
                # 返回候选页列表,让调用者决定是否解析
                candidate_pages_for_parsing = [c['page_num'] for c in candidates]
                
                # 暂时将候选页标记为 'nested_candidate' (需要后续 LLM 验证)
                for c in candidates:
                    page_num = c['page_num']
                    all_toc_pages.append(page_num)
                    all_toc_info[page_num] = {
                        'type': 'nested_candidate',
                        'reason': f"Pattern match ({c['matched_patterns']})",
                        'confidence': c['confidence'],
                        'needs_verification': True,
                        'parent': None
                    }
            else:
                if self.debug:
                    print(f"[TOC V2 - Phase 2] No patterns learned, skipping nested TOC detection")
        
        # ===== Final Summary =====
        if self.debug:
            print(f"\n[TOC V2] Detection complete (lazy mode):")
            print(f"  Main TOC pages: {[p for p in all_toc_pages if all_toc_info[p]['type'] == 'main']}")
            print(f"  Nested TOC candidates: {candidate_pages_for_parsing}")
            print(f"  Pages needing full parsing: {len(candidate_pages_for_parsing)}")
            print(f"{'='*60}\n")
        
        return {
            'toc_pages': sorted(all_toc_pages),
            'toc_info': all_toc_info,
            'candidate_pages_for_parsing': candidate_pages_for_parsing
        }
    
    async def detect_all_toc_pages(
        self,
        pages: List,
        check_first_n: int = 20
    ) -> dict:
        """
        Detect ALL TOC pages in the document (including nested TOCs).
        
        Uses Smart Two-Phase Detection:
        Phase 1: Check first N pages (default 20) for main TOC
        Phase 2: Pre-filter suspicious pages in rest of document, batch verify
        
        Args:
            pages: List of PDFPage objects
            check_first_n: Check first N pages for main TOC
        
        Returns:
            {
                'toc_pages': [5, 34, ...],  # 1-indexed page numbers
                'toc_info': {
                    5: {'type': 'main', 'reason': '...'},
                    34: {'type': 'nested', 'parent': '第五部分', 'reason': '...'}
                }
            }
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[TOC DETECTOR V2] Smart Two-Phase Detection")
            print(f"{'='*60}")
        
        all_toc_pages = []
        all_toc_info = {}
        
        # ===== PHASE 1: Check first N pages for main TOC =====
        if self.debug:
            print(f"[TOC V2 - Phase 1] Checking first {check_first_n} pages for main TOC...")
        
        main_toc_pages = await self.detect_toc_pages(pages, check_first_n)
        
        if main_toc_pages:
            for page_idx in main_toc_pages:
                page_num = page_idx + 1  # Convert to 1-indexed
                all_toc_pages.append(page_num)
                all_toc_info[page_num] = {
                    'type': 'main',
                    'reason': 'Main TOC detected in first pages',
                    'confidence': 'high',
                    'parent': None
                }
        
        # ===== PHASE 2: Check rest of document for nested TOCs =====
        if len(pages) > check_first_n and main_toc_pages:
            if self.debug:
                print(f"[TOC V2 - Phase 2] Pattern-based nested TOC detection...")
            
            # Step 1: 从主 TOC 学习格式模式（使用 LLM）
            main_toc_text = "\n".join([pages[i].text for i in main_toc_pages])
            patterns = await self.pattern_extractor.learn_from_main_toc(main_toc_text)
            
            if patterns:
                # Step 2: 使用正则快速扫描（最多找 5 个候选）
                candidates = self.pattern_extractor.quick_scan_for_nested_tocs(
                    pages, 
                    start_page=check_first_n
                )
                
                if self.debug:
                    print(f"[TOC V2 - Phase 2] Pattern matching found {len(candidates)} candidates")
                    if candidates:
                        print(f"  Candidate pages: {[c['page_num'] for c in candidates]}")
                
                # Step 3: LLM 验证候选页（只对候选页调用 LLM）
                if candidates:
                    nested_tocs = await self._batch_verify_nested_tocs(pages, candidates)
                    
                    for page_num, info in nested_tocs.items():
                        all_toc_pages.append(page_num)
                        all_toc_info[page_num] = info
            else:
                if self.debug:
                    print(f"[TOC V2 - Phase 2] No patterns learned, skipping nested TOC detection")
        
        # ===== Final Summary =====
        if self.debug:
            print(f"\n[TOC V2] Detection complete:")
            print(f"  Total TOC pages found: {len(all_toc_pages)}")
            for page_num in sorted(all_toc_pages):
                info = all_toc_info[page_num]
                print(f"  • Page {page_num} ({info['type']}): {info['reason'][:60]}...")
            print(f"{'='*60}\n")
        
        return {
            'toc_pages': sorted(all_toc_pages),
            'toc_info': all_toc_info
        }
    
    async def _batch_verify_nested_tocs(
        self,
        pages: List,
        candidates: List[dict]
    ) -> dict:
        """
        Batch verify candidate pages to determine if they are nested TOCs.
        
        Args:
            pages: All pages
            candidates: List of {'page_idx': int, 'page_num': int, 'summary': dict}
        
        Returns:
            {page_num: {'type': 'nested', 'reason': '...', ...}}
        """
        if not candidates:
            return {}
        
        # Prepare compact summary for LLM
        candidate_info = []
        for c in candidates:
            s = c['summary']
            candidate_info.append(
                f"Page {c['page_num']}: {s['tokens']} tokens, {s['list_items']} numbered items\n"
                f"  Preview: {s['preview'][:150]}"
            )
        
        system_prompt = """
        You are analyzing pages to identify nested Table of Contents (TOCs).
        
        ⚠️ **CRITICAL**: When identifying nested TOCs, preserve exact text from PDF - DO NOT modify.
        
        **What is a Nested TOC:**
        A nested TOC appears at the start of a major section and lists its subsections.
        
        **Characteristics:**
        - Section title at the top (e.g., "第五部分 投标文件格式")
        - Followed by compact numbered list (e.g., "一、自查表 二、资格文件 三、符合性文件")
        - Each item is brief (1-5 words)
        - Little prose, mostly list items
        - Low token count (< 200)
        
        **NOT a nested TOC:**
        - Regular content with numbered paragraphs
        - Detailed requirements or specifications
        - Long explanations between numbered items
        
        Reply in JSON:
        {
            "nested_tocs": [
                {
                    "page": 34,
                    "confidence": "high",
                    "parent": "第五部分 投标文件格式",
                    "reason": "Section header + 6 compact subsection items"
                }
            ]
        }
        """
        
        prompt = f"""
        Which of these candidate pages are nested TOCs?
        
        Candidates:
        ---
        {chr(10).join(candidate_info)}
        ---
        
        Return JSON with verified nested TOCs only.
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt)
            
            verified = {}
            for item in result.get('nested_tocs', []):
                page_num = item.get('page')
                if page_num:
                    verified[page_num] = {
                        'type': 'nested',
                        'reason': item.get('reason', ''),
                        'confidence': item.get('confidence', 'medium'),
                        'parent': item.get('parent', None)
                    }
            
            if self.debug and verified:
                print(f"[TOC V2 - Phase 2] Verified {len(verified)} nested TOC(s)")
            
            return verified
            
        except Exception as e:
            if self.debug:
                print(f"[ERROR] Batch verification failed: {e}")
            return {}
    
    def _generate_page_summary(self, page, page_index: int) -> dict:
        """
        Generate a compact summary of a page for TOC detection.
        
        Returns:
            {
                'page': 5,
                'tokens': 60,
                'has_numbering': True,
                'list_items': 6,
                'preview': 'First 300 chars...'
            }
        """
        import re
        
        text = page.text
        tokens = len(text)
        
        # Detect Chinese numbering: 一、二、三、
        chinese_nums = re.findall(r'[一二三四五六七八九十]+[、．.]', text)
        
        # Detect Arabic numbering: 1. 2. 3. or 1.1 1.2
        arabic_nums = re.findall(r'\b\d+[\.、](?:\d+[\.、]?)?\s', text)
        
        # Detect letter numbering: A. B. C.
        letter_nums = re.findall(r'\b[A-Z][\.、]\s', text)
        
        # Count total numbered items
        list_items = len(chinese_nums) + len(arabic_nums) + len(letter_nums)
        has_numbering = list_items > 0
        
        # Get preview (first 300 chars)
        preview = text[:300].replace('\n', ' ').strip()
        
        return {
            'page': page_index + 1,  # 1-indexed
            'tokens': tokens,
            'has_numbering': has_numbering,
            'list_items': list_items,
            'preview': preview
        }
    
    async def detect_page_numbers_in_toc(
        self,
        toc_pages: List,
        pages: List
    ) -> Tuple[bool, str]:
        """
        Check if TOC contains page numbers
        
        Returns:
            (has_page_numbers, toc_content)
        """
        if not toc_pages:
            return False, ""
        
        # Combine TOC pages content
        toc_content = "\n\n".join([pages[i].text for i in toc_pages])
        
        # Clean up dots
        toc_content = self._clean_toc_format(toc_content)
        
        system_prompt = """
        Analyze if this Table of Contents contains page numbers for each section/chapter.

        **What COUNTS as TOC page numbers:**
        - Numbers at the end of TOC lines indicating where sections start
        - Examples: 
          * "Chapter 1 ......... 5" (the 5 is TOC page number)
          * "第一章 简介 ........ 10" (the 10 is TOC page number)
          * "1.1 Background    15" (the 15 is TOC page number)

        **What DOES NOT count (IGNORE these):**
        - Page footer markers (bottom of page labels)
        - Section numbering like "1.1", "1.2" (these are section codes, not page numbers)

        **Few-shot examples:**

        Example 1 - HAS page numbers:
        Input: "目录\n第一章 引言 ......... 1\n第二章 方法 ......... 10\n第 2 页 共 50 页"
        Analysis: Each section has a number at the end (1, 10). "第 2 页 共 50 页" is page footer, ignore it.
        Answer: "yes"

        Example 2 - NO page numbers:
        Input: "目 录\n第一部分 投标邀请函\n第二部分 采购项目内容\n第三部分 投标人须知\n第 4 页 共 78 页"
        Analysis: Sections have no numbers after them. "第 4 页 共 78 页" is page footer, ignore it.
        Answer: "no"

        Example 3 - HAS page numbers:
        Input: "Contents\n1. Introduction ................ 5\n2. Literature Review ........... 15\n3. Methodology ................. 25\nPage 3 of 100"
        Analysis: Each section has page number (5, 15, 25). "Page 3 of 100" is footer, ignore it.
        Answer: "yes"

        Example 4 - NO page numbers:
        Input: "Table of Contents\nChapter 1: Overview\nChapter 2: Analysis\nChapter 3: Results\n- 5 -"
        Analysis: Sections listed without page numbers. "- 5 -" is footer, ignore it.
        Answer: "no"

        Example 5 - HAS page numbers:
        Input: "目录\n1.1 研究背景 ................ 2\n1.2 研究意义 ................ 5\n2.1 文献综述 ................ 8"
        Analysis: Each subsection has page number (2, 5, 8).
        Answer: "yes"

        Reply in JSON:
        {
            "reasoning": "Explain what you observed: do sections have page numbers after them?",
            "has_page_numbers": "yes" or "no"
        }
        """
        
        prompt = f"""
        Does this Table of Contents contain page numbers for sections/chapters?

        TOC content:
        ---
        {toc_content[:3000]}
        ---

        Look for page numbers AFTER section titles. Ignore any page footer markers at the bottom.
        Respond with JSON.
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt)
            has_numbers = result.get("has_page_numbers", "no").lower() == "yes"
            
            if self.debug:
                status = "✓ has" if has_numbers else "✗ no"
                reasoning = result.get("reasoning", "")[:100]
                print(f"[TOC] Page numbers: {status}")
                print(f"[TOC] Reasoning: {reasoning}...")
            
            return has_numbers, toc_content
            
        except Exception as e:
            if self.debug:
                print(f"[ERROR] Page number detection failed: {e}")
            return False, toc_content
    
    def _clean_toc_format(self, text: str) -> str:
        """Clean TOC formatting (dots to colons)"""
        import re
        # Replace multiple dots with colon
        text = re.sub(r'\.{4,}', ': ', text)
        # Handle spaced dots
        text = re.sub(r'(?:\. )\.{3,}', ': ', text)
        return text
    
    async def validate_toc_extraction(
        self,
        toc_content: str,
        extracted_structure: List[dict]
    ) -> bool:
        """
        Validate if TOC extraction is complete
        """
        if not extracted_structure:
            return False
        
        system_prompt = """
        Validate if the extracted table of contents is complete compared to the original TOC.

        Check if all major sections from the original TOC appear in the extracted structure.

        Reply in JSON:
        {
            "reasoning": "Comparison of original vs extracted",
            "is_complete": "yes" or "no"
        }
        """
        
        prompt = f"""
        Original TOC:
        ---
        {toc_content[:2000]}
        ---

        Extracted structure:
        ---
        {extracted_structure}
        ---

        Is the extraction complete? Respond with JSON.
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt)
            return result.get("is_complete", "no").lower() == "yes"
        except:
            return False
