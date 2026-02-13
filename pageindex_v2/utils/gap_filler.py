"""
Gap Filler - Post-processing utility to fill missing pages in tree structure

This module analyzes the generated tree structure and identifies page gaps.
For any missing pages, it generates a supplementary TOC using LLM and appends
it to the tree structure as a "patch".

V2 improvements:
- Accepts pre-parsed pages to avoid re-parsing PDF
- Segments large gaps to prevent LLM timeouts
- Adds timeout protection on LLM calls
- Inserts gap patches at correct position (not append+sort)
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from ..core.llm_client import LLMClient
from ..core.pdf_parser import PDFParser, PDFPage


class GapFiller:
    """Post-processor to fill missing pages in tree structure"""

    # Gaps smaller than this are ignored (likely cover pages, blank pages etc.)
    MIN_GAP_PAGES = 3
    # Maximum pages to send to LLM in a single call
    MAX_PAGES_PER_LLM_CALL = 20
    # Maximum content chars per LLM call
    MAX_CHARS_PER_CALL = 30000
    # Timeout per LLM call (seconds)
    LLM_TIMEOUT = 60

    def __init__(self, llm: LLMClient, debug: bool = False):
        self.llm = llm
        self.debug = debug

    def analyze_coverage(self, tree_structure: List[Dict], total_pages: int) -> Dict[str, Any]:
        """
        Analyze page coverage in tree structure and identify gaps.

        Returns:
            Dict with covered_pages, missing_pages, gaps, coverage_percentage
        """
        covered_pages = set()

        def collect_leaf_ranges(nodes):
            for node in nodes:
                if 'nodes' in node and node['nodes']:
                    collect_leaf_ranges(node['nodes'])
                else:
                    start = node.get('start_index', 0)
                    end = node.get('end_index', start)
                    for p in range(start, end + 1):
                        covered_pages.add(p)

        collect_leaf_ranges(tree_structure)

        all_pages = set(range(1, total_pages + 1))
        missing_pages = all_pages - covered_pages

        # Group missing pages into continuous ranges
        gaps = []
        if missing_pages:
            sorted_missing = sorted(missing_pages)
            gap_start = sorted_missing[0]
            gap_end = sorted_missing[0]

            for page in sorted_missing[1:]:
                if page == gap_end + 1:
                    gap_end = page
                else:
                    gaps.append((gap_start, gap_end))
                    gap_start = page
                    gap_end = page
            gaps.append((gap_start, gap_end))

        return {
            'covered_pages': covered_pages,
            'missing_pages': missing_pages,
            'gaps': gaps,
            'coverage_percentage': len(covered_pages) / total_pages * 100 if total_pages > 0 else 0
        }

    async def _ensure_pages_parsed(
        self,
        gap_start: int,
        gap_end: int,
        existing_pages: List[PDFPage],
        pdf_path: str,
        parser: PDFParser
    ) -> List[PDFPage]:
        """
        Ensure pages for a gap range are parsed. Reuse existing pages where possible,
        only parse additional pages if needed.

        Returns:
            List of PDFPage objects for the gap range
        """
        # Check which gap pages we already have
        existing_page_nums = {p.page_number for p in existing_pages}
        needed_max = gap_end

        if needed_max <= len(existing_pages):
            # All gap pages already parsed
            return [existing_pages[i - 1] for i in range(gap_start, gap_end + 1)
                    if i <= len(existing_pages)]

        # Need to parse more pages
        if self.debug:
            print(f"  [GAP FILLER] Parsing pages up to {needed_max} for gap coverage")

        all_pages = await parser.parse(pdf_path, max_pages=needed_max)

        # Return only the gap range
        return [all_pages[i - 1] for i in range(gap_start, gap_end + 1)
                if i <= len(all_pages)]

    async def generate_gap_toc(
        self,
        gap_pages: List[PDFPage],
        gap_start: int,
        gap_end: int
    ) -> List[Dict[str, Any]]:
        """
        Generate TOC for a gap using LLM. Segments large gaps into chunks.

        Args:
            gap_pages: Pre-parsed PDFPage objects for the gap
            gap_start: First page of gap (1-indexed)
            gap_end: Last page of gap (1-indexed)

        Returns:
            List of TOC items for this gap
        """
        if self.debug:
            print(f"\n[GAP FILLER] Generating TOC for pages {gap_start}-{gap_end} "
                  f"({gap_end - gap_start + 1} pages)")

        if not gap_pages:
            if self.debug:
                print(f"  [GAP FILLER] ⚠ No content for gap pages {gap_start}-{gap_end}")
            return []

        # Segment large gaps into chunks
        all_toc_items = []
        chunk_size = self.MAX_PAGES_PER_LLM_CALL

        for chunk_start_idx in range(0, len(gap_pages), chunk_size):
            chunk_pages = gap_pages[chunk_start_idx:chunk_start_idx + chunk_size]
            if not chunk_pages:
                break

            chunk_page_start = chunk_pages[0].page_number
            chunk_page_end = chunk_pages[-1].page_number

            # Build labeled content
            gap_content = "\n\n".join([
                f"<physical_index_{page.page_number}>\n{page.text}"
                for page in chunk_pages
            ])

            # Truncate if needed
            if len(gap_content) > self.MAX_CHARS_PER_CALL:
                gap_content = gap_content[:self.MAX_CHARS_PER_CALL] + "\n\n[Content truncated...]"

            prompt = f"""从以下文档内容中提取章节标题。每页内容以 <physical_index_N> 标记开头，N 是该页的物理页码。

