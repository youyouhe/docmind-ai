"""
Title Normalizer - Standardize tree node titles with hierarchical numbering

Numbering scheme:
- Level 1: 1, 2, 3, 4
- Level 2: 1.1, 1.2, 2.1, 2.2
- Level 3: 1.1.1, 1.1.2, 2.1.1, 2.1.2
- Level 4: 1.1.1.1, 1.1.1.2, 1.1.2.1

Features:
- display_title: Cleaned title for UI display (removes noise, numbering prefixes)
- is_noise: Boolean flag to identify invalid entries (headers, footers, metadata)
- Original title is preserved for search/indexing
"""

import re
import sys
import io
from typing import Dict, Any, List, Optional

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# Noise detection patterns
NOISE_PATTERNS = [
    # Page headers/footers
    r'^(温馨提示|页码|第\s*\d+\s*页|-\s*\d+\s*-$)',
    # Metadata
    r'^.*项目编号.*:.*JJWL.*$',
    r'^.*采购.*$',
    r'^.*报价文件.*$',
    r'^.*台州第一技师学院.*车铣复合机床采购.*$',
    # Empty or very short titles
    r'^[、，,．.·:\s]*$',
    # UUID-like strings
    r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$',
]

# Compile patterns for efficiency
COMPILED_NOISE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in NOISE_PATTERNS]


