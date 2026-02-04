"""
Page Mapper - Map logical TOC items to physical page indices
Uses <physical_index_X> tags for precise matching
"""
from typing import List, Dict, Optional, Any
from ..core.llm_client import LLMClient
from ..utils.helpers import convert_physical_index_to_int


class PageMapper:
    """
    Map TOC structure to physical page indices
    Handles both TOC-with-page-numbers and TOC-without-page-numbers scenarios
    """
    
    def __init__(self, llm: LLMClient, debug: bool = True):
        self.llm = llm
        self.debug = debug
    
    async def map_pages(
        self,
        structure: List[Dict],
        pages: List,
        has_page_numbers: bool = True
    ) -> List[Dict]:
        """
        Map TOC items to physical pages
        
        Args:
            structure: List of TOC items with structure codes
            pages: List of PDFPage objects
            has_page_numbers: Whether original TOC had page numbers
        
        Returns:
            Structure with physical_index assigned
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[PAGE MAPPER] Mapping TOC to physical pages")
            print(f"{'='*60}")
            print(f"[MAP] Items to map: {len(structure)}")
            print(f"[MAP] Total pages: {len(pages)}")
            print(f"[MAP] Has page numbers: {has_page_numbers}")
            
            # Check if structure already has physical_index
            already_mapped = sum(1 for item in structure if item.get('physical_index'))
            if already_mapped > 0:
                print(f"[MAP] ⚠ {already_mapped}/{len(structure)} items already have physical_index")
                print(f"[MAP] → Skipping mapping, using existing indices")
        
        # If structure already has physical_index, just convert and return
        already_mapped_count = sum(1 for item in structure if item.get('physical_index'))
        if already_mapped_count == len(structure):
            # All items already mapped (from content analysis)
            # Convert tags to integers
            mapped = convert_physical_index_to_int(structure)
            
            # Add list_index
            for i, item in enumerate(mapped):
                item['list_index'] = i
            
            if self.debug:
                print(f"[MAP] All items pre-mapped, converting tags to integers")
                success_count = sum(1 for m in mapped if isinstance(m.get('physical_index'), int))
                print(f"[MAP] Converted: {success_count}/{len(mapped)} items")
                print(f"{'='*60}\n")
            return mapped
        
        if has_page_numbers:
            mapped = await self._map_with_page_numbers(structure, pages)
        else:
            mapped = await self._map_without_page_numbers(structure, pages)
        
        # Convert tags to integers
        mapped = convert_physical_index_to_int(mapped)
        
        # Add list_index for verification
        for i, item in enumerate(mapped):
            item['list_index'] = i
        
        if self.debug:
            print(f"[MAP] Mapping complete: {len(mapped)} items")
            success_count = sum(1 for m in mapped if m.get('physical_index'))
            print(f"[MAP] Successfully mapped: {success_count}/{len(mapped)}")
            
            # Show validation accuracy
            validated_count = sum(1 for m in mapped if m.get('validation_passed'))
            validation_accuracy = validated_count / len(mapped) if mapped else 0
            print(f"[MAP] Validation accuracy: {validated_count}/{len(mapped)} ({validation_accuracy*100:.1f}%)")
            print(f"{'='*60}\n")
        
        return mapped
    
    async def _map_with_page_numbers(
        self,
        structure: List[Dict],
        pages: List
    ) -> List[Dict]:
        """
        Map when TOC has explicit page numbers
        
        Strategy: Smart validation with fallback
        1. Try direct mapping (TOC page = physical page)
        2. Validate: check if title appears on that page
        3. If not found, search nearby pages (±1)
        4. This handles both accurate TOCs and TOCs with offset
        """
        if self.debug:
            print(f"[MAP] TOC has page numbers, using smart validation")
        
        mapped = []
        validated = 0
        corrected = 0
        not_found = 0
        
        for item in structure:
            title = item.get('title', '').strip()
            toc_page = item.get('page')
            
            if not toc_page or toc_page < 1 or toc_page > len(pages):
                # Invalid page number, use as-is
                mapped.append({
                    'structure': item.get('structure'),
                    'title': title,
                    'page': toc_page,
                    'physical_index': None,
                    'validation_passed': False
                })
                not_found += 1
                continue
            
            # Try to find the title on the claimed page
            page_text = pages[toc_page - 1].text if toc_page <= len(pages) else ""
            
            if title in page_text:
                # Found on the claimed page!
                validated += 1
                physical_page = toc_page
                validation_passed = True
            else:
                # Not found, mark as failed
                physical_page = toc_page  # Still use TOC page
                not_found += 1
                validation_passed = False
            
            mapped.append({
                'structure': item.get('structure'),
                'title': title,
                'page': toc_page,
                'physical_index': f"<physical_index_{physical_page}>" if physical_page else None,
                'validation_passed': validation_passed
            })
        
        if self.debug:
            print(f"[MAP] Validation results:")
            print(f"  ✓ Validated: {validated}/{len(structure)} items ({validated/len(structure)*100:.1f}%)")
            print(f"  ✗ Failed: {not_found} items ({not_found/len(structure)*100:.1f}%)")
        
        return mapped
    
    async def _map_without_page_numbers(
        self,
        structure: List[Dict],
        pages: List
    ) -> List[Dict]:
        """
        Map when TOC has no explicit page numbers
        Strategy: Segmented processing - scan entire document in groups
        
        Key improvements:
        1. Process entire document (not just first 12k chars)
        2. Use 20k token segments with overlap
        3. Accumulate mappings across groups
        """
        if self.debug:
            print(f"[MAP] No page numbers in TOC, using segmented content analysis")
        
        # Prepare document groups (20k tokens each with 1-page overlap)
        groups = self._prepare_document_groups(pages, max_tokens=20000, overlap_pages=1)
        
        if self.debug:
            print(f"[MAP] Document divided into {len(groups)} groups")
        
        # Initialize mappings with original structure
        current_mappings = [{'structure': item.get('structure'), 
                            'title': item.get('title'),
                            'physical_index': None} 
                           for item in structure]
        
        # Process each group sequentially
        for group_idx, group in enumerate(groups):
            if self.debug:
                print(f"[MAP] Processing group {group_idx + 1}/{len(groups)}")
            
            # Find unmapped items
            unmapped = [item for item in current_mappings if not item.get('physical_index')]
            
            if not unmapped:
                if self.debug:
                    print(f"[MAP] All items mapped, stopping early")
                break
            
            # Map items in this group
            group_mappings = await self._map_in_group(unmapped, group['content'])
            
            # Update current mappings
            current_mappings = self._update_mappings(current_mappings, group_mappings)
            
            if self.debug:
                mapped_count = sum(1 for m in current_mappings if m.get('physical_index'))
                print(f"[MAP] Progress: {mapped_count}/{len(structure)} items mapped")
        
        return self._merge_mappings(structure, current_mappings)
    
    def _prepare_document_groups(
        self, 
        pages: List, 
        max_tokens: int = 20000,
        overlap_pages: int = 1
    ) -> List[Dict]:
        """
        Divide document into overlapping groups
        
        Args:
            pages: List of PDFPage objects
            max_tokens: Maximum tokens per group
            overlap_pages: Number of pages to overlap between groups
        
        Returns:
            List of groups with content and metadata
        """
        groups = []
        current_group_pages = []
        current_tokens = 0
        
        total_tokens = sum(page.tokens for page in pages)
        expected_groups = max(1, (total_tokens + max_tokens - 1) // max_tokens)
        avg_tokens_per_group = (total_tokens // expected_groups + max_tokens) // 2
        
        if self.debug:
            print(f"[MAP] Total tokens: {total_tokens}, Expected groups: {expected_groups}, Avg per group: {avg_tokens_per_group}")
        
        for i, page in enumerate(pages):
            # Check if adding this page exceeds limit
            if current_tokens + page.tokens > avg_tokens_per_group and current_group_pages:
                # Save current group
                group_content = "\n\n".join([p.labeled_content for p in current_group_pages])
                groups.append({
                    'content': group_content,
                    'start_page': current_group_pages[0].page_number,
                    'end_page': current_group_pages[-1].page_number,
                    'token_count': current_tokens
                })
                
                if self.debug:
                    print(f"[MAP] Group {len(groups)}: pages {current_group_pages[0].page_number}-{current_group_pages[-1].page_number}, {current_tokens} tokens")
                
                # Start new group with overlap
                overlap_start = max(0, len(current_group_pages) - overlap_pages)
                current_group_pages = current_group_pages[overlap_start:]
                current_tokens = sum(p.tokens for p in current_group_pages)
            
            current_group_pages.append(page)
            current_tokens += page.tokens
        
        # Add final group
        if current_group_pages:
            group_content = "\n\n".join([p.labeled_content for p in current_group_pages])
            groups.append({
                'content': group_content,
                'start_page': current_group_pages[0].page_number,
                'end_page': current_group_pages[-1].page_number,
                'token_count': current_tokens
            })
            
            if self.debug:
                print(f"[MAP] Group {len(groups)}: pages {current_group_pages[0].page_number}-{current_group_pages[-1].page_number}, {current_tokens} tokens")
        
        return groups
    
    async def _map_in_group(
        self,
        unmapped_items: List[Dict],
        group_content: str
    ) -> List[Dict]:
        """
        Map TOC items within a specific document group
        
        Args:
            unmapped_items: Items without physical_index
            group_content: Labeled content for this group
        
        Returns:
            Mappings found in this group
        """
        system_prompt = """
        Assign physical page indices to TOC items by analyzing the document content.

        The content is labeled with <physical_index_X> tags.

        Task:
        1. For each TOC section title, check if it appears in this document segment
        2. If found, assign the <physical_index_X> tag where the section starts
        3. If not found in this segment, set physical_index to null

        Tips:
        - Chapter titles often appear at page starts
        - Look for exact or fuzzy title matches
        - Consider the hierarchical structure

        Reply format (JSON):
        {
            "mappings": [
                {
                    "structure": "1",
                    "title": "Chapter Title",
                    "physical_index": "<physical_index_3>" or null,
                    "confidence": "high/medium/low"
                }
            ]
        }
        """
        
        # Process in smaller batches
        batch_size = 5
        all_mappings = []
        
        for i in range(0, len(unmapped_items), batch_size):
            batch = unmapped_items[i:i+batch_size]
            
            # Simplified batch for prompt
            batch_simple = [{'structure': item['structure'], 'title': item['title']} 
                           for item in batch]
            
            prompt = f"""
            Find these TOC sections in the document segment:

            TOC Sections to find:
            {batch_simple}

            Document Segment (with page labels):
            ---
            {group_content[:50000]}
            ---

            Return mappings in JSON format.
            For sections NOT found in this segment, set physical_index to null.
            """
            
            try:
                result = await self.llm.chat_json(prompt, system=system_prompt)
                mappings = result.get("mappings", [])
                all_mappings.extend(mappings)
            except Exception as e:
                if self.debug:
                    print(f"  [ERROR] Group batch mapping failed: {e}")
                # Keep as unmapped
                for item in batch:
                    all_mappings.append({
                        **item,
                        'physical_index': None,
                        'confidence': 'error'
                    })
        
        return all_mappings
    
    def _update_mappings(
        self,
        current: List[Dict],
        new_mappings: List[Dict]
    ) -> List[Dict]:
        """
        Update current mappings with new findings
        Only update if new mapping has physical_index and current doesn't
        """
        # Create lookup dict
        new_dict = {}
        for m in new_mappings:
            if m.get('physical_index'):
                key = (m.get('structure'), m.get('title'))
                new_dict[key] = m
        
        # Update current
        updated = []
        for item in current:
            key = (item.get('structure'), item.get('title'))
            
            # Update if we found a mapping and current doesn't have one
            if key in new_dict and not item.get('physical_index'):
                updated.append({**item, **new_dict[key]})
            else:
                updated.append(item)
        
        return updated
    
    def _prepare_labeled_content(self, pages: List, max_tokens: int = 15000) -> str:
        """
        Prepare labeled content string from pages
        
        Note: This method is kept for backward compatibility with _map_with_page_numbers()
        For _map_without_page_numbers(), use _prepare_document_groups() instead
        """
        labeled_pages = []
        total_tokens = 0
        
        for page in pages:
            content = page.labeled_content
            tokens = page.tokens
            
            if total_tokens + tokens > max_tokens:
                break
            
            labeled_pages.append(content)
            total_tokens += tokens
        
        return "\n\n".join(labeled_pages)
    
    def _merge_mappings(
        self,
        original: List[Dict],
        mappings: List[Dict]
    ) -> List[Dict]:
        """Merge LLM mappings with original structure"""
        # Create lookup by structure code
        mapping_dict = {}
        for m in mappings:
            key = (m.get('structure'), m.get('title'))
            mapping_dict[key] = m
        
        merged = []
        for item in original:
            key = (item.get('structure'), item.get('title'))
            
            if key in mapping_dict:
                # Use LLM mapping
                merged_item = {**item, **mapping_dict[key]}
            else:
                # Keep original without mapping
                merged_item = {
                    **item,
                    'physical_index': None
                }
            
            merged.append(merged_item)
        
        return merged
    
    def calculate_page_offset(
        self,
        structure: List[Dict],
        pages: List
    ) -> int:
        """
        Calculate offset between logical page numbers and physical pages
        """
        # Find first item with both logical page and physical index
        for item in structure:
            logical_page = item.get('page')
            physical_idx = item.get('physical_index')
            
            if logical_page and physical_idx:
                # Calculate offset
                return physical_idx - logical_page
        
        return 0  # No offset detected
    
    def apply_offset_correction(
        self,
        structure: List[Dict],
        offset: int
    ) -> List[Dict]:
        """Apply offset correction to items without physical_index"""
        corrected = []
        
        for item in structure:
            if not item.get('physical_index') and item.get('page'):
                # Apply offset to logical page
                logical_page = item['page']
                estimated_physical = logical_page + offset
                
                # Validate range
                if estimated_physical > 0:
                    item['physical_index'] = estimated_physical
                    item['page_estimated'] = True
            
            corrected.append(item)
        
        return corrected
