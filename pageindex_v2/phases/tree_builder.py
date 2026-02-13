"""
Tree Builder - Convert flat structure to hierarchical tree with depth limit
Enforces maximum 4 levels as per design constraint
"""
from typing import List, Dict, Tuple, Optional
from ..utils.helpers import (
    list_to_tree,
    validate_structure_depth,
    merge_deep_nodes,
    add_node_ids,
    calculate_tree_depth
)


class TreeBuilder:
    """
    Build hierarchical tree from flat TOC structure
    Features:
    - 4-level depth constraint
    - Node ID assignment
    - End index calculation
    - Chinese document support
    """
    
    def __init__(self, max_depth: int = 4, debug: bool = True, max_leaf_pages: int = 15):
        self.max_depth = max_depth
        self.debug = debug
        self.max_leaf_pages = max_leaf_pages
    
    def build_tree(
        self,
        structure: List[Dict],
        pages: List,
        total_pages: int = 0
    ) -> List[Dict]:
        """
        Build tree from verified structure

        Args:
            structure: Flat list of TOC items with physical_index
            pages: List of PDFPage objects (may be a subset of total)
            total_pages: Total pages in the document (for end_index calculation).
                        If 0, defaults to len(pages).

        Returns:
            Hierarchical tree with start/end indices
        """
        if total_pages <= 0:
            total_pages = len(pages)
        if self.debug:
            print(f"\n{'='*60}")
            print("[TREE BUILDER] Building hierarchical tree")
            print(f"{'='*60}")
            print(f"[TREE] Input items: {len(structure)}")
            print(f"[TREE] Max depth: {self.max_depth}")
        
        # Step 1: Filter items for tree building
        # Keep items that either:
        # 1. Passed verification (verification_passed is True or absent)
        # 2. Have a valid physical_index (from page mapper offset detection),
        #    even if LLM verification failed (e.g., free model returned garbage)
        # This prevents unreliable LLM verification from dropping correctly-mapped items
        verified = [
            s for s in structure
            if s.get('verification_passed', True)
            or (s.get('physical_index') is not None and isinstance(s.get('physical_index'), int))
        ]

        # Safety net: if filtering still removes ALL items, use full structure
        if not verified and structure:
            if self.debug:
                print(f"[TREE] ⚠ All {len(structure)} items failed verification AND have no physical_index!")
                print(f"[TREE] → Using unverified structure as fallback (verification may be unreliable)")
            verified = structure

        if self.debug:
            # Show how many items were kept due to physical_index fallback
            passed_verification = sum(1 for s in structure if s.get('verification_passed', True))
            kept_by_physical = len(verified) - passed_verification
            if kept_by_physical > 0:
                print(f"[TREE] ℹ {kept_by_physical} items kept via physical_index fallback "
                      f"(verification failed but page mapping exists)")

        if self.debug:
            print(f"[TREE] Verified items: {len(verified)}/{len(structure)}")
        
        # Step 2: Add list indices for reference
        for i, item in enumerate(verified):
            item['list_index'] = i
        
        # Step 3: Convert flat list to tree
        tree = list_to_tree(verified)
        
        if self.debug:
            print(f"[TREE] Initial tree nodes: {len(tree)}")
            for node in tree:
                depth = calculate_tree_depth(node)
                print(f"  - '{node.get('title', '')[:30]}...' (depth: {depth})")
        
        # Step 4: Validate and enforce depth limit
        is_valid, errors = validate_structure_depth(tree, self.max_depth)
        
        if not is_valid:
            if self.debug:
                print(f"[TREE] Depth violations found: {len(errors)}")
                for err in errors[:3]:
                    print(f"  ! {err}")
            
            # Merge deep nodes
            tree = merge_deep_nodes(tree, self.max_depth)
            
            if self.debug:
                print(f"[TREE] Merged nodes exceeding depth {self.max_depth}")
        
        # Step 5: Calculate end indices (use total_pages for proper range calculation)
        tree = self._calculate_end_indices(tree, pages, total_pages=total_pages)
        
        # Step 6: Add node IDs with multi-level numbering (1, 1.1, 1.1.1, etc.)
        add_node_ids(tree, use_hierarchical=True)
        
        # Step 7: Optional - add summaries or text
        # tree = self._add_node_texts(tree, pages)  # If needed
        
        if self.debug:
            final_depth = max(
                (calculate_tree_depth(n) for n in tree),
                default=0
            )
            print(f"[TREE] Complete: {len(tree)} root nodes, max depth: {final_depth}")
            print(f"{'='*60}\n")
        
        return tree
    
    def _calculate_end_indices(
        self,
        tree: List[Dict],
        pages: List,
        total_pages: int = 0
    ) -> List[Dict]:
        """
        Calculate end_index for each node based on next sibling or child.

        Strategy:
        - Allow adjacent sections to share pages (end = next_start)
        - For last-child leaf nodes at non-root level: cap page span to
          max_leaf_pages to prevent a single leaf from swallowing dozens
          of uncovered pages
        - Root-level leaf nodes are NOT capped: Phase 6a recursive processing
          will break them down, and gap filler handles any remaining gaps
        - Track oversized nodes and uncovered page ranges for diagnostics

        Args:
            tree: List of tree nodes
            pages: List of PDFPage objects (may be a subset)
            total_pages: Total pages in the document. If 0, defaults to len(pages).
        """
        if total_pages <= 0:
            total_pages = len(pages)
        self._oversized_warnings = []  # Collect warnings for post-processing

        def process_node(
            node: Dict,
            next_sibling_start: Optional[int] = None,
            parent_end: Optional[int] = None,
            is_root: bool = False
        ):
            """Process single node and its children"""
            title = node.get('title', '')
            start = node.get('start_index') or node.get('physical_index', 1)

            # Calculate end
            if 'nodes' in node and node['nodes']:
                # Has children - end is last child's end
                children = node['nodes']

                # Estimate this node's potential end for children to use
                if next_sibling_start:
                    node_boundary = next_sibling_start - 1
                elif parent_end:
                    node_boundary = parent_end
                else:
                    node_boundary = total_pages

                # Process children (never root)
                for i, child in enumerate(children):
                    next_start = None
                    if i + 1 < len(children):
                        next_start = children[i + 1].get('start_index') or children[i + 1].get('physical_index')

                    process_node(child, next_start, node_boundary, is_root=False)

                # This node's end is last child's end
                last_child = children[-1]
                end = last_child.get('end_index', start)
            else:
                # Leaf node
                if next_sibling_start:
                    # Has next sibling: extend to its start page (allows page sharing)
                    end = next_sibling_start
                elif parent_end:
                    # Last child without next sibling
                    if is_root:
                        # Root-level node: do NOT cap. Let Phase 6a recursive
                        # processing handle large nodes. Capping here would prevent
                        # recursive processing from seeing the full page range.
                        end = parent_end
                        page_span = parent_end - start + 1
                        if page_span > self.max_leaf_pages and self.debug:
                            print(f"  [END_IDX] ℹ Root leaf '{title[:40]}': "
                                  f"p{start}-{parent_end} ({page_span} pages, "
                                  f"will be handled by recursive processing)")
                    else:
                        # Non-root last child: cap span to prevent greedy extension
                        uncapped_end = parent_end
                        capped_end = min(parent_end, start + self.max_leaf_pages - 1)
                        end = capped_end

                        if uncapped_end > capped_end:
                            span_diff = uncapped_end - capped_end
                            self._oversized_warnings.append({
                                'title': title,
                                'start': start,
                                'uncapped_end': uncapped_end,
                                'capped_end': capped_end,
                                'uncovered_pages': span_diff
                            })
                            if self.debug:
                                print(f"  [END_IDX] ⚠ Capped last leaf '{title[:40]}': "
                                      f"p{start}-{uncapped_end} → p{start}-{capped_end} "
                                      f"({span_diff} uncovered pages)")
                else:
                    # No parent context: estimate
                    end = min(start + self.max_leaf_pages - 1, total_pages)

            node['start_index'] = start
            node['end_index'] = max(end, start)  # Ensure end >= start

            # Remove temporary fields
            node.pop('physical_index', None)
            node.pop('structure', None)
            node.pop('page', None)
            node.pop('verified_existence', None)
            node.pop('verified_start', None)
            node.pop('verification_passed', None)
            node.pop('list_index', None)

        # Process all root nodes (marked as is_root=True)
        for i, node in enumerate(tree):
            next_start = None
            if i + 1 < len(tree):
                next_start = tree[i + 1].get('start_index') or tree[i + 1].get('physical_index')

            process_node(node, next_start, total_pages, is_root=True)

        # Report page coverage analysis
        if self.debug:
            self._report_page_coverage(tree, total_pages)

        return tree

    def _report_page_coverage(self, tree: List[Dict], total_pages: int):
        """Analyze and report page coverage after end_index calculation."""
        covered = set()

        def collect_leaf_ranges(node):
            if 'nodes' in node and node['nodes']:
                for child in node['nodes']:
                    collect_leaf_ranges(child)
            else:
                start = node.get('start_index', 1)
                end = node.get('end_index', start)
                for p in range(start, end + 1):
                    covered.add(p)

        for node in tree:
            collect_leaf_ranges(node)

        all_pages = set(range(1, total_pages + 1))
        uncovered = sorted(all_pages - covered)

        coverage_pct = len(covered) / total_pages * 100 if total_pages > 0 else 100

        print(f"  [COVERAGE] {len(covered)}/{total_pages} pages covered ({coverage_pct:.1f}%)")

        if uncovered:
            # Group consecutive uncovered pages into ranges
            ranges = []
            range_start = uncovered[0]
            range_end = uncovered[0]
            for p in uncovered[1:]:
                if p == range_end + 1:
                    range_end = p
                else:
                    ranges.append((range_start, range_end))
                    range_start = p
                    range_end = p
            ranges.append((range_start, range_end))

            for rs, re_ in ranges:
                span = re_ - rs + 1
                print(f"  [COVERAGE] ⚠ Uncovered gap: pages {rs}-{re_} ({span} pages)")

        if self._oversized_warnings:
            print(f"  [COVERAGE] {len(self._oversized_warnings)} leaf node(s) were capped")
    
    def _add_node_texts(
        self,
        tree: List[Dict],
        pages: List,
        max_chars: int = 5000
    ) -> List[Dict]:
        """
        Add text content to each node (optional)
        """
        def add_text_to_node(node: Dict):
            start = node.get('start_index', 1)
            end = node.get('end_index', start)
            
            # Collect text from all pages in range
            texts = []
            for page_num in range(start, end + 1):
                if 1 <= page_num <= len(pages):
                    texts.append(pages[page_num - 1].text)
            
            full_text = "\n\n".join(texts)
            
            # Truncate if too long
            if len(full_text) > max_chars:
                full_text = full_text[:max_chars] + "..."
            
            node['text'] = full_text
            
            # Recurse to children
            if 'nodes' in node:
                for child in node['nodes']:
                    add_text_to_node(child)
        
        for node in tree:
            add_text_to_node(node)
        
        return tree
    
    def add_preface_if_needed(
        self,
        tree: List[Dict],
        pages: List
    ) -> List[Dict]:
        """
        Add preface node if first section doesn't start at page 1
        """
        if not tree:
            return tree
        
        first_node = tree[0]
        first_start = first_node.get('start_index', 1)
        
        if first_start > 1:
            # Create preface node
            preface = {
                'title': 'Preface / 前言',
                'start_index': 1,
                'end_index': first_start - 1,
                'node_id': '0000',
                'nodes': []
            }
            
            # Insert at beginning
            tree.insert(0, preface)
            
            # Re-assign IDs with multi-level numbering
            add_node_ids(tree, use_hierarchical=True)
            
            if self.debug:
                print(f"[TREE] Added preface node (pages 1-{first_start - 1})")
        
        return tree
    
    def get_tree_statistics(self, tree: List[Dict]) -> Dict:
        """
        Get statistics about the tree
        """
        def count_nodes(node, depth=1):
            count = 1
            max_d = depth
            
            if 'nodes' in node:
                for child in node['nodes']:
                    c, d = count_nodes(child, depth + 1)
                    count += c
                    max_d = max(max_d, d)
            
            return count, max_d
        
        total_nodes = 0
        max_depth = 0
        
        for node in tree:
            c, d = count_nodes(node)
            total_nodes += c
            max_depth = max(max_depth, d)
        
        return {
            'root_nodes': len(tree),
            'total_nodes': total_nodes,
            'max_depth': max_depth,
            'avg_nodes_per_root': total_nodes / len(tree) if tree else 0
        }
