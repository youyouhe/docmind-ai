"""
Gap Filler - Post-processing utility to fill missing pages in tree structure

This module analyzes the generated tree structure and identifies page gaps.
For any missing pages, it generates a supplementary TOC using LLM and appends
it to the tree structure as a "patch".
"""

import asyncio
from typing import List, Dict, Any, Set, Tuple
from ..core.llm_client import LLMClient
from ..core.pdf_parser import PDFParser


class GapFiller:
    """Post-processor to fill missing pages in tree structure"""
    
    def __init__(self, llm: LLMClient, debug: bool = False):
        self.llm = llm
        self.debug = debug
    
    def analyze_coverage(self, tree_structure: List[Dict], total_pages: int) -> Dict[str, Any]:
        """
        Analyze page coverage in tree structure and identify gaps.
        
        Args:
            tree_structure: The generated tree structure
            total_pages: Total number of pages in PDF
            
        Returns:
            Dict with coverage analysis:
            - covered_pages: Set of pages covered in tree
            - missing_pages: Set of pages not covered
            - gaps: List of continuous page ranges that are missing
        """
        covered_pages = set()
        
        def collect_pages(nodes):
            """Recursively collect all page references"""
            for node in nodes:
                # Collect start_index and end_index
                if 'start_index' in node:
                    covered_pages.add(node['start_index'])
                if 'end_index' in node:
                    covered_pages.add(node['end_index'])
                
                # Also check for 'page' field (used in some structures)
                if 'page' in node:
                    covered_pages.add(node['page'])
                
                # Collect pages from all indices in range
                if 'start_index' in node and 'end_index' in node:
                    start = node['start_index']
                    end = node['end_index']
                    for p in range(start, end + 1):
                        covered_pages.add(p)
                
                # Recurse into children
                if 'nodes' in node and node['nodes']:
                    collect_pages(node['nodes'])
                if 'children' in node and node['children']:
                    collect_pages(node['children'])
        
        # Collect all covered pages
        collect_pages(tree_structure)
        
        # Find missing pages
        all_pages = set(range(1, total_pages + 1))
        missing_pages = all_pages - covered_pages
        
        # Group missing pages into continuous ranges (gaps)
        gaps = []
        if missing_pages:
            sorted_missing = sorted(missing_pages)
            gap_start = sorted_missing[0]
            gap_end = sorted_missing[0]
            
            for page in sorted_missing[1:]:
                if page == gap_end + 1:
                    # Continue current gap
                    gap_end = page
                else:
                    # Save current gap and start new one
                    gaps.append((gap_start, gap_end))
                    gap_start = page
                    gap_end = page
            
            # Don't forget the last gap
            gaps.append((gap_start, gap_end))
        
        return {
            'covered_pages': covered_pages,
            'missing_pages': missing_pages,
            'gaps': gaps,
            'coverage_percentage': len(covered_pages) / total_pages * 100 if total_pages > 0 else 0
        }
    
    async def generate_gap_toc(
        self, 
        pdf_path: str, 
        gap_start: int, 
        gap_end: int,
        parser: PDFParser
    ) -> List[Dict[str, Any]]:
        """
        Generate TOC for a gap in page coverage using LLM.
        
        Args:
            pdf_path: Path to PDF file
            gap_start: First page of gap (1-indexed)
            gap_end: Last page of gap (1-indexed)
            parser: PDF parser instance
            
        Returns:
            List of TOC items for this gap
        """
        if self.debug:
            print(f"\n[GAP FILLER] Generating TOC for pages {gap_start}-{gap_end}")
        
        # Parse the gap pages
        pages = await parser.parse(pdf_path, max_pages=gap_end)
        gap_pages = pages[gap_start - 1:gap_end]  # Convert to 0-indexed
        
        if not gap_pages:
            if self.debug:
                print(f"[GAP FILLER] ⚠ No content found in gap pages {gap_start}-{gap_end}")
            return []
        
        # Combine page content
        gap_content = "\n\n".join([
            f"=== Page {gap_start + i} ===\n{page.text}"
            for i, page in enumerate(gap_pages)
        ])
        
        # Limit content size (to avoid token limits)
        max_chars = 50000
        if len(gap_content) > max_chars:
            gap_content = gap_content[:max_chars] + "\n\n[Content truncated...]"
        
        # Generate TOC using LLM
        prompt = f"""Analyze the following content from pages {gap_start} to {gap_end} of a PDF document.

Generate a table of contents (TOC) for this section. For each entry:
1. Identify main topics, sections, or headings
2. Assign a page number where the topic appears
3. Create a hierarchical structure if subsections exist

Content:
{gap_content}

Respond with a JSON array of TOC items. Each item should have:
- "title": The section/topic title
- "page": The page number where it appears ({gap_start} to {gap_end})
- "level": Hierarchy level (1 for main topics, 2 for subtopics, etc.)

Example format:
[
  {{"title": "Main Topic", "page": {gap_start}, "level": 1}},
  {{"title": "Subtopic", "page": {gap_start + 1}, "level": 2}}
]

If no clear structure is found, create at least one entry representing the page range.
Please respond in JSON format."""
        
        try:
            response = await self.llm.chat_json(
                prompt=prompt,
                temperature=0.3
            )
            
            if isinstance(response, list):
                toc_items = response
            elif isinstance(response, dict) and 'items' in response:
                toc_items = response['items']
            elif isinstance(response, dict) and 'toc' in response:
                toc_items = response['toc']
            else:
                toc_items = []
            
            if self.debug:
                print(f"[GAP FILLER] ✓ Generated {len(toc_items)} TOC items for gap")
            
            return toc_items
        
        except Exception as e:
            if self.debug:
                print(f"[GAP FILLER] ✗ Error generating TOC for gap: {e}")
            
            # Fallback: Create a simple entry for the gap
            return [{
                "title": f"Pages {gap_start}-{gap_end} (Uncategorized)",
                "page": gap_start,
                "level": 1
            }]
    
    def convert_gap_toc_to_structure(
        self, 
        gap_toc: List[Dict[str, Any]], 
        gap_start: int,
        gap_end: int
    ) -> List[Dict[str, Any]]:
        """
        Convert gap TOC items to tree structure format.
        
        Args:
            gap_toc: TOC items from LLM
            gap_start: First page of gap
            gap_end: Last page of gap
            
        Returns:
            List of tree nodes in standard format
        """
        nodes = []
        
        # Build hierarchy
        for i, item in enumerate(gap_toc):
            title = item.get('title', f'Section (Page {item.get("page", gap_start)})')
            page = item.get('page', gap_start)
            level = item.get('level', 1)
            
            # Determine end page (next item's page - 1, or gap_end)
            if i + 1 < len(gap_toc):
                end_page = gap_toc[i + 1].get('page', gap_end) - 1
            else:
                end_page = gap_end
            
            # Ensure valid range
            if end_page < page:
                end_page = page
            
            node = {
                "title": title,
                "start_index": page,
                "end_index": end_page,
                "nodes": [],
                "node_id": f"gap_{gap_start}_{i:04d}",
                "is_gap_fill": True  # Mark as gap-filled content
            }
            
            # Handle hierarchy (simple approach: nest level 2+ under level 1)
            if level == 1:
                nodes.append(node)
            elif nodes and level > 1:
                # Add as child of last level-1 node
                nodes[-1]['nodes'].append(node)
            else:
                # Fallback: add as root
                nodes.append(node)
        
        # If no items were generated, create a default entry
        if not nodes:
            nodes.append({
                "title": f"Pages {gap_start}-{gap_end} (Supplementary Content)",
                "start_index": gap_start,
                "end_index": gap_end,
                "nodes": [],
                "node_id": f"gap_{gap_start}_0000",
                "is_gap_fill": True
            })
        
        return nodes
    
    async def fill_gaps(
        self, 
        tree_structure: List[Dict], 
        pdf_path: str,
        total_pages: int,
        parser: PDFParser
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Main function to analyze and fill gaps in tree structure.
        
        Args:
            tree_structure: Original tree structure
            pdf_path: Path to PDF file
            total_pages: Total pages in PDF
            parser: PDF parser instance
            
        Returns:
            Tuple of (updated_structure, gap_info)
        """
        # Analyze coverage
        analysis = self.analyze_coverage(tree_structure, total_pages)
        
        if self.debug:
            print(f"\n[GAP FILLER] Coverage Analysis:")
            print(f"  Total pages: {total_pages}")
            print(f"  Covered pages: {len(analysis['covered_pages'])}")
            print(f"  Missing pages: {len(analysis['missing_pages'])}")
            print(f"  Coverage: {analysis['coverage_percentage']:.1f}%")
            print(f"  Gaps found: {len(analysis['gaps'])}")
            if analysis['gaps']:
                for gap_start, gap_end in analysis['gaps']:
                    gap_size = gap_end - gap_start + 1
                    print(f"    - Pages {gap_start}-{gap_end} ({gap_size} pages)")
        
        # If no gaps, return original structure
        if not analysis['gaps']:
            if self.debug:
                print(f"[GAP FILLER] ✓ No gaps found, structure is complete")
            return tree_structure, analysis
        
        # Generate TOC for each gap
        gap_patches = []
        for gap_start, gap_end in analysis['gaps']:
            gap_toc = await self.generate_gap_toc(pdf_path, gap_start, gap_end, parser)
            gap_nodes = self.convert_gap_toc_to_structure(gap_toc, gap_start, gap_end)
            gap_patches.extend(gap_nodes)
        
        # Append gap patches to original structure
        updated_structure = tree_structure + gap_patches
        
        if self.debug:
            print(f"[GAP FILLER] ✓ Added {len(gap_patches)} patch nodes to structure")
            print(f"[GAP FILLER] Original nodes: {len(tree_structure)}")
            print(f"[GAP FILLER] Updated nodes: {len(updated_structure)}")
        
        return updated_structure, analysis


async def fill_structure_gaps(
    structure_data: Dict[str, Any],
    pdf_path: str,
    llm: LLMClient,
    parser: PDFParser,
    debug: bool = False
) -> Dict[str, Any]:
    """
    Convenience function to fill gaps in a complete structure data dict.
    
    Args:
        structure_data: Complete structure dict with 'structure' key
        pdf_path: Path to PDF file
        llm: LLM client instance
        parser: PDF parser instance
        debug: Enable debug logging
        
    Returns:
        Updated structure_data with gaps filled
    """
    filler = GapFiller(llm, debug=debug)
    
    tree_structure = structure_data.get('structure', [])
    total_pages = structure_data.get('total_pages', 0)
    
    # Fill gaps
    updated_structure, gap_info = await filler.fill_gaps(
        tree_structure, pdf_path, total_pages, parser
    )
    
    # Update structure data
    structure_data['structure'] = updated_structure
    structure_data['gap_fill_info'] = {
        'gaps_found': len(gap_info['gaps']),
        'gaps_filled': gap_info['gaps'],
        'original_coverage': f"{len(gap_info['covered_pages'])}/{total_pages}",
        'coverage_percentage': gap_info['coverage_percentage']
    }
    
    return structure_data
