"""
优化的LLM页码验证方法（可选）

用于需要高精度验证的场景
"""

async def _map_with_llm_verification(
    self,
    structure: List[Dict],
    pages: List
) -> List[Dict]:
    """
    使用改进的LLM验证来映射页码
    
    关键改进：
    1. 使用TOC页码作为搜索范围提示（±5页）
    2. 明确告诉LLM忽略TOC页面本身
    3. 提取实际章节开头的<physical_index_X>标签
    """
    if self.debug:
        print(f"[MAP] Using LLM-assisted verification with page hints")
    
    system_prompt = """
    You are mapping Table of Contents entries to their actual physical page numbers.

    CRITICAL INSTRUCTIONS:
    1. Each TOC entry has a 'page' number - this is where the TOC CLAIMS the section is
    2. Your job: Find where that section ACTUALLY starts in the document
    3. Look for the section title appearing as a CHAPTER/SECTION HEADING (not in TOC lists)
    4. The document uses <physical_index_X> tags to mark actual page numbers
    5. Extract the <physical_index_X> tag where you find the real chapter heading

    AVOIDING FALSE MATCHES:
    - IGNORE any matches in Table of Contents pages (usually pages 1-10)
    - IGNORE compact lists with many section titles together
    - LOOK FOR the title as a heading followed by actual content/paragraphs
    - Use the TOC page number as a hint: search around that page (±5 pages)

    Example:
    TOC says: "3. Introduction" → page 15
    You should: Look around pages 10-20 for where "Introduction" appears as a heading
    Return: <physical_index_15> (or nearby if there's an offset)

    Reply format (JSON):
    {
        "mappings": [
            {
                "structure": "1.1",
                "title": "Section Title",
                "toc_page": 15,
                "physical_index": "<physical_index_15>" or null,
                "confidence": "high" or "medium" or "low",
                "note": "Found as heading on page 15" or "Not found in search range"
            }
        ]
    }
    """
    
    # Prepare document segments based on TOC page ranges
    # Group items that are close together to reduce LLM calls
    segments = self._prepare_smart_segments(structure, pages)
    
    if self.debug:
        print(f"[MAP] Document divided into {len(segments)} smart segments")
    
    current_mappings = []
    
    for seg_idx, segment in enumerate(segments):
        items = segment['items']
        content = segment['content']
        
        # Prepare items for prompt
        items_for_prompt = [
            {
                'structure': item['structure'],
                'title': item['title'],
                'toc_page': item.get('page')
            }
            for item in items
        ]
        
        prompt = f"""
        Map these TOC entries to their actual physical pages:

        TOC Entries:
        {json.dumps(items_for_prompt, ensure_ascii=False, indent=2)}

        Document segment (with <physical_index_X> tags):
        ---
        {content[:50000]}
        ---

        For each entry:
        1. Use toc_page as a hint (search around that page)
        2. Find where the title appears as a real heading (not in TOC)
        3. Extract the <physical_index_X> tag at that location
        4. If not found in this segment, return null

        Return mappings in JSON format.
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt)
            mappings = result.get("mappings", [])
            
            # Merge with current mappings
            for mapping in mappings:
                current_mappings.append({
                    'structure': mapping.get('structure'),
                    'title': mapping.get('title'),
                    'page': mapping.get('toc_page'),
                    'physical_index': mapping.get('physical_index'),
                    'confidence': mapping.get('confidence', 'unknown')
                })
            
            if self.debug:
                high_conf = sum(1 for m in mappings if m.get('confidence') == 'high')
                print(f"  Segment {seg_idx+1}: Mapped {len(mappings)} items ({high_conf} high confidence)")
                
        except Exception as e:
            if self.debug:
                print(f"  [ERROR] Segment {seg_idx+1} failed: {e}")
            # Fallback: use TOC pages directly for this segment
            for item in items:
                current_mappings.append({
                    'structure': item.get('structure'),
                    'title': item.get('title'),
                    'page': item.get('page'),
                    'physical_index': f"<physical_index_{item.get('page')}>" if item.get('page') else None,
                    'confidence': 'fallback'
                })
    
    return current_mappings


def _prepare_smart_segments(
    self,
    structure: List[Dict],
    pages: List,
    items_per_segment: int = 10,
    pages_per_segment: int = 50
) -> List[Dict]:
    """
    将structure分组为智能段落，每段包含相近页码的items
    
    策略：
    - 每段最多10个items
    - 每段覆盖的页面范围：最小TOC页 - 5 到 最大TOC页 + 5
    - 提取该范围内的labeled_content
    """
    segments = []
    current_batch = []
    
    for item in structure:
        current_batch.append(item)
        
        if len(current_batch) >= items_per_segment:
            segment = self._create_segment(current_batch, pages)
            if segment:
                segments.append(segment)
            current_batch = []
    
    # Last batch
    if current_batch:
        segment = self._create_segment(current_batch, pages)
        if segment:
            segments.append(segment)
    
    return segments


def _create_segment(self, items: List[Dict], pages: List) -> Dict:
    """
    为一组items创建segment，包含相关的页面内容
    """
    # Find page range
    toc_pages = [item.get('page') for item in items if item.get('page')]
    if not toc_pages:
        return None
    
    min_page = max(1, min(toc_pages) - 5)  # Search 5 pages before
    max_page = min(len(pages), max(toc_pages) + 5)  # Search 5 pages after
    
    # Extract content from that range
    content_parts = []
    for i in range(min_page - 1, max_page):  # Convert to 0-indexed
        if 0 <= i < len(pages):
            content_parts.append(pages[i].labeled_content)
    
    content = "\n".join(content_parts)
    
    return {
        'items': items,
        'page_range': (min_page, max_page),
        'content': content
    }
