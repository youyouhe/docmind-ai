"""
PDF Parser - Extract text with table preservation and physical index labels
Supports Chinese documents with table structure retention

Five-tier fallback strategy:
1. pdfplumber (best for tables)
2. pdfminer.six (best text quality)
3. pypdfium2 (Chrome engine fallback)
4. PyMuPDF (always available)
5. DeepSeek-OCR-2 via OCR service (for scanned/image-based PDFs)
"""
import os
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

# Import all available PDF libraries
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("[WARNING] pdfplumber not installed, table detection disabled")

try:
    from pdfminer.high_level import extract_text_to_fp
    from pdfminer.layout import LAParams
    from pdfminer.converter import TextConverter
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.pdfpage import PDFPage as PdfMinerPage  # Rename to avoid conflict
    from io import BytesIO
    HAS_PDFMINER = True
except ImportError:
    HAS_PDFMINER = False
    print("[WARNING] pdfminer.six not installed")

try:
    import pypdfium2 as pdfium
    HAS_PYPDFIUM2 = True
except ImportError:
    HAS_PYPDFIUM2 = False
    print("[WARNING] pypdfium2 not installed")

import fitz  # PyMuPDF always available as final fallback


@dataclass
class PDFPage:
    """Represents a PDF page with metadata"""
    page_number: int  # 1-indexed
    text: str
    tokens: int
    has_table: bool
    labeled_content: str  # With <physical_index_X> tag