任务：找出这些页面中的章节/小节标题，构建层级目录。

页码规则：使用 <physical_index_N> 中的 N 作为页码，不要使用文档正文中印刷的页码（如"第X页共Y页"）。

内容：
{gap_content}

提取规则：
- 只提取真正的章节标题，如："第三章 评标办法"、"（一）甲方的权利和义务"、"附件1：投标函"
- 不要提取以下内容：
  * 目录条目（带省略号连接页码的行，如"第一章 招标公告......1"）
  * 页眉页脚（如"第31页共78页"）
  * 表单字段（如"项目编号：""电话：""日期："）
  * 占位符或空白模板项（如"2．......"、"3．......"、"______"）
  * 普通段落文本或表格内容
- 标题原文照抄，不要翻译或修改
- 页码必须在 {chunk_page_start} 到 {chunk_page_end} 之间
- level: 1=章, 2=节, 3=小节

示例 - 正确提取:
✓ {{"title": "第三章 评标办法及评分标准", "page": 23, "level": 1}}
✓ {{"title": "（一）甲方的权利和义务", "page": 32, "level": 2}}
✓ {{"title": "附件1：投标函", "page": 58, "level": 1}}

示例 - 不应提取:
✗ "2．......"（占位符）
✗ "第31页共78页"（页脚）
✗ "项目编号：0724-2410SZ968133"（表单字段）
✗ "第一章 招标公告......1"（目录条目，不是正文标题）

输出 JSON 格式：
{{
  "table_of_contents": [
    {{"title": "章节标题", "page": {chunk_page_start}, "level": 1}},
    {{"title": "小节标题", "page": {chunk_page_start + 1}, "level": 2}}
  ]
}}

