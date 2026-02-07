#!/usr/bin/env python3
"""
打印PDF树形结构的摘要信息
"""

import json
import sys

def print_node_summary(node, depth=0, max_depth=3, parent_end=None):
    """
    打印节点摘要信息
    """
    title = node.get('title', 'Unknown')
    start_page = node.get('page_start') or node.get('start_page')
    end_page = node.get('page_end') or node.get('end_page')
    children = node.get('children', [])
    
    indent = "  " * depth
    
    # 打印当前节点信息
    page_info = f"[{start_page}-{end_page}]" if start_page is not None else "[no pages]"
    
    # 检查是否有问题
    issue_marker = ""
    if parent_end is not None and end_page is not None and end_page == parent_end:
        issue_marker = " <-- ISSUE: same end as parent!"
    
    print(f"{indent}{page_info} {title}{issue_marker}")
    
    # 只打印到指定深度
    if depth < max_depth:
        for idx, child in enumerate(children):
            print_node_summary(child, depth + 1, max_depth, end_page)
            # 只打印前几个子节点
            if idx >= 2 and len(children) > 4:
                remaining = len(children) - 3
                print(f"{indent}  ... and {remaining} more children")
                # 打印最后一个子节点
                if remaining > 0:
                    print_node_summary(children[-1], depth + 1, max_depth, end_page)
                break

def main(file_path):
    print(f"Tree structure summary: {file_path}\n")
    print("=" * 80)
    print()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 检查是否是数组还是单个对象
        if isinstance(data, list):
            print(f"Document contains {len(data)} root nodes\n")
            for idx, root in enumerate(data):
                print(f"\nRoot #{idx + 1}:")
                print_node_summary(root, 0, max_depth=4)
        else:
            print_node_summary(data, 0, max_depth=4)
        
        print("\n" + "=" * 80)
        
    except FileNotFoundError:
        print(f"X Error: File not found - {file_path}")
        return -1
    except json.JSONDecodeError as e:
        print(f"X Error: JSON parsing failed - {e}")
        return -1
    except Exception as e:
        print(f"X Error: {e}")
        import traceback
        traceback.print_exc()
        return -1

if __name__ == "__main__":
    file_path = "./data/parsed/e5358777-b09d-4d6a-b4dd-16b9f16d4f1e_tree.json"
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    main(file_path)
