#!/usr/bin/env python3
"""
检查PDF以验证节点的实际页码范围
对比TOC标注的页码与我们计算的页码
"""

import json
import sys

def check_shared_pages(file_path):
    """
    检查可能共享页面的相邻节点
    """
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 如果是API格式
    if 'structure' in data:
        tree = data['structure']
    elif 'children' in data:
        tree = data['children']
    elif isinstance(data, list):
        tree = data
    else:
        tree = [data]
    
    issues = []
    
    def analyze_siblings(nodes, parent_title=''):
        """分析兄弟节点之间的关系"""
        for i in range(len(nodes) - 1):
            node = nodes[i]
            next_node = nodes[i + 1]
            
            title = node.get('title', '')
            start = node.get('start_index') or node.get('page_start')
            end = node.get('end_index') or node.get('page_end')
            
            next_title = next_node.get('title', '')
            next_start = next_node.get('start_index') or next_node.get('page_start')
            
            children = node.get('nodes', []) or node.get('children', [])
            next_children = next_node.get('nodes', []) or next_node.get('children', [])
            
            # 检查：当前节点的end = next_start - 1
            # 这意味着它们可能实际上共享一页
            if start and end and next_start:
                if end == next_start - 1:
                    # 当前算法认为它们不共享页面
                    # 但实际上可能共享 next_start 这一页
                    issues.append({
                        'parent': parent_title,
                        'node1': title,
                        'node1_start': start,
                        'node1_end': end,
                        'node2': next_title,
                        'node2_start': next_start,
                        'potential_shared_page': next_start,
                        'current_gap': 1  # end=N, next_start=N+1, 中间没有gap
                    })
            
            # 递归检查子节点
            if children:
                analyze_siblings(children, title)
            if next_children:
                analyze_siblings(next_children, next_title)
        
        # 检查最后一个节点的子节点
        if nodes:
            last_node = nodes[-1]
            last_children = last_node.get('nodes', []) or last_node.get('children', [])
            if last_children:
                analyze_siblings(last_children, last_node.get('title', ''))
    
    analyze_siblings(tree)
    
    return issues


def main(file_path):
    print("=" * 80)
    print("SHARED PAGE ANALYSIS")
    print("=" * 80)
    print()
    print("Analyzing potential cases where adjacent sections might share a page...")
    print()
    
    issues = check_shared_pages(file_path)
    
    print(f"Found {len(issues)} potential shared-page situations\n")
    
    if issues:
        print("Current calculation: node1.end = node2.start - 1")
        print("Potential issue: node1 might actually end on node2.start (shared page)")
        print()
        print("-" * 80)
        
        for i, issue in enumerate(issues[:20], 1):
            print(f"\n{i}. {issue['node1']}")
            print(f"   Current: [{issue['node1_start']}-{issue['node1_end']}]")
            print(f"   Next sibling: {issue['node2']} starts at {issue['node2_start']}")
            print(f"   Potential: [{issue['node1_start']}-{issue['node2_start']}] (if they share page {issue['node2_start']})")
            
            if issue['parent']:
                print(f"   Parent: {issue['parent']}")
        
        if len(issues) > 20:
            print(f"\n... and {len(issues) - 20} more cases")
        
        print()
        print("=" * 80)
        print("QUESTION:")
        print("=" * 80)
        print("Should we change the algorithm to allow overlapping pages?")
        print()
        print("Current:  node1.end = node2.start - 1  (no overlap)")
        print("Proposed: node1.end = node2.start      (can share last/first page)")
        print()
        print("Trade-off:")
        print("+ More accurate when sections actually share pages")
        print("- May cause confusion with overlapping ranges")
        print("=" * 80)
    
    return len(issues)


if __name__ == "__main__":
    file_path = "./data/test_fix/e5358777-b09d-4d6a-b4dd-16b9f16d4f1e_structure.json"
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    main(file_path)
