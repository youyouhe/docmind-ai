#!/usr/bin/env python3
"""
分析PDF树形结构中的页码问题
检查子节点的结尾页码是否与父节点相同的问题
"""

import json
import sys

def analyze_node_pages(node, parent_info=None, issues=[], depth=0):
    """
    递归分析节点的页码问题
    
    Args:
        node: 当前节点
        parent_info: 父节点信息 {title, start, end}
        issues: 发现的问题列表
        depth: 当前深度
    """
    title = node.get('title', 'Unknown')
    start_page = node.get('page_start') or node.get('start_page')
    end_page = node.get('page_end') or node.get('end_page')
    children = node.get('children', [])
    
    indent = "  " * depth
    
    # 检查当前节点是否有页码信息
    if start_page is not None and end_page is not None:
        # 如果有父节点，检查子节点的结尾页码是否与父节点相同
        if parent_info and end_page == parent_info['end']:
            issue = {
                'depth': depth,
                'title': title,
                'start_page': start_page,
                'end_page': end_page,
                'parent_title': parent_info['title'],
                'parent_start': parent_info['start'],
                'parent_end': parent_info['end'],
                'problem': '子节点结尾页码与父节点相同'
            }
            issues.append(issue)
            print(f"{indent}X Problem: '{title}' (page {start_page}-{end_page})")
            print(f"{indent}   Parent: '{parent_info['title']}' (page {parent_info['start']}-{parent_info['end']})")
            print(f"{indent}   Issue: Child end page {end_page} same as parent end page")
            print()
        
        # 检查页码范围是否合理
        if start_page > end_page:
            issue = {
                'depth': depth,
                'title': title,
                'start_page': start_page,
                'end_page': end_page,
                'problem': '起始页码大于结尾页码'
            }
            issues.append(issue)
            print(f"{indent}X Problem: '{title}' - start page {start_page} > end page {end_page}")
            print()
        
        # 递归处理子节点
        current_info = {
            'title': title,
            'start': start_page,
            'end': end_page
        }
        
        for child in children:
            analyze_node_pages(child, current_info, issues, depth + 1)
    else:
        # 没有页码信息的节点
        for child in children:
            analyze_node_pages(child, parent_info, issues, depth + 1)

def main(file_path):
    print(f"Analyzing file: {file_path}\n")
    print("=" * 80)
    print()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        issues = []
        
        # 检查是否是数组还是单个对象
        if isinstance(data, list):
            print(f"Document contains {len(data)} root nodes\n")
            for idx, root in enumerate(data):
                print(f"Root node #{idx + 1}: {root.get('title', 'Unknown')}")
                analyze_node_pages(root, None, issues, 0)
        else:
            print(f"Root node: {data.get('title', 'Unknown')}\n")
            analyze_node_pages(data, None, issues, 0)
        
        print("=" * 80)
        print(f"\nSummary: Found {len(issues)} issues\n")
        
        # 统计问题类型
        same_end_page_count = sum(1 for i in issues if i['problem'] == '子节点结尾页码与父节点相同')
        invalid_range_count = sum(1 for i in issues if i['problem'] == '起始页码大于结尾页码')
        
        print(f"- Child end page same as parent: {same_end_page_count}")
        print(f"- Invalid page range (start > end): {invalid_range_count}")
        
        if same_end_page_count > 0:
            print("\nExplanation:")
            print("Child nodes should not have the same end page as their parent.")
            print("This usually means:")
            print("1. The child section's page range is calculated incorrectly")
            print("2. Should determine correct end page based on next sibling or child")
            print("3. If it's the last child, its end page should be less than parent's end page")
        
        return len(issues)
        
    except FileNotFoundError:
        print(f"X Error: File not found - {file_path}")
        return -1
    except json.JSONDecodeError as e:
        print(f"X Error: JSON parsing failed - {e}")
        return -1
    except Exception as e:
        print(f"X Error: {e}")
        return -1

if __name__ == "__main__":
    file_path = "./data/parsed/e5358777-b09d-4d6a-b4dd-16b9f16d4f1e_tree.json"
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    exit_code = main(file_path)
    sys.exit(0 if exit_code >= 0 else 1)