class PDFParser:
    """
    Parse PDF with five-tier fallback strategy:
    1. pdfplumber (best for tables)
    2. pdfminer.six (best text quality)
    3. pypdfium2 (Chrome engine fallback)
    4. PyMuPDF (always available)
    5. DeepSeek-OCR-2 via OCR service (for scanned PDFs)

    Features:
    - Table structure preservation
    - Physical index labeling
    - Chinese document support
    - Automatic quality detection
    - Scanned PDF detection and OCR fallback
    """

    def __init__(self, debug: bool = True, ocr_client=None):
        self.debug = debug
        self.ocr_client = ocr_client  # Optional OCRClient instance
    
    async def parse(
        self,
        pdf_path: str,
        max_pages: Optional[int] = None
    ) -> List[PDFPage]:
        """
        Parse PDF and extract pages with table preservation
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum pages to parse (None = all)
        
        Returns:
            List of PDFPage objects with labeled content
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[PDF PARSER] Three-Tier Extraction Strategy")
            print(f"{'='*60}")
            print(f"[PDF] File: {pdf_path}")
            libs = []
            if HAS_PDFPLUMBER: libs.append("pdfplumber")
            if HAS_PDFMINER: libs.append("pdfminer")
            if HAS_PYPDFIUM2: libs.append("pypdfium2")
            libs.append("pymupdf")
            print(f"[PDF] Available: {' → '.join(libs)}")
        
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        # Get total page count
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        limit = max_pages if max_pages else total_pages
        doc.close()
        
        if self.debug:
            print(f"[PDF] Total pages: {total_pages}, Will parse: {limit}")
        
        pages = []
        parser_used = None
        
        # Tier 1: pdfplumber (best for tables)
        if HAS_PDFPLUMBER:
            if self.debug:
                print(f"[PDF] 🔄 Trying Tier 1: pdfplumber (table detection)...")
            pages = await self._parse_with_pdfplumber(pdf_path, limit)
            
            # Check extraction quality
            if pages and not self._is_poor_extraction(pages[0].text):
                parser_used = "pdfplumber"
            else:
                if self.debug:
                    print("\n[PDF] ⚠️  Poor quality with pdfplumber")
                pages = []  # Clear for next attempt
        
        # Tier 2: pdfminer (best text quality)
        if not pages and HAS_PDFMINER:
            if self.debug:
                print("[PDF] 🔄 Trying Tier 2: pdfminer.six (high quality)...")
            pages = await self._parse_with_pdfminer(pdf_path, limit)
            
            # Check extraction quality
            if pages and not self._is_poor_extraction(pages[0].text):
                parser_used = "pdfminer"
            else:
                if self.debug:
                    print("\n[PDF] ⚠️  Poor quality with pdfminer")
                pages = []
        
        # Tier 3: pypdfium2 (Chrome engine)
        if not pages and HAS_PYPDFIUM2:
            if self.debug:
                print("[PDF] 🔄 Trying Tier 3: pypdfium2 (Chrome engine)...")
            pages = await self._parse_with_pypdfium2(pdf_path, limit)
            
            if pages and not self._is_poor_extraction(pages[0].text):
                parser_used = "pypdfium2"
            else:
                if self.debug:
                    print("\n[PDF] ⚠️  Poor quality with pypdfium2")
                pages = []
        
        # Final fallback: PyMuPDF (always available)
        if not pages:
            if self.debug:
                print("[PDF] 🔄 Using final fallback: PyMuPDF...")
            pages = await self._parse_with_pymupdf(pdf_path, limit)
            parser_used = "pymupdf"

        # Tier 5: OCR for scanned/image-based PDFs
        if self._is_scanned_pdf(pages):
            if self.ocr_client and self.ocr_client.is_available():
                if self.debug:
                    print("\n[PDF] 📸 Detected scanned/image-based PDF")
                    print("[PDF] 🔄 Trying Tier 5: DeepSeek-OCR-2 via OCR service...")
                ocr_pages = await self._parse_with_ocr(pdf_path, limit)
                if ocr_pages:
                    pages = ocr_pages
                    parser_used = "deepseek-ocr-2"
            else:
                if self.debug:
                    reason = "OCR service not configured" if not self.ocr_client else "OCR service not available"
                    print(f"\n[PDF] ⚠️  Scanned PDF detected but {reason}")

        if self.debug:
            print(f"\n[PDF] ✅ Extraction complete using: {parser_used}")
            print(f"[PDF] Extracted: {len(pages)} pages")
            total_tokens = sum(p.tokens for p in pages)
            tables_found = sum(1 for p in pages if p.has_table)
            print(f"[PDF] Total tokens: {total_tokens}")
            print(f"[PDF] Pages with tables: {tables_found}")
            
            # Quality report
            if pages:
                sample_words = pages[0].text.split()[:100]
                single_chars = sum(1 for w in sample_words if len(w) == 1)
                avg_len = sum(len(w) for w in sample_words) / len(sample_words) if sample_words else 0
                print(f"[PDF] Quality: {len(sample_words)} words, {single_chars} single-chars ({100*single_chars/len(sample_words) if sample_words else 0:.1f}%), avg len: {avg_len:.2f}")
            print(f"{'='*60}\n")
        
        return pages
    
    async def _parse_with_pdfplumber(
        self,
        pdf_path: str,
        max_pages: int
    ) -> List[PDFPage]:
        """Parse using pdfplumber with table detection"""
        pages = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for i in range(min(max_pages, len(pdf.pages))):
                page_num = i + 1
                page = pdf.pages[i]
                
                # Detect tables
                tables = page.extract_tables()
                has_table = len(tables) > 0
                
                # Extract text
                raw_text = page.extract_text() or ""
                
                # Format with tables preserved
                formatted_text = self._format_with_tables(raw_text, tables)
                
                # Add physical index label
                labeled_content = f"<physical_index_{page_num}>\n{formatted_text}"
                
                # Count tokens
                tokens = self._estimate_tokens(formatted_text)
                
                pdf_page = PDFPage(
                    page_number=page_num,
                    text=formatted_text,
                    tokens=tokens,
                    has_table=has_table,
                    labeled_content=labeled_content
                )
                pages.append(pdf_page)
                
                if self.debug:
                    table_markers = formatted_text.count('|') // 2
                    print(f"  Page {page_num}: {tokens} tokens, {table_markers} table rows")
        
        return pages
    
    async def _parse_with_pdfminer(
        self,
        pdf_path: str,
        max_pages: int
    ) -> List[PDFPage]:
        """Tier 2: Parse using pdfminer.six (best text quality)"""
        pages = []
        
        with open(pdf_path, 'rb') as fp:
            for i, page in enumerate(PdfMinerPage.get_pages(fp)):
                if i >= max_pages:
                    break
                
                page_num = i + 1
                
                # Extract text from this page
                output = BytesIO()
                rsrcmgr = PDFResourceManager()
                device = TextConverter(rsrcmgr, output, laparams=LAParams())
                interpreter = PDFPageInterpreter(rsrcmgr, device)
                interpreter.process_page(page)
                device.close()
                
                text = output.getvalue().decode('utf-8')
                labeled = f"<physical_index_{page_num}>\n{text}"
                tokens = self._estimate_tokens(text)
                
                pdf_page = PDFPage(
                    page_number=page_num,
                    text=text,
                    tokens=tokens,
                    has_table=False,  # pdfminer doesn't detect tables easily
                    labeled_content=labeled
                )
                pages.append(pdf_page)
                
                if self.debug:
                    print(f"  Page {page_num}: {tokens} tokens")
        
        return pages
    
    async def _parse_with_pypdfium2(
        self,
        pdf_path: str,
        max_pages: int
    ) -> List[PDFPage]:
        """Tier 3: Parse using pypdfium2 (Chrome's PDFium engine)"""
        pages = []
        pdf = pdfium.PdfDocument(pdf_path)
        
        for i in range(min(max_pages, len(pdf))):
            page_num = i + 1
            page = pdf[i]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            
            labeled = f"<physical_index_{page_num}>\n{text}"
            tokens = self._estimate_tokens(text)
            
            pdf_page = PDFPage(
                page_number=page_num,
                text=text,
                tokens=tokens,
                has_table=False,  # pypdfium2 doesn't detect tables
                labeled_content=labeled
            )
            pages.append(pdf_page)
            
            if self.debug:
                print(f"  Page {page_num}: {tokens} tokens")
            
            page.close()
        
        pdf.close()
        return pages
    
    async def _parse_with_pymupdf(
        self,
        pdf_path: str,
        max_pages: int
    ) -> List[PDFPage]:
        """Final fallback: Parse using PyMuPDF"""
        pages = []
        doc = fitz.open(pdf_path)
        
        for i in range(min(max_pages, len(doc))):
            page_num = i + 1
            page = doc.load_page(i)
            text = page.get_text("text")
            
            # Add label
            labeled = f"<physical_index_{page_num}>\n{text}"
            tokens = self._estimate_tokens(text)
            
            pdf_page = PDFPage(
                page_number=page_num,
                text=text,
                tokens=tokens,
                has_table=False,  # PyMuPDF doesn't detect tables
                labeled_content=labeled
            )
            pages.append(pdf_page)
            
            if self.debug:
                print(f"  Page {page_num}: {tokens} tokens")
        
        doc.close()
        return pages
    
    def _format_with_tables(
        self,
        text: str,
        tables: List[List[List[str]]]
    ) -> str:
        """
        Format text with tables in Markdown format
        REPLACES original table text with clean Markdown tables
        """
        if not tables:
            return text
        
        # Build set of all table cell texts for detection
        table_cell_texts = set()
        for table in tables:
            for row in table:
                for cell in row:
                    if cell:
                        cell_text = str(cell).strip()
                        table_cell_texts.add(cell_text)
                        # Add partial texts for matching
                        if len(cell_text) > 5:
                            table_cell_texts.add(cell_text[:10])
                            table_cell_texts.add(cell_text[-10:])
        
        # Convert tables to markdown
        markdown_tables = []
        for table in tables:
            if not table:
                continue
            
            # Clean cells
            clean_rows = []
            for row in table:
                clean_row = [
                    str(cell).replace('\n', ' ').strip() if cell else ""
                    for cell in row
                ]
                clean_rows.append(clean_row)
            
            if not clean_rows:
                continue
            
            # Build markdown
            md_lines = []
            # Header
            md_lines.append("| " + " | ".join(clean_rows[0]) + " |")
            # Separator  
            md_lines.append("|" + "|".join([" --- " for _ in clean_rows[0]]) + "|")
            # Data rows
            for row in clean_rows[1:]:
                md_lines.append("| " + " | ".join(row) + " |")
            
            markdown_tables.append("\n".join(md_lines))
        
        # Smart replacement: detect table regions and replace with markdown
        lines = text.split('\n')
        result_lines = []
        table_idx = 0
        skip_until_idx = -1
        
        for i, line in enumerate(lines):
            # Skip if we're inside a table region
            if i <= skip_until_idx:
                continue
            
            # Check if this line is part of a table
            is_table_line = False
            line_stripped = line.strip()
            
            if line_stripped:
                # Check if line matches table content
                for cell_text in table_cell_texts:
                    if len(cell_text) > 3 and cell_text in line_stripped:
                        is_table_line = True
                        break
                
                # Additional check: short lines with numbers/slashes (table cells)
                if not is_table_line and len(line_stripped) < 40:
                    has_slashes = line_stripped.count('/') >= 2
                    has_numbers = any(c.isdigit() for c in line_stripped[:5])
                    if has_slashes and has_numbers:
                        is_table_line = True
            
            if is_table_line:
                # Found table region - find where it ends
                if table_idx < len(markdown_tables):
                    # Skip consecutive table lines
                    j = i
                    while j < len(lines) and j < i + 15:  # Max 15 lines per table
                        next_line = lines[j].strip()
                        is_still_table = False
                        for cell_text in table_cell_texts:
                            if len(cell_text) > 3 and cell_text in next_line:
                                is_still_table = True
                                break
                        if not is_still_table and next_line and len(next_line) > 30:
                            # Looks like normal text, table ended
                            break
                        j += 1
                    
                    # Insert markdown table instead
                    result_lines.append("\n[TABLE]\n" + markdown_tables[table_idx] + "\n[/TABLE]\n")
                    table_idx += 1
                    skip_until_idx = j - 1
                else:
                    # No more markdown tables, skip this line
                    pass
            else:
                # Normal line, keep it
                result_lines.append(line)
        
        # If any tables weren't inserted, add them at the end
        while table_idx < len(markdown_tables):
            result_lines.append("\n[TABLE]\n" + markdown_tables[table_idx] + "\n[/TABLE]\n")
            table_idx += 1
        
        return '\n'.join(result_lines)
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (Chinese-aware)"""
        # Chinese: ~2 chars per token
        # English: ~4 chars per token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return (chinese_chars // 2) + (other_chars // 4)
    
    def _is_scanned_pdf(self, pages: List[PDFPage]) -> bool:
        """
        Detect if pages represent a scanned/image-based PDF.
        Returns True if most sampled pages have very little text (<50 chars).
        """
        if not pages:
            return True
        sample = pages[:min(5, len(pages))]
        empty_count = sum(1 for p in sample if len(p.text.strip()) < 50)
        return empty_count >= max(1, int(len(sample) * 0.8))

    async def _parse_with_ocr(
        self,
        pdf_path: str,
        max_pages: int,
    ) -> List[PDFPage]:
        """Tier 5: Parse using DeepSeek-OCR-2 via OCR service."""
        # Try to import progress reporting for WebSocket updates
        try:
            from pageindex.progress_callback import get_document_id, report_progress
            doc_id = get_document_id()
        except Exception:
            doc_id = None
            report_progress = None

        pages = []
        doc = fitz.open(pdf_path)
        total = min(max_pages, len(doc))
        doc.close()

        # Check how many pages are already cached
        cached_count = self.ocr_client.get_cached_page_count(pdf_path)
        if self.debug:
            if cached_count > 0:
                print(f"  [OCR] Cache hit: {cached_count}/{total} pages already cached")
                if cached_count >= total:
                    print(f"  [OCR] All pages cached, skipping OCR service calls")
            else:
                print(f"  [OCR] No cache found, will OCR {total} pages")

        all_cached = cached_count >= total

        for page_num in range(1, total + 1):
            # Report OCR progress via WebSocket
            if doc_id and report_progress:
                progress = 5.0 + (page_num / total) * 20.0  # OCR uses 5%-25% range
                report_progress(
                    doc_id, "ocr", progress,
                    message=f"加载缓存第 {page_num}/{total} 页..."
                    if all_cached
                    else f"OCR 识别第 {page_num}/{total} 页...",
                )

            md_text = self.ocr_client.ocr_page(pdf_path, page_num)
            tokens = self._estimate_tokens(md_text)
            labeled = f"<physical_index_{page_num}>\n{md_text}"
            has_table = bool(md_text and "|" in md_text and "---" in md_text)

            pages.append(PDFPage(
                page_number=page_num,
                text=md_text,
                tokens=tokens,
                has_table=has_table,
                labeled_content=labeled,
            ))

            if self.debug and not all_cached:
                print(f"  [OCR] Page {page_num}/{total}: {tokens} tokens")

        if self.debug:
            new_ocr = max(0, total - cached_count)
            print(f"  [OCR] Complete: {len(pages)} pages "
                  f"({min(cached_count, total)} from cache, {new_ocr} from OCR service)")

        return pages

    def _is_poor_extraction(self, text: str) -> bool:
        """
        Detect if text extraction quality is poor
        Returns True if extraction appears broken (e.g., character separation)
        """
        if not text or len(text) < 100:
            return False
        
        words = text.split()
        if len(words) < 20:
            return False
        
        # Check percentage of single-character words
        # Poor extraction: >80% single character words (like "M a d s" instead of "Mads")
        single_char_words = sum(1 for w in words if len(w) == 1)
        single_char_ratio = single_char_words / len(words)
        
        # Check average word length
        # Poor extraction: avg < 1.5 chars per word
        avg_word_length = sum(len(w) for w in words) / len(words)
        
        is_poor = single_char_ratio > 0.80 or avg_word_length < 1.5
        
        if self.debug and is_poor:
            print(f"[PDF] Quality check: {single_char_ratio:.1%} single-char words, avg word length: {avg_word_length:.2f}")
        
        return is_poor
    
    def get_labeled_content_batch(
        self,
        pages: List[PDFPage],
        start_idx: int = 0,
        end_idx: Optional[int] = None
    ) -> str:
        """
        Get concatenated labeled content for multiple pages
        Used for TOC matching
        """
        if end_idx is None:
            end_idx = len(pages)
        
        labeled_pages = [p.labeled_content for p in pages[start_idx:end_idx]]
        return "\n\n".join(labeled_pages)


def get_page_text_with_labels(pages: List[PDFPage], page_num: int) -> str:
    """Helper to get specific page text by page number (1-indexed)"""
    for page in pages:
        if page.page_number == page_num:
            return page.labeled_content
    return ""
