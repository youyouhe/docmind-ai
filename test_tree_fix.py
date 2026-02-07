#!/usr/bin/env python3
"""
测试tree_builder的修复
模拟一个简单的树结构来验证页码计算逻辑
"""

def simulate_tree_calculation():
    """模拟树构建过程"""
    
    # 模拟list_to_tree后的结构
    tree = [
        {
            'title': 'Chapter 1',
            'start_index': 21,  # list_to_tree已经将physical_index转为start_index
            'nodes': [
                {
                    'title': '1.1',
                    'start_index': 24,
                    'nodes': []
                },
                {
                    'title': '1.2',
                    'start_index': 32,
                    'nodes': []
                },
                {
                    'title': '1.3',
                    'start_index': 52,
                    'nodes': []
                },
                {
                    'title': 'Exercises',
                    'start_index': 78,
                    'nodes': []
                }
            ]
        },
        {
            'title': 'Chapter 2',
            'start_index': 87,
            'nodes': []
        }
    ]
    
    total_pages = 200
    
    def process_node(node, next_sibling_start=None, parent_end=None):
        """处理单个节点（修复后的逻辑）"""
        start = node.get('start_index', 1)
        
        if 'nodes' in node and node['nodes']:
            # 有子节点
            children = node['nodes']
            
            # 计算节点边界
            if next_sibling_start:
                node_boundary = next_sibling_start - 1
            elif parent_end:
                node_boundary = parent_end
            else:
                node_boundary = total_pages
            
            # 处理子节点
            for i, child in enumerate(children):
                next_start = None
                if i + 1 < len(children):
                    # 修复后：使用start_index而不是physical_index
                    next_start = children[i + 1].get('start_index')
                
                process_node(child, next_start, node_boundary)
            
            # 父节点的end是最后一个子节点的end
            last_child = children[-1]
            end = last_child.get('end_index', start)
        else:
            # 叶子节点
            if next_sibling_start:
                end = next_sibling_start - 1
            elif parent_end:
                end = parent_end
            else:
                end = min(start + 10, total_pages)
        
        node['end_index'] = max(end, start)
    
    # 处理所有根节点
    for i, node in enumerate(tree):
        next_start = None
        if i + 1 < len(tree):
            # 修复后：使用start_index
            next_start = tree[i + 1].get('start_index')
        
        process_node(node, next_start, total_pages)
    
    return tree


def print_tree(tree, indent=0):
    """打印树结构"""
    for node in tree:
        title = node.get('title', '')
        start = node.get('start_index', '?')
        end = node.get('end_index', '?')
        prefix = "  " * indent
        print(f"{prefix}[{start}-{end}] {title}")
        
        if 'nodes' in node and node['nodes']:
            print_tree(node['nodes'], indent + 1)


if __name__ == "__main__":
    print("Testing tree calculation with fix...\n")
    print("=" * 60)
    
    tree = simulate_tree_calculation()
    print_tree(tree)
    
    print("\n" + "=" * 60)
    print("\nExpected results:")
    print("  Chapter 1: [21-86] (last child ends at 86)")
    print("    1.1: [24-31] (next sibling at 32)")
    print("    1.2: [32-51] (next sibling at 52)")
    print("    1.3: [52-77] (next sibling at 78)")
    print("    Exercises: [78-86] (parent boundary)")
    print("  Chapter 2: [87-97] (estimated 10 pages)")
    
    # 验证结果
    print("\n" + "=" * 60)
    print("Verification:")
    
    ch1 = tree[0]
    ch1_children = ch1['nodes']
    
    expected = [
        ('Chapter 1', 21, 86),
        ('1.1', 24, 31),
        ('1.2', 32, 51),
        ('1.3', 52, 77),
        ('Exercises', 78, 86),
        ('Chapter 2', 87, 97)
    ]
    
    actual = [
        (ch1['title'], ch1['start_index'], ch1['end_index']),
        (ch1_children[0]['title'], ch1_children[0]['start_index'], ch1_children[0]['end_index']),
        (ch1_children[1]['title'], ch1_children[1]['start_index'], ch1_children[1]['end_index']),
        (ch1_children[2]['title'], ch1_children[2]['start_index'], ch1_children[2]['end_index']),
        (ch1_children[3]['title'], ch1_children[3]['start_index'], ch1_children[3]['end_index']),
        (tree[1]['title'], tree[1]['start_index'], tree[1]['end_index'])
    ]
    
    all_pass = True
    for exp, act in zip(expected, actual):
        title_exp, start_exp, end_exp = exp
        title_act, start_act, end_act = act
        
        match = start_exp == start_act and end_exp == end_act
        status = "✓ PASS" if match else "✗ FAIL"
        
        print(f"{status}: {title_act:15} expected [{start_exp}-{end_exp}], got [{start_act}-{end_act}]")
        
        if not match:
            all_pass = False
    
    print("\n" + "=" * 60)
    if all_pass:
        print("✓ All tests PASSED! Fix is working correctly.")
    else:
        print("✗ Some tests FAILED. Please review the logic.")
