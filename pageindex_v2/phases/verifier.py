"""
Verifier - Dual validation for TOC accuracy
Validates: 1) Title existence, 2) Title appears at page start
"""
import re
import asyncio
from typing import List, Dict, Tuple
from ..core.llm_client import LLMClient
from ..utils.error_handler import is_fatal_llm_error, handle_fatal_error


class Verifier:
    """
    Double verification system:
    1. Check if title actually exists on the assigned page
    2. Check if title appears at the beginning of the page (DISABLED for speed)
    """
    
    def __init__(self, llm: LLMClient, debug: bool = True, concurrency: int = 20):
        self.llm = llm
        self.debug = debug
        self.concurrency = concurrency  # Configurable concurrency
    
    async def verify_structure(
        self,
        structure: List[Dict],
        pages: List,
        page_offset: int = 0
    ) -> Tuple[List[Dict], float]:
        """
        Verify entire structure
        
        Args:
            structure: List of TOC items to verify
            pages: List of PDFPage objects (may be a subset)
            page_offset: Offset to adjust global page numbers to local indices (default 0)
        
        Returns:
            (verified_structure, accuracy_ratio)
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[VERIFIER] Starting verification (existence check only)")
            print(f"{'='*60}")
        
        # Verification 1: Check title existence
        existence_results = await self._verify_existence(structure, pages, page_offset)
        
        # OPTIMIZATION: Skip Phase 2 (start position check)
        # Reason: Only need to verify existence, position check adds 2x time with minimal value
        # start_results = await self._verify_start_position(structure, pages)
        start_results = {}  # Empty - skip position verification
        
        # Merge results
        verified = []
        correct_count = 0
        
        for item in structure:
            idx = item.get('list_index', 0)
            
            # Check both verifications
            exists = existence_results.get(idx, False)
            at_start = start_results.get(idx, False)
            
            # Mark item with verification status
            verified_item = {
                **item,
                'verified_existence': exists,
                'verified_start': at_start,
                'verification_passed': exists  # Must exist, start is optional
            }
            
            if exists:
                correct_count += 1
            
            verified.append(verified_item)
        
        accuracy = correct_count / len(structure) if structure else 0.0
        
        if self.debug:
            print(f"\n[VERIFIER] Verification complete")
            print(f"  Total items: {len(structure)}")
            print(f"  Passed: {correct_count}")
            print(f"  Failed: {len(structure) - correct_count}")
            print(f"  Accuracy: {accuracy:.1%}")
            print(f"{'='*60}\n")
        
        return verified, accuracy
    
    async def _verify_existence(
        self,
        structure: List[Dict],
        pages: List,
        page_offset: int = 0
    ) -> Dict[int, bool]:
        """
        Verification 1: Check if title exists on assigned page
        Uses batch parallel processing for better performance
        
        Args:
            structure: List of TOC items
            pages: List of PDFPage objects (may be a subset)
            page_offset: Offset to convert global page numbers to local indices
        """
        if self.debug:
            print(f"[VERIFIER] Phase 1: Checking title existence on {len(structure)} items")
            print(f"[VERIFIER] Using parallel processing with {self.concurrency} concurrent calls")
        
        # Use configurable concurrency
        semaphore = asyncio.Semaphore(self.concurrency)
        
        # Progress tracking
        completed = 0
        total = len(structure)
        
        async def check_one(item: Dict) -> Tuple[int, bool]:
            nonlocal completed
            async with semaphore:
                idx = item.get('list_index', 0)
                title = item.get('title', '')
                page_num = item.get('physical_index')
                
                if not page_num or not title:
                    completed += 1
                    return idx, False
                
                # Get page content
                # Convert global page number to local index using offset
                if page_num < 1 or page_num > len(pages) + page_offset:
                    completed += 1
                    return idx, False
                
                local_index = page_num - page_offset - 1
                if local_index < 0 or local_index >= len(pages):
                    completed += 1
                    return idx, False
                
                page_content = pages[local_index].text[:2000]  # First 2000 chars

                # Pre-check: fuzzy string matching before LLM call
                # This handles OCR text with extra spaces/formatting differences
                normalized_title = re.sub(r'\s+', '', title)
                normalized_page = re.sub(r'\s+', '', page_content)

                # Quick check: if title appears in page content (whitespace-insensitive),
                # and page has substantial content (not just a TOC listing), mark as found
                title_found_in_text = normalized_title in normalized_page
                page_has_content = len(page_content.strip()) > 200  # More than just a listing

                if title_found_in_text and page_has_content:
                    # Title found via string matching and page has real content
                    # Skip expensive LLM call
                    completed += 1
                    if self.debug and completed % 20 == 0:
                        print(f"  Progress: {completed}/{total} ({completed*100//total}%)")
                    return idx, True

                system_prompt = """
                Check if the section title appears in the page content as a real section heading.

                Distinguish between:
                - Real section heading (actual chapter/section start with content)
                - TOC reference (listing in table of contents without content)

                Use fuzzy matching for minor spacing/formatting differences.
                Note: OCR-processed text may have extra spaces or slightly different formatting.

                Reply JSON:
                {
                    "reasoning": "Brief explanation",
                    "exists": "yes" or "no",
                    "is_toc_page": "yes" or "no"
                }
                """

                prompt = f"""
                Section title: "{title}"

                Page content (first 2000 chars):
                ---
                {page_content}
                ---

                Does the title appear as a REAL section heading (not just in a TOC list)?
                """

                try:
                    result = await self.llm.chat_json(prompt, system=system_prompt)
                    exists = result.get("exists", "no").lower() == "yes"
                    is_toc_page = result.get("is_toc_page", "no").lower() == "yes"
                    
                    # Update progress
                    completed += 1
                    if self.debug and completed % 20 == 0:
                        print(f"  Progress: {completed}/{total} ({completed*100//total}%)")
                    
                    if self.debug:
                        if not exists:
                            print(f"  ⚠ Item {idx}: '{title[:40]}...' not found on page {page_num}")
                        elif is_toc_page:
                            print(f"  ⚠ Item {idx}: '{title[:40]}...' found on page {page_num} (but it's a TOC reference)")
                    
                    # If it's a TOC reference, treat as not found (will trigger smart fixer)
                    if is_toc_page:
                        return idx, False
                    
                    return idx, exists
                    
                except Exception as e:
                    # Check for fatal errors
                    if is_fatal_llm_error(e):
                        handle_fatal_error(e, f"Verification (item {idx})")
                    
                    # Non-fatal error
                    completed += 1
                    if self.debug:
                        print(f"  [ERROR] Verification failed for item {idx}: {e}")
                    return idx, False
        
        # Run all checks concurrently
        tasks = [check_one(item) for item in structure]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        if self.debug:
            print(f"  Progress: {completed}/{total} (100%) - Complete!")
        
        # Build result dict
        existence_map = {}
        for r in results:
            if isinstance(r, Exception):
                continue
            idx, exists = r
            existence_map[idx] = exists
        
        return existence_map
    
    async def _verify_start_position(
        self,
        structure: List[Dict],
        pages: List,
        page_offset: int = 0
    ) -> Dict[int, bool]:
        """
        Verification 2: Check if title appears at the beginning of the page
        Uses batch parallel processing for better performance
        
        Args:
            structure: List of TOC items
            pages: List of PDFPage objects (may be a subset)
            page_offset: Offset to convert global page numbers to local indices
        """
        if self.debug:
            print(f"[VERIFIER] Phase 2: Checking title position (start of page)")
        
        # Increase concurrency for better performance
        semaphore = asyncio.Semaphore(20)  # Allow 20 concurrent LLM calls
        
        async def check_start(item: Dict) -> Tuple[int, bool]:
            async with semaphore:
                idx = item.get('list_index', 0)
                title = item.get('title', '')
                page_num = item.get('physical_index')
                
                if not page_num or not title:
                    return idx, False
                
                local_index = page_num - page_offset - 1
                if local_index < 0 or local_index >= len(pages):
                    return idx, False
                
                # Get first 1000 chars of page
                page_start = pages[local_index].text[:1000]
                
                system_prompt = """
                Check if the section title appears at the BEGINNING of the page.
                
                "Beginning" means:
                - Title is within first 500 characters
                - Title is the first meaningful content (after headers/footers)
                - No other section titles appear before it
                
                Reply JSON:
                {
                    "reasoning": "Position analysis",
                    "at_start": "yes" or "no"
                }
                """
                
                prompt = f"""
                Section title: "{title}"
                
                Page start (first 1000 chars):
                ---
                {page_start}
                ---
                
                Does this title appear at the beginning of the page?
                """
                
                try:
                    result = await self.llm.chat_json(prompt, system=system_prompt)
                    at_start = result.get("at_start", "no").lower() == "yes"
                    return idx, at_start
                    
                except Exception:
                    return idx, False
        
        # Check only items that passed existence verification
        items_to_check = [item for item in structure if item.get('physical_index')]
        
        if not items_to_check:
            return {}
        
        tasks = [check_start(item) for item in items_to_check]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        start_map = {}
        for r in results:
            if isinstance(r, Exception):
                continue
            idx, at_start = r
            start_map[idx] = at_start
        
        return start_map
    
    async def fix_incorrect_items(
        self,
        structure: List[Dict],
        incorrect_items: List[Dict],
        pages: List,
        max_attempts: int = 3,
        page_offset: int = 0
    ) -> List[Dict]:
        """
        Attempt to fix incorrect mappings using smart range search
        
        Strategy (from original PageIndex):
        1. Find previous correct item's page
        2. Find next correct item's page
        3. Search only in that range
        4. Verify the fix before accepting
        
        Args:
            structure: Full structure (for context)
            incorrect_items: Items that failed verification
            pages: List of PDFPage objects (may be a subset)
            max_attempts: Maximum retry attempts (not used in this version)
            page_offset: Offset to convert global page numbers to local indices
        
        Returns:
            Fixed items (some may still be unfixed)
        """
        if self.debug:
            print(f"\n[VERIFIER] Smart fixing: {len(incorrect_items)} incorrect items")
        
        # Build incorrect set for quick lookup
        incorrect_indices = {item.get('list_index') for item in incorrect_items}
        
        # Increase concurrency for better performance
        semaphore = asyncio.Semaphore(10)  # Allow 10 concurrent fix operations
        
        async def fix_one_item(item: Dict) -> Dict:
            async with semaphore:
                list_idx = item.get('list_index')
                title = item.get('title', '')
                current_page = item.get('physical_index')
                
                # Skip items without physical_index
                if current_page is None:
                    if self.debug:
                        print(f"  Item {list_idx}: '{title[:40]}...' - No physical_index, cannot fix")
                    return {
                        **item,
                        'fix_failed': True,
                        'fix_reason': 'no_physical_index'
                    }
                
                # Find search range: [prev_correct, next_correct]
                prev_correct = None
                for i in range(list_idx - 1, -1, -1):
                    if i not in incorrect_indices:
                        candidate = structure[i].get('physical_index')
                        if candidate is not None:
                            prev_correct = candidate
                            break
                
                if prev_correct is None:
                    prev_correct = page_offset + 1  # Start of this subset (global page number)
                
                next_correct = None
                for i in range(list_idx + 1, len(structure)):
                    if i not in incorrect_indices:
                        candidate = structure[i].get('physical_index')
                        if candidate is not None:
                            next_correct = candidate
                            break
                
                if next_correct is None:
                    next_correct = page_offset + len(pages)  # End of this subset (global page number)
                
                if self.debug:
                    print(f"  Item {list_idx}: '{title[:40]}...' - Searching pages {prev_correct}-{next_correct}")
                
                # Build content range
                range_content = []
                for page_num in range(prev_correct, next_correct + 1):
                    local_index = page_num - page_offset - 1
                    if 0 <= local_index < len(pages):
                        page = pages[local_index]
                        range_content.append(page.labeled_content)
                
                range_text = "\n\n".join(range_content)
                
                # Use LLM to find the correct page
                system_prompt = """
                Find the correct physical page for this section title.
                
                The content contains <physical_index_X> tags.
                
                Task:
                1. Find where the section title appears
                2. Return the <physical_index_X> tag
                3. If not found, return null
                
                Reply JSON:
                {
                    "physical_index": "<physical_index_X>" or null,
                    "reasoning": "Why this is the correct page"
                }
                """
                
                prompt = f"""
                Section title: "{title}"
                
                Search range content:
                ---
                {range_text[:25000]}
                ---
                
                Find the correct physical page for this section.
                """
                
                try:
                    result = await self.llm.chat_json(prompt, system=system_prompt)
                    new_physical_index = result.get("physical_index")
                    
                    if new_physical_index:
                        # Convert tag to int
                        from utils.helpers import convert_physical_index_to_int
                        temp_item = {'physical_index': new_physical_index}
                        converted = convert_physical_index_to_int([temp_item])
                        new_page_num = converted[0].get('physical_index')
                        
                        if new_page_num and new_page_num != current_page:
                            # Verify the fix
                            if await self._verify_single_item(
                                title, new_page_num, pages, page_offset
                            ):
                                if self.debug:
                                    print(f"    ✓ Fixed: {current_page} → {new_page_num}")
                                return {
                                    **item,
                                    'physical_index': new_page_num,
                                    'fixed': True,
                                    'original_page': current_page,
                                    'verification_passed': True,  # Mark as verified after successful fix
                                    'verified_existence': True
                                }
                            else:
                                if self.debug:
                                    print(f"    ✗ Fix verification failed for page {new_page_num}")
                    
                    # Fix failed
                    if self.debug:
                        print(f"    ✗ Could not find correct page")
                    return {
                        **item,
                        'fix_failed': True,
                        'fix_reason': 'not_found_in_range'
                    }
                    
                except Exception as e:
                    if self.debug:
                        print(f"    ✗ Fix error: {e}")
                    return {
                        **item,
                        'fix_failed': True,
                        'fix_reason': f'error: {str(e)}'
                    }
        
        # Fix all items concurrently
        tasks = [fix_one_item(item) for item in incorrect_items]
        fixed_items = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        result = []
        for item in fixed_items:
            if isinstance(item, Exception):
                if self.debug:
                    print(f"  [ERROR] Fix task failed: {item}")
                continue
            result.append(item)
        
        # Summary
        if self.debug:
            success = sum(1 for item in result if item.get('fixed'))
            failed = len(result) - success
            print(f"[VERIFIER] Fix summary: {success} fixed, {failed} failed")
        
        return result
    
    async def _verify_single_item(
        self,
        title: str,
        page_num: int,
        pages: List,
        page_offset: int = 0
    ) -> bool:
        """
        Quick verification for a single item
        Returns True if title exists on page
        
        Args:
            title: Section title to verify
            page_num: Global page number
            pages: List of PDFPage objects (may be a subset)
            page_offset: Offset to convert global page numbers to local indices
        """
        local_index = page_num - page_offset - 1
        if local_index < 0 or local_index >= len(pages):
            return False
        
        page_content = pages[local_index].text[:2000]
        
        system_prompt = """
        Check if the section title appears in the page content.
        Do fuzzy matching.
        Reply JSON: {"exists": "yes" or "no"}
        """
        
        prompt = f"""
        Title: "{title}"
        Page content: {page_content}
        Does the title appear?
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt)
            return result.get("exists", "no").lower() == "yes"
        except:
            return False
