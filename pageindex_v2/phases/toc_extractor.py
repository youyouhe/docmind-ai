"""
TOC Extractor - Extract and structure TOC with Chinese optimization
Handles hierarchical TOC with structure codes (1, 1.1, 1.1.1, etc.)
"""
import re
from typing import List, Dict, Any
from ..core.llm_client import LLMClient
from ..utils.error_handler import is_fatal_llm_error, handle_fatal_error
from ..utils.helpers import extract_json


class TOCExtractor:
    """
    Extract structured TOC from raw TOC content
    Supports Chinese section numbering and mixed formats
    """
    
    def __init__(self, llm: LLMClient, debug: bool = True):
        self.llm = llm
        self.debug = debug
    
    async def extract_structure(
        self,
        toc_content: str,
        has_page_numbers: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Extract structured TOC from raw TOC text
        
        Args:
            toc_content: Raw TOC text content
            has_page_numbers: Whether TOC has explicit page numbers
        
        Returns:
            List of structured items with structure codes
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[TOC EXTRACTOR] Transforming TOC to structured format")
            print(f"{'='*60}")
            print(f"[TOC] Content length: {len(toc_content)} chars")
            print(f"[TOC] Has page numbers: {has_page_numbers}")
        
        # Clean up TOC format
        cleaned_content = self._preprocess_toc(toc_content)
        
        # Extract structure using LLM
        structure = await self._transform_toc(cleaned_content, has_page_numbers)
        
        if self.debug:
            print(f"[TOC] Extracted {len(structure)} items")
            for i, item in enumerate(structure[:5], 1):
                struct = item.get('structure', '?')
                title = item.get('title', '')
                page = item.get('page', 'N/A')
                print(f"  {i}. [{struct}] {title} (p.{page})")
            if len(structure) > 5:
                print(f"  ... and {len(structure) - 5} more")
            print(f"{'='*60}\n")
        
        return structure
    
    def _preprocess_toc(self, text: str) -> str:
        """Preprocess TOC text for better extraction"""
        import re
        
        # Replace dots used for alignment with colons
        text = re.sub(r'\.{5,}', ': ', text)
        text = re.sub(r'(?:\. ){5,}\.?', ': ', text)
        
        # Normalize Chinese chapter markers
        text = re.sub(r'第\s*([一二三四五六七八九十百千万]+)\s*章', r'第\1章', text)
        text = re.sub(r'第\s*(\d+)\s*章', r'第\1章', text)
        
        return text
    
    async def _transform_toc(
        self,
        toc_content: str,
        has_page_numbers: bool
    ) -> List[Dict[str, Any]]:
        """Transform TOC to structured JSON using LLM"""
        
        system_prompt = """Extract table of contents to JSON format.

Output: {"table_of_contents": [{"structure": "1.1", "title": "...", "page": 5}]}

Rules:
- structure: "1" (chapter), "1.1" (section), "1.1.1" (subsection)
- Chinese chapters: "第一章" → structure="1", keep title as-is
- Preserve exact titles, extract page numbers, maintain hierarchy
- Include ALL sections

Return JSON only."""
        
        # Split if content too long (process in chunks)
        # NOTE: Increased from 8000 to 32000 after testing with PRML.pdf
        # Single-batch processing is faster and more accurate than chunking
        max_chunk_size = 32000
        if len(toc_content) > max_chunk_size:
            return await self._transform_large_toc(toc_content, has_page_numbers)
        
        prompt = f"""TOC text:

{toc_content}

Extract to JSON."""
        
        try:
            result = await self.llm.chat_json(
                prompt, 
                system=system_prompt,
                max_tokens=8000  # Allow long TOC output (up to ~150 items)
            )
            toc_list = result.get("table_of_contents", [])
            
            # Validate and clean
            return self._validate_structure(toc_list)
            
        except Exception as e:
            # Check for fatal errors
            if is_fatal_llm_error(e):
                handle_fatal_error(e, "TOC extraction")
            
            # Non-fatal error
            if self.debug:
                print(f"[ERROR] TOC transformation failed: {e}")
            return []
    
    async def _transform_large_toc(
        self,
        toc_content: str,
        has_page_numbers: bool
    ) -> List[Dict[str, Any]]:
        """Handle large TOC by processing in chunks with continuation"""
        
        max_chunk_size = 8000
        chunks = [toc_content[i:i+max_chunk_size] for i in range(0, len(toc_content), max_chunk_size)]
        
        if self.debug:
            print(f"[TOC] Large TOC detected, processing in {len(chunks)} chunks")
        
        all_items = []
        previous_structure = []
        
        for i, chunk in enumerate(chunks):
            if self.debug:
                print(f"[TOC] Processing chunk {i + 1}/{len(chunks)}")
            
            system_prompt = f"""Extract table of contents from chunk {i+1} of {len(chunks)} to JSON format.

Previous sections extracted:
{previous_structure[-5:] if previous_structure else "None"}

Continue the structure numbering from where previous chunk left off.

Output JSON format:
{{
    "table_of_contents": [
        {{"structure": "x.x", "title": "...", "page": N}}
    ],
    "is_complete": "yes/no"
}}

Return JSON only."""
            
            prompt = f"""TOC chunk {i + 1}/{len(chunks)}:

{chunk}

Extract to JSON and continue numbering from previous sections."""
            
            try:
                result = await self.llm.chat_json(
                    prompt, 
                    system=system_prompt,
                    max_tokens=8000  # Allow long TOC output per chunk
                )
                chunk_items = result.get("table_of_contents", [])
                all_items.extend(chunk_items)
                previous_structure.extend(chunk_items)
                
                # Check if complete
                if result.get("is_complete") == "yes":
                    break
                    
            except Exception as e:
                # Check for fatal errors
                if is_fatal_llm_error(e):
                    handle_fatal_error(e, f"TOC extraction (chunk {i+1}/{len(chunks)})")
                
                # Non-fatal error
                if self.debug:
                    print(f"[ERROR] Chunk {i + 1} failed: {e}")
                continue
        
        return self._validate_structure(all_items)
    
    def _validate_structure(self, items: List[Dict]) -> List[Dict]:
        """Validate and clean extracted structure"""
        valid_items = []
        
        for item in items:
            if not isinstance(item, dict):
                continue
            
            title = item.get('title', '').strip()
            if not title:
                continue
            
            # Clean up structure code
            struct = item.get('structure', '')
            if struct:
                # Normalize structure code
                struct = str(struct).strip()
                # Remove trailing dots
                struct = struct.rstrip('.')
            
            # Convert page to int if possible
            page = item.get('page')
            if isinstance(page, str):
                try:
                    page = int(page)
                except:
                    page = None
            
            valid_items.append({
                'structure': struct,
                'title': title,
                'page': page
            })
        
        return valid_items
    
    async def fix_incomplete_toc(
        self,
        original_toc: str,
        incomplete_structure: List[Dict]
    ) -> List[Dict]:
        """
        Fix incomplete TOC extraction by re-processing
        """
        if self.debug:
            print(f"[TOC] Attempting to fix incomplete extraction")
        
        # Re-extract with emphasis on completeness
        system_prompt = """
        The previous TOC extraction was incomplete. Extract ALL sections from the original TOC.

        Requirements:
        1. Include EVERY section from the original TOC
        2. Maintain correct hierarchy
        3. Capture exact titles

        Return complete JSON structure.
        """
        
        prompt = f"""
        Original TOC (extract ALL sections):
        ---
        {original_toc}
        ---

        Previously extracted (incomplete):
        {incomplete_structure}

        Return complete structure.
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt)
            return self._validate_structure(result.get("table_of_contents", []))
        except:
            return incomplete_structure