如果没有找到章节标题，返回空数组。"""

            try:
                response = await asyncio.wait_for(
                    self.llm.chat_json(prompt, max_tokens=2000),
                    timeout=self.LLM_TIMEOUT
                )

                if isinstance(response, dict):
                    toc_items = response.get('table_of_contents',
                                  response.get('toc',
                                  response.get('items', [])))
                elif isinstance(response, list):
                    toc_items = response
                else:
                    toc_items = []

                # Filter items: page must be within the gap range
                valid_items = []
                filtered_out = 0
                for item in toc_items:
                    page = item.get('page', 0)
                    if isinstance(page, int) and gap_start <= page <= gap_end:
                        valid_items.append(item)
                    else:
                        filtered_out += 1

                if self.debug:
                    print(f"  [GAP FILLER] Chunk p{chunk_page_start}-{chunk_page_end}: "
                          f"{len(valid_items)} items extracted"
                          f"{f' ({filtered_out} filtered: outside gap range)' if filtered_out else ''}")

                all_toc_items.extend(valid_items)

            except asyncio.TimeoutError:
                if self.debug:
                    print(f"  [GAP FILLER] ⚠ LLM timeout for chunk "
                          f"p{chunk_page_start}-{chunk_page_end}, using fallback")
                all_toc_items.append({
                    "title": f"Pages {chunk_page_start}-{chunk_page_end}",
                    "page": chunk_page_start,
                    "level": 1
                })
            except Exception as e:
                if self.debug:
                    print(f"  [GAP FILLER] ⚠ Error for chunk "
                          f"p{chunk_page_start}-{chunk_page_end}: {e}")
                all_toc_items.append({
                    "title": f"Pages {chunk_page_start}-{chunk_page_end}",
                    "page": chunk_page_start,
                    "level": 1
                })

        if self.debug:
            print(f"  [GAP FILLER] Total: {len(all_toc_items)} items for gap")

        return all_toc_items

    def convert_gap_toc_to_tree(
        self,
        gap_toc: List[Dict[str, Any]],
        gap_start: int,
        gap_end: int
    ) -> List[Dict[str, Any]]:
        """
        Convert gap TOC items to tree nodes.
        """
        if not gap_toc:
            # No items: create a placeholder node
            return [{
                "title": f"Pages {gap_start}-{gap_end}",
                "start_index": gap_start,
                "end_index": gap_end,
                "nodes": [],
                "node_id": f"gap_{gap_start}_0000",
                "is_gap_fill": True
            }]

        # Sort by page number
        sorted_items = sorted(gap_toc, key=lambda x: x.get('page', gap_start))

        # Build hierarchy: level 1 nodes are roots, level 2+ are children
        roots = []
        for i, item in enumerate(sorted_items):
            title = item.get('title', f'Page {item.get("page", gap_start)}')
            page = item.get('page', gap_start)
            level = item.get('level', 1)

            # Determine end page
            if i + 1 < len(sorted_items):
                next_page = sorted_items[i + 1].get('page', gap_end)
                next_level = sorted_items[i + 1].get('level', 1)
                # If next item is at same or higher level, end before it
                if next_level <= level:
                    end_page = next_page - 1
                else:
                    # Next item is a child, find the next same-level-or-above item
                    end_page = gap_end
                    for j in range(i + 1, len(sorted_items)):
                        if sorted_items[j].get('level', 1) <= level:
                            end_page = sorted_items[j].get('page', gap_end) - 1
                            break
            else:
                end_page = gap_end

            # Clamp end_page to gap boundaries
            end_page = min(end_page, gap_end)
            end_page = max(end_page, page)

            node = {
                "title": title,
                "start_index": max(page, gap_start),
                "end_index": end_page,
                "nodes": [],
                "node_id": f"gap_{gap_start}_{i:04d}",
                "is_gap_fill": True
            }

            if level == 1:
                roots.append(node)
            elif roots and level > 1:
                roots[-1]['nodes'].append(node)
            else:
                roots.append(node)

        return roots

    def _insert_gap_nodes(
        self,
        tree_structure: List[Dict],
        gap_nodes: List[Dict]
    ) -> List[Dict]:
        """
        Insert gap nodes at the correct position in the root-level tree
        by start_index order, instead of append+sort which breaks hierarchy.
        """
        if not gap_nodes:
            return tree_structure

        result = list(tree_structure)

        for gap_node in gap_nodes:
            gap_start = gap_node.get('start_index', 0)
            # Find insertion point: after the last node whose start_index < gap_start
            insert_idx = len(result)
            for i, existing in enumerate(result):
                if existing.get('start_index', 0) > gap_start:
                    insert_idx = i
                    break
            result.insert(insert_idx, gap_node)

        return result

    async def fill_gaps(
        self,
        tree_structure: List[Dict],
        pdf_path: str,
        total_pages: int,
        parser: PDFParser,
        existing_pages: Optional[List[PDFPage]] = None
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Main function to analyze and fill gaps in tree structure.

        Args:
            tree_structure: Original tree structure
            pdf_path: Path to PDF file
            total_pages: Total pages in PDF
            parser: PDF parser instance
            existing_pages: Pre-parsed pages to reuse (avoids re-parsing)

        Returns:
            Tuple of (updated_structure, gap_info)
        """
        if existing_pages is None:
            existing_pages = []

        # Analyze coverage
        analysis = self.analyze_coverage(tree_structure, total_pages)

        # Filter out small gaps (likely cover pages, blanks, etc.)
        significant_gaps = [
            (gs, ge) for gs, ge in analysis['gaps']
            if ge - gs + 1 >= self.MIN_GAP_PAGES
        ]

        if self.debug:
            print(f"\n[GAP FILLER] Coverage Analysis:")
            print(f"  Total pages: {total_pages}")
            print(f"  Covered: {len(analysis['covered_pages'])} pages "
                  f"({analysis['coverage_percentage']:.1f}%)")
            print(f"  Total gaps: {len(analysis['gaps'])}")
            print(f"  Significant gaps (≥{self.MIN_GAP_PAGES} pages): {len(significant_gaps)}")
            for gs, ge in significant_gaps:
                print(f"    - Pages {gs}-{ge} ({ge - gs + 1} pages)")

        if not significant_gaps:
            if self.debug:
                print(f"[GAP FILLER] ✓ No significant gaps to fill")
            return tree_structure, analysis

        # Fill each significant gap
        all_gap_nodes = []
        for gap_start, gap_end in significant_gaps:
            # Ensure pages are parsed
            gap_pages = await self._ensure_pages_parsed(
                gap_start, gap_end, existing_pages, pdf_path, parser
            )

            # Generate TOC for this gap
            gap_toc = await self.generate_gap_toc(gap_pages, gap_start, gap_end)

            # Convert to tree nodes
            gap_nodes = self.convert_gap_toc_to_tree(gap_toc, gap_start, gap_end)
            all_gap_nodes.extend(gap_nodes)

        # Filter out gap nodes that overlap with already-covered pages
        covered = analysis['covered_pages']
        filtered_gap_nodes = []
        removed_overlap = 0

        for node in all_gap_nodes:
            node_start = node.get('start_index', 0)
            node_end = node.get('end_index', node_start)
            node_pages = set(range(node_start, node_end + 1))
            overlap = node_pages & covered
            overlap_ratio = len(overlap) / len(node_pages) if node_pages else 0

            if overlap_ratio < 0.5:
                # Less than 50% overlap — keep this gap node
                # Also filter children that overlap
                if 'nodes' in node and node['nodes']:
                    filtered_children = []
                    for child in node['nodes']:
                        child_start = child.get('start_index', 0)
                        child_end = child.get('end_index', child_start)
                        child_pages = set(range(child_start, child_end + 1))
                        child_overlap = child_pages & covered
                        child_overlap_ratio = len(child_overlap) / len(child_pages) if child_pages else 0
                        if child_overlap_ratio < 0.5:
                            filtered_children.append(child)
                    node['nodes'] = filtered_children
                filtered_gap_nodes.append(node)
            else:
                removed_overlap += 1
                if self.debug:
                    print(f"  [GAP FILLER] Removed overlapping node: "
                          f"'{node.get('title', '')[:40]}' "
                          f"(p{node_start}-{node_end}, {overlap_ratio:.0%} overlap)")

        if self.debug and removed_overlap:
            print(f"  [GAP FILLER] Removed {removed_overlap} nodes due to overlap with existing coverage")

        # Insert gap nodes at correct positions
        updated_structure = self._insert_gap_nodes(tree_structure, filtered_gap_nodes)

        if self.debug:
            print(f"\n[GAP FILLER] ✓ Added {len(filtered_gap_nodes)} gap-fill nodes"
                  f"{f' (filtered {removed_overlap} overlapping)' if removed_overlap else ''}")
            print(f"  Original root nodes: {len(tree_structure)}")
            print(f"  Updated root nodes: {len(updated_structure)}")

        # Update analysis with gap fill info
        analysis['gaps_filled'] = significant_gaps

        return updated_structure, analysis


