#!/usr/bin/env python3
"""
分析相邻节点之间的页码间隙
检查是否存在不必要的间隙（gap）
"""

import json
import sys

def analyze_gaps(tree, parent_info=None, gaps=[], depth=0):
    """
    分析树中的页码间隙
    
    检查：如果节点A的end是N，节点B的start是N+2，则中间有1页的gap
    """
    
    for i, node in enumerate(tree):
        title = node.get('title', 'Unknown')
        start = node.get('start_index') or node.get('page_start')
        end = node.get('end_index') or node.get('page_end')
        children = node.get('nodes', []) or node.get('children', [])
        
        indent = "  " * depth
        
        # 检查与下一个兄弟节点之间的间隙
        if i + 1 < len(tree):
            next_node = tree[i + 1]
            next_start = next_node.get('start_index') or next_node.get('page_start')
            next_title = next_node.get('title', 'Unknown')
            
            if start and end and next_start:
                gap = next_start - end - 1
                
                if gap > 0:
                    gaps.append({
                        'depth': depth,
                        'node1': title,
                        'node1_range': f'[{start}-{end}]',
                        'node2': next_title,
                        'node2_start': next_start,
                        'gap_pages': gap,
                        'missing_pages': list(range(end + 1, next_start))
                    })
                    print(f"{indent}Gap detected:")
                    print(f"{indent}  {title[:40]:42} ends at {end}")
                    print(f"{indent}  {next_title[:40]:42} starts at {next_start}")
                    print(f"{indent}  Missing pages: {list(range(end + 1, next_start))}")
                    print()
                elif gap < 0:
                    # 重叠
                    print(f"{indent}Overlap detected:")
                    print(f"{indent}  {title[:40]:42} ends at {end}")
                    print(f"{indent}  {next_title[:40]:42} starts at {next_start}")
                    print(f"{indent}  Overlap: {abs(gap)} pages")
                    print()
        
        # 递归处理子节点
        if children:
            analyze_gaps(children, {'title': title, 'start': start, 'end': end}, gaps, depth + 1)
    
    return gaps


def main(file_path):
    print(f"Analyzing gaps in: {file_path}\n")
    print("=" * 80)
    print()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        gaps = []
        
        # 检查数据格式
        if 'structure' in data:
            # PageIndex internal format
            tree = data['structure']
        elif 'children' in data:
            # API format with root node
            tree = data['children']
        elif isinstance(data, list):
            # List of root nodes
            tree = data
        else:
            print("Unknown data format")
            return -1
        
        gaps = analyze_gaps(tree)
        
        print("=" * 80)
        print(f"\nSummary: Found {len(gaps)} gaps\n")
        
        if len(gaps) > 0:
            # 统计间隙大小
            gap_sizes = {}
            for gap in gaps:
                size = gap['gap_pages']
                gap_sizes[size] = gap_sizes.get(size, 0) + 1
            
            print("Gap distribution:")
            for size in sorted(gap_sizes.keys()):
                count = gap_sizes[size]
                print(f"  {size} page gap: {count} occurrences")
            
            print("\nPotential issues:")
            print("- If two sections share the same starting page,")
            print("  the first section's end should be on that page, not the previous page")
            print("- Check if the TOC indicates overlapping page ranges")
        else:
            print("No gaps found - all page ranges are consecutive or overlapping")
        
        return len(gaps)
        
    except FileNotFoundError:
        print(f"Error: File not found - {file_path}")
        return -1
    except json.JSONDecodeError as e:
        print(f"Error: JSON parsing failed - {e}")
        return -1
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return -1


if __name__ == "__main__":
    file_path = "./data/test_fix/e5358777-b09d-4d6a-b4dd-16b9f16d4f1e_structure.json"
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    exit_code = main(file_path)
    sys.exit(0 if exit_code >= 0 else 1)
