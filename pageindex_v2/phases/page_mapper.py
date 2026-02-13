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

        Strategy: Smart validation with offset detection
        1. Try direct mapping (TOC page = physical page)
        2. Validate: check if title appears on that page
        3. If validation rate is low (<50%), detect page offset by searching
           for titles across all pages
        4. Re-map with corrected offset
        """
        if self.debug:
            print(f"[MAP] TOC has page numbers, using smart validation")

        # First pass: try direct mapping
        mapped, validated, not_found = self._validate_page_mapping(structure, pages, offset=0)

        validation_rate = validated / len(structure) if structure else 0

        if self.debug:
            print(f"[MAP] Direct mapping validation: {validated}/{len(structure)} ({validation_rate*100:.1f}%)")

        # If validation rate is low, try to detect page offset
        if validation_rate < 0.5 and len(structure) > 0:
            if self.debug:
                print(f"[MAP] Low validation rate ({validation_rate*100:.0f}%), attempting offset detection...")

            detected_offset = self._detect_page_offset(structure, pages)

            if detected_offset != 0:
                if self.debug:
                    print(f"[MAP] Detected page offset: {detected_offset:+d}")
                    print(f"[MAP] Re-mapping with offset correction...")

                # Re-map with detected offset
                new_mapped, new_validated, new_not_found = self._validate_page_mapping(
                    structure, pages, offset=detected_offset
                )

                new_rate = new_validated / len(structure) if structure else 0
                if self.debug:
                    print(f"[MAP] After offset correction: {new_validated}/{len(structure)} ({new_rate*100:.1f}%)")

                # Only apply offset if it actually improves validation rate
                if new_validated > validated:
                    mapped = new_mapped
                    validated = new_validated
                    not_found = new_not_found
                    if self.debug:
                        print(f"[MAP] Offset improved validation, applying offset {detected_offset:+d}")
                else:
                    if self.debug:
                        print(f"[MAP] Offset did NOT improve validation ({new_validated} vs {validated}), keeping direct mapping")
            else:
                if self.debug:
                    print(f"[MAP] Could not detect page offset")

        if self.debug:
            print(f"[MAP] Final validation results:")
            print(f"  ✓ Validated: {validated}/{len(structure)} items ({validated/len(structure)*100:.1f}%)")
            print(f"  ✗ Failed: {not_found} items ({not_found/len(structure)*100:.1f}%)")

        return mapped

    def _validate_page_mapping(
        self,
        structure: List[Dict],
        pages: List,
        offset: int = 0
    ) -> tuple:
        """
        Validate TOC page numbers against physical pages with optional offset.

        Args:
            structure: TOC items with 'page' field
            pages: PDFPage objects
            offset: Page offset (physical_page = toc_page + offset)

        Returns:
            (mapped_items, validated_count, not_found_count)
        """
        mapped = []
        validated = 0
        not_found = 0

        for item in structure:
            title = item.get('title', '').strip()
            toc_page = item.get('page')

            if not toc_page:
                mapped.append({
                    'structure': item.get('structure'),
                    'title': title,
                    'page': toc_page,
                    'physical_index': None,
                    'validation_passed': False
                })
                not_found += 1
                continue

            physical_page = toc_page + offset

            if physical_page < 1:
                mapped.append({
                    'structure': item.get('structure'),
                    'title': title,
                    'page': toc_page,
                    'physical_index': None,
                    'validation_passed': False
                })
                not_found += 1
                continue

            if physical_page > len(pages):
                # Page beyond loaded range — still assign physical_index
                # (will be verified later when remaining pages are loaded)
                mapped.append({
                    'structure': item.get('structure'),
                    'title': title,
                    'page': toc_page,
                    'physical_index': f"<physical_index_{physical_page}>",
                    'validation_passed': False
                })
                not_found += 1
                continue

            page_text = pages[physical_page - 1].text

            # Use fuzzy matching: check if title (or significant substring) is in page
            if self._title_in_page(title, page_text):
                validated += 1
                validation_passed = True
            else:
                not_found += 1
                validation_passed = False

            mapped.append({
                'structure': item.get('structure'),
                'title': title,
                'page': toc_page,
                'physical_index': f"<physical_index_{physical_page}>" if physical_page else None,
                'validation_passed': validation_passed
            })

        return mapped, validated, not_found

    def _title_in_page(self, title: str, page_text: str) -> bool:
        """
        Check if a title appears in page text with fuzzy matching.
        Handles OCR artifacts like extra spaces, different whitespace, etc.
        """
        if not title or not page_text:
            return False

        # Direct match
        if title in page_text:
            return True

        # Normalize whitespace for comparison (OCR often adds extra spaces)
        import re
        normalized_title = re.sub(r'\s+', '', title)
        normalized_page = re.sub(r'\s+', '', page_text)

        if normalized_title in normalized_page:
            return True

        # Try first 2000 chars of page with whitespace-insensitive comparison
        page_start = page_text[:2000]
        normalized_start = re.sub(r'\s+', '', page_start)

        if normalized_title in normalized_start:
            return True

        return False

    def _detect_page_offset(self, structure: List[Dict], pages: List) -> int:
        """
        Detect page offset by searching for TOC titles across all pages.

        Strategy:
        1. Identify TOC listing pages (pages that match 3+ titles) and skip them
        2. For each title, find the content page where it appears as a heading
        3. Calculate offset = found_physical_page - toc_page
        4. Return most common offset (consensus)
        """
        import re
        from collections import Counter

        sample_items = structure[:min(5, len(structure))]
        sample_titles = []
        for item in sample_items:
            title = item.get('title', '').strip()
            if title:
                sample_titles.append(re.sub(r'\s+', '', title))

        if not sample_titles:
            return 0

        # Step 1: Identify TOC listing pages (pages matching 3+ sample titles)
        # These are pages that list many titles (like a table of contents)
        toc_pages = set()
        for page_idx, page in enumerate(pages):
            normalized_text = re.sub(r'\s+', '', page.text[:5000])
            match_count = sum(1 for t in sample_titles if t in normalized_text)
            if match_count >= 3:
                toc_pages.add(page_idx)
                if self.debug:
                    print(f"  [OFFSET] Skipping page {page_idx + 1} (TOC listing page, "
                          f"matches {match_count}/{len(sample_titles)} titles)")

        # Step 2: Search for each title, skipping TOC listing pages
        offsets = []
        for item in sample_items:
            title = item.get('title', '').strip()
            toc_page = item.get('page')

            if not title or not toc_page:
                continue

            normalized_title = re.sub(r'\s+', '', title)

            for page_idx, page in enumerate(pages):
                if page_idx in toc_pages:
                    continue  # Skip TOC listing pages

                physical_page = page_idx + 1
                normalized_text = re.sub(r'\s+', '', page.text[:3000])

                if normalized_title in normalized_text:
                    offset = physical_page - toc_page
                    offsets.append(offset)
                    if self.debug:
                        print(f"  [OFFSET] '{title[:30]}' found on page {physical_page} "
                              f"(TOC page {toc_page}, offset={offset:+d})")
                    break  # Found, move to next item

        if not offsets:
            return 0

        # Step 3: Return most common offset (consensus)
        counter = Counter(offsets)
        best_offset, count = counter.most_common(1)[0]

        if self.debug:
            print(f"  [OFFSET] Consensus offset: {best_offset:+d} "
                  f"({count}/{len(offsets)} matches)")

        return best_offset
    
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