async def fill_structure_gaps(
    structure_data: Dict[str, Any],
    pdf_path: str,
    llm: LLMClient,
    parser: PDFParser,
    debug: bool = False,
    existing_pages: Optional[List[PDFPage]] = None
) -> Dict[str, Any]:
    """
    Convenience function to fill gaps in a complete structure data dict.

    Args:
        structure_data: Complete structure dict with 'structure' key
        pdf_path: Path to PDF file
        llm: LLM client instance
        parser: PDF parser instance
        debug: Enable debug logging
        existing_pages: Pre-parsed pages to reuse

    Returns:
        Updated structure_data with gaps filled
    """
    filler = GapFiller(llm, debug=debug)

    tree_structure = structure_data.get('structure', [])
    total_pages = structure_data.get('total_pages', 0)

    updated_structure, gap_info = await filler.fill_gaps(
        tree_structure, pdf_path, total_pages, parser,
        existing_pages=existing_pages
    )

    structure_data['structure'] = updated_structure
    structure_data['gap_fill_info'] = {
        'gaps_found': len(gap_info.get('gaps_filled', [])),
        'gaps_filled': gap_info.get('gaps_filled', []),
        'original_coverage': f"{len(gap_info['covered_pages'])}/{total_pages}",
        'coverage_percentage': gap_info['coverage_percentage']
    }

    return structure_data