class TitleNormalizer:
    """
    Normalize tree node titles with hierarchical numbering
    """

    def __init__(self, debug: bool = False, max_title_length: int = 100):
        """
        Args:
            debug: Enable debug output
            max_title_length: Maximum length for title content (default 100 chars)
        """
        self.debug = debug
        self.max_title_length = max_title_length
        self.stats = {
            "total_nodes": 0,
            "normalized_count": 0,
            "skipped_count": 0,
            "truncated_count": 0,
            "noise_count": 0,
            "display_title_count": 0,
        }

    def _is_noise_node(self, title: str) -> bool:
        """
        Check if a title represents noise (headers, footers, metadata)

        Args:
            title: Title to check

        Returns:
            True if the title matches noise patterns
        """
        if not title:
            return True

        title = title.strip()

        # Check against all noise patterns
        for pattern in COMPILED_NOISE_PATTERNS:
            if pattern.match(title):
                return True

        # Check for very short titles after cleaning (likely garbage)
        clean = self._extract_title_content(title)
        if len(clean) <= 2 and not any(c.isdigit() for c in clean):
            return True

        return False
    
    def normalize_tree(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize all node titles in the tree
        
        Args:
            tree: Tree structure (nested dict)
            
        Returns:
            Tree with normalized titles
        """
        if self.debug:
            print("\n" + "="*70)
            print("🔤 TITLE NORMALIZATION")
            print("="*70)
        
        # Start normalization from root's children (level 1)
        self._normalize_node(tree, level=0, parent_number="")
        
        if self.debug:
            print("\n" + "="*70)
            print(f"✓ Normalized {self.stats['normalized_count']} titles")
            print(f"  Skipped {self.stats['skipped_count']} titles (already numeric)")
            print(f"  Total nodes: {self.stats['total_nodes']}")
            print("="*70)
        
        return tree
    
    def _normalize_node(self, node: Dict[str, Any], level: int, parent_number: str, node_index: int = 0):
        """
        Recursively normalize node titles

        Now: ONLY assigns node_ids, preserves original titles completely
        """
        self.stats["total_nodes"] += 1

        # NO TITLE MODIFICATION - preserve PDF TOC titles exactly as-is
        # The title field should remain exactly as extracted from PDF

        # Process children (support both "children" and "nodes" keys)
        children = node.get("children") or node.get("nodes") or []
        for i, child in enumerate(children, start=1):
            # Recursively process each child
            self._normalize_node(child, level=level+1, parent_number=parent_number, node_index=i)
    
    def _extract_title_content(self, title: str) -> str:
        """
        Extract the actual content from a title, removing numbering prefixes
        
        Examples:
            "第一章 概述" → "概述"
            "第二节 定义" → "定义"
            "（一）适用范围" → "适用范围"
            "一、总则" → "总则"
            "1. 投标须知" → "投标须知"
            "1、投标须知" → "投标须知"
            "1 投标须知" → "投标须知"
            "1.1 基本要求" → "基本要求"
            
        Args:
            title: Original title with numbering
            
        Returns:
            Clean title content without numbering prefix
        """
        # Handle None or empty title
        if not title:
            return ""
        
        title = title.strip()
        
        # Pattern 1: Chinese chapter/section (第X章, 第X节, 第X条)
        title = re.sub(r'^第[零一二三四五六七八九十百千万\d]+[章节条款项部分篇]\s*[、.．·:\s]*', '', title)
        
        # Pattern 2: Parenthesized Chinese numbers (（一）, （二）, (1), (2))
        title = re.sub(r'^[（(][零一二三四五六七八九十百千万\d]+[）)]\s*[、.．·:\s]*', '', title)
        
        # Pattern 3: Chinese numbers with punctuation (一、二、三、)
        title = re.sub(r'^[零一二三四五六七八九十百千万]+[、，,．.·:\s]+', '', title)
        
        # Pattern 4: Arabic numbers with punctuation (1. 2、3. 1.1 1.1.1)
        title = re.sub(r'^\d+(\.\d+)*\s*[、，,．.·:\s]*', '', title)
        
        # Pattern 5: Letters with punctuation (A. B、a) b))
        title = re.sub(r'^[A-Za-z]+\s*[、，,．.·:)\s]+', '', title)
        
        # Pattern 6: Roman numerals (I. II、III.)
        title = re.sub(r'^[IVXivx]+\s*[、，,．.·:\s]+', '', title)
        
        # Remove leading/trailing whitespace and punctuation
        title = title.strip('、，,．.·: \t')
        
        return title
    
    def get_stats(self) -> Dict[str, int]:
        """Get normalization statistics"""
        return self.stats.copy()

    def enhance_tree_display(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance tree with display_title and is_noise fields.

        This method ADDS new fields without modifying the original title:
        - display_title: Cleaned title for UI display
        - is_noise: Boolean flag for invalid entries

        The original 'title' field is preserved for search/indexing.

        Args:
            tree: Tree structure (nested dict)

        Returns:
            Tree with display_title and is_noise fields added
        """
        if self.debug:
            print("\n" + "="*70)
            print("🎨 DISPLAY TITLE ENHANCEMENT")
            print("="*70)

        self._enhance_node_display(tree, level=0)

        if self.debug:
            print("\n" + "="*70)
            print(f"✓ Enhanced {self.stats['display_title_count']} display titles")
            print(f"  Marked {self.stats['noise_count']} nodes as noise")
            print("="*70)

        return tree

    def _enhance_node_display(self, node: Dict[str, Any], level: int = 0):
        """
        Recursively enhance node with display_title and is_noise

        Args:
            node: Current node
            level: Current depth level
        """
        original_title = node.get("title", "")
        node_id = node.get("node_id", "")
        self.stats["total_nodes"] += 1

        # Skip root node
        if level > 0:
            # Check if this is a noise node
            is_noise = self._is_noise_node(original_title)

            # Generate display_title: prepend node_id to title for display
            # Format: "1 项目概况与招标内容" or "1.1 项目概况"
            if node_id and original_title:
                display_title = f"{node_id} {original_title}"
            else:
                display_title = original_title

            # Add new fields (don't modify original title)
            if display_title != original_title:
                node["display_title"] = display_title
                self.stats["display_title_count"] += 1

            node["is_noise"] = is_noise
            if is_noise:
                self.stats["noise_count"] += 1
                if self.debug:
                    print(f"  [NOISE] '{original_title[:50]}...'")
            elif self.debug:
                print(f"  [DISPLAY] id='{node_id}' title='{original_title[:30]}...' → '{display_title[:40]}...'")

        # Process children (support both "children" and "nodes" keys)
        children = node.get("children") or node.get("nodes") or []
        for child in children:
            self._enhance_node_display(child, level + 1)

    def _generate_display_title(self, title: str) -> str:
        """
        Generate a clean display title from the original title.

        Rules:
        1. Remove numbering prefixes (1 /, 第一章, （一）, etc.)
        2. Remove noise markers
        3. Clean up punctuation
        4. Keep meaningful content

        Args:
            title: Original title

        Returns:
            Clean display title
        """
        if not title:
            return ""

        # First, check if title has format like "1 / 前言"
        # Extract just the content part
        if " / " in title:
            parts = title.split(" / ", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()

        # Use the existing extraction method
        clean = self._extract_title_content(title)

        # Further cleanup for display
        if not clean:
            return title

        # Remove common prefix noise
        clean = re.sub(r'^[（(][^）)]*[）)]\s*', '', clean)  # Remove (xxx) at start
        clean = clean.strip('、，,．.·: \t\n-—_')

        # If result is too short, return more of original
        if len(clean) < 3:
            # Try to preserve more from original
            original = title.strip()
            # Remove just the number prefix like "1 ", "1.1 ", "第一章 "
            original = re.sub(r'^第[^章节条款]*[章节条款]\s*', '', original)
            original = re.sub(r'^\d+(\.\d+)*\s*[、/／]*\s*', '', original)
            original = re.sub(r'^[（(][^）)]*[）)]\s*', '', original)
            original = original.strip('、，,．.·: \t\n-—_')
            if original:
                return original

        return clean if clean else title


def normalize_tree_titles(tree: Dict[str, Any], debug: bool = False) -> Dict[str, Any]:
    """
    Convenience function to normalize tree titles (single node)
    
    Args:
        tree: Single tree node structure
        debug: Enable debug output
        
    Returns:
        Tree with normalized titles
    """
    normalizer = TitleNormalizer(debug=debug)
    return normalizer.normalize_tree(tree)


def normalize_tree_list(tree_list: List[Dict[str, Any]], debug: bool = False) -> List[Dict[str, Any]]:
    """
    Normalize titles for a list of root nodes

    Args:
        tree_list: List of root-level tree nodes
        debug: Enable debug output

    Returns:
        List of trees with normalized titles
    """
    normalizer = TitleNormalizer(debug=debug)

    # Normalize each root node with its index
    for i, node in enumerate(tree_list, start=1):
        # Process this node and its children
        normalizer._normalize_node(node, level=1, parent_number="", node_index=i)

    return tree_list


def enhance_tree_display(tree: Dict[str, Any], debug: bool = False) -> Dict[str, Any]:
    """
    Enhance tree with display_title and is_noise fields.

    Adds:
    - display_title: Cleaned title for UI display (preserves original title)
    - is_noise: Boolean flag to identify invalid entries

    Args:
        tree: Tree structure (nested dict)
        debug: Enable debug output

    Returns:
        Tree with display_title and is_noise fields added
    """
    normalizer = TitleNormalizer(debug=debug)
    return normalizer.enhance_tree_display(tree)


def enhance_tree_list_display(tree_list: List[Dict[str, Any]], debug: bool = False) -> List[Dict[str, Any]]:
    """
    Enhance a list of root nodes with display_title and is_noise fields.

    Args:
        tree_list: List of root-level tree nodes
        debug: Enable debug output

    Returns:
        List of trees with display_title and is_noise fields added
    """
    normalizer = TitleNormalizer(debug=debug)

    for node in tree_list:
        normalizer._enhance_node_display(node, level=1)

    return tree_list


if __name__ == "__main__":
    # Test cases
    import json
    
    test_tree = {
        "id": "root",
        "title": "文档根节点",
        "children": [
            {
                "id": "0001",
                "title": "第一章 总则",
                "children": [
                    {"id": "0002", "title": "第一节 适用范围", "children": []},
                    {"id": "0003", "title": "第二节 定义", "children": [
                        {"id": "0004", "title": "（一）投标人", "children": []},
                        {"id": "0005", "title": "（二）招标人", "children": []},
                    ]},
                ]
            },
            {
                "id": "0006",
                "title": "第二章 投标人须知",
                "children": [
                    {"id": "0007", "title": "一、说明", "children": []},
                    {"id": "0008", "title": "二、投标文件", "children": []},
                ]
            },
            {
                "id": "0009",
                "title": "3、评标",
                "children": [
                    {"id": "0010", "title": "3.1 评标委员会", "children": []},
                    {"id": "0011", "title": "3.2 评标程序", "children": []},
                ]
            },
        ]
    }
    
    print("Original tree:")
    print(json.dumps(test_tree, ensure_ascii=False, indent=2))
    
    normalized_tree = normalize_tree_titles(test_tree, debug=True)
    
    print("\n\nNormalized tree:")
    print(json.dumps(normalized_tree, ensure_ascii=False, indent=2))
