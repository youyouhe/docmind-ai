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
    
    def __init__(self, max_depth: int = 4, debug: bool = True):
        self.max_depth = max_depth
        self.debug = debug
    
    def build_tree(
        self,
        structure: List[Dict],
        pages: List
    ) -> List[Dict]:
        """
        Build tree from verified structure
        
        Args:
            structure: Flat list of TOC items with physical_index
            pages: List of PDFPage objects
        
        Returns:
            Hierarchical tree with start/end indices
        """
        if self.debug:
            print(f"\n{'='*60}")
            print("[TREE BUILDER] Building hierarchical tree")
            print(f"{'='*60}")
            print(f"[TREE] Input items: {len(structure)}")
            print(f"[TREE] Max depth: {self.max_depth}")
        
        # Step 1: Filter to verified items only
        verified = [s for s in structure if s.get('verification_passed', True)]
        
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
        
        # Step 5: Calculate end indices
        tree = self._calculate_end_indices(tree, len(pages))
        
        # Step 6: Add node IDs
        add_node_ids(tree)
        
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
        total_pages: int
    ) -> List[Dict]:
        """
        Calculate end_index for each node based on next sibling or child
        
        Improved strategy:
        - Use next sibling's start - 1 if available
        - Otherwise, use parent's boundary or reasonable estimate
        - Avoid defaulting all leaf nodes to total_pages
        """
        def process_node(node: Dict, next_sibling_start: Optional[int] = None, parent_end: Optional[int] = None):
            """Process single node and its children"""
            start = node.get('start_index') or node.get('physical_index', 1)
            
            # Calculate end
            if 'nodes' in node and node['nodes']:
                # Has children - end is last child's end
                children = node['nodes']
                
                # First, estimate this node's potential end for children to use
                if next_sibling_start:
                    node_boundary = next_sibling_start - 1
                elif parent_end:
                    node_boundary = parent_end
                else:
                    node_boundary = total_pages
                
                # Process children and find their ends
                for i, child in enumerate(children):
                    # Next sibling's start (or None if last)
                    next_start = None
                    if i + 1 < len(children):
                        next_start = children[i + 1].get('physical_index')
                    
                    process_node(child, next_start, node_boundary)
                
                # This node's end is last child's end
                last_child = children[-1]
                end = last_child.get('end_index', start)
            else:
                # Leaf node - use smarter heuristics
                if next_sibling_start:
                    # Next sibling available - use it
                    end = next_sibling_start - 1
                elif parent_end:
                    # Use parent's boundary
                    end = parent_end
                else:
                    # Last resort - estimate based on document structure
                    # Assume reasonable section length: ~10 pages max for leaf nodes
                    estimated_end = min(start + 10, total_pages)
                    end = estimated_end
            
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
        
        # Process all root nodes
        for i, node in enumerate(tree):
            next_start = None
            if i + 1 < len(tree):
                next_start = tree[i + 1].get('physical_index') or tree[i + 1].get('start_index')
            
            process_node(node, next_start, total_pages)
        
        return tree
    
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
            
            # Re-assign IDs
            add_node_ids(tree)
            
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
