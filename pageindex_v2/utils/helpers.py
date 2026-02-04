"""
Utility Helpers - JSON parsing, tree operations, text processing
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple


def extract_json(content: str) -> Dict[str, Any]:
    """
    Extract JSON from LLM response with robust parsing
    Handles markdown code blocks and common formatting issues
    """
    if not content:
        return {}
    
    try:
        # Try direct parse first
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Try to extract from markdown
    try:
        # Find ```json ... ``` or ``` ... ```
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7
            end_idx = content.find("```", start_idx)
            json_str = content[start_idx:end_idx].strip()
        else:
            start_idx = content.find("```")
            if start_idx != -1:
                start_idx += 3
                end_idx = content.find("```", start_idx)
                json_str = content[start_idx:end_idx].strip()
            else:
                # No markdown, try to clean entire content
                json_str = content.strip()
        
        # Clean up common issues
        json_str = json_str.replace('None', 'null')
        json_str = json_str.replace('True', 'true')
        json_str = json_str.replace('False', 'false')
        # Remove trailing commas
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
        
        return json.loads(json_str)
        
    except Exception as e:
        print(f"[JSON EXTRACT ERROR] {e}")
        print(f"[CONTENT PREVIEW] {content[:200]}...")
        return {}


def convert_page_to_int(page_value: Any) -> Optional[int]:
    """Convert various page formats to integer"""
    if page_value is None:
        return None
    
    if isinstance(page_value, int):
        return page_value
    
    if isinstance(page_value, str):
        # Extract number from string
        match = re.search(r'\d+', page_value)
        if match:
            return int(match.group())
    
    return None


def convert_physical_index_to_int(structure: List[Dict]) -> List[Dict]:
    """
    Convert <physical_index_X> tags to integers
    """
    for item in structure:
        if 'physical_index' in item:
            idx = item['physical_index']
            if isinstance(idx, str) and '<physical_index_' in idx:
                match = re.search(r'<physical_index_(\d+)>', idx)
                if match:
                    item['physical_index'] = int(match.group(1))
                else:
                    item['physical_index'] = None
            elif isinstance(idx, str):
                # Try direct conversion
                try:
                    item['physical_index'] = int(idx)
                except:
                    item['physical_index'] = None
    
    return structure


def list_to_tree(flat_list: List[Dict]) -> List[Dict]:
    """
    Convert flat list with structure codes to hierarchical tree
    
    Input: [{"structure": "1.1", "title": "xxx", ...}]
    Output: Nested tree structure
    """
    if not flat_list:
        return []
    
    # Sort by structure code
    def sort_key(item):
        struct = item.get('structure', '')
        parts = struct.split('.')
        return [int(p) if p.isdigit() else 999 for p in parts]
    
    sorted_list = sorted(flat_list, key=sort_key)
    
    # Build tree
    tree = []
    stack = []
    
    for item in sorted_list:
        struct = item.get('structure', '')
        level = len(struct.split('.'))
        
        # Create node
        node = {
            'title': item.get('title', ''),
            'start_index': item.get('physical_index'),
            'nodes': [],
        }
        
        # Add optional fields
        if 'node_id' in item:
            node['node_id'] = item['node_id']
        if 'summary' in item:
            node['summary'] = item['summary']
        
        # Find parent
        while stack and len(stack[-1]['struct'].split('.')) >= level:
            stack.pop()
        
        if stack:
            # Add as child
            if 'nodes' not in stack[-1]['node']:
                stack[-1]['node']['nodes'] = []
            stack[-1]['node']['nodes'].append(node)
        else:
            # Add to root
            tree.append(node)
        
        # Push to stack
        stack.append({'struct': struct, 'node': node})
    
    return tree


def tree_to_list(tree: List[Dict], parent_struct: str = "") -> List[Dict]:
    """
    Flatten tree to list with structure codes
    """
    result = []
    
    for i, node in enumerate(tree, 1):
        # Build structure code
        if parent_struct:
            struct = f"{parent_struct}.{i}"
        else:
            struct = str(i)
        
        # Create flat item
        item = {
            'structure': struct,
            'title': node.get('title', ''),
        }
        
        if 'start_index' in node:
            item['physical_index'] = node['start_index']
        if 'end_index' in node:
            item['end_index'] = node['end_index']
        
        result.append(item)
        
        # Recurse into children
        if 'nodes' in node and node['nodes']:
            result.extend(tree_to_list(node['nodes'], struct))
    
    return result


def validate_structure_depth(tree: List[Dict], max_depth: int = 4) -> Tuple[bool, List[str]]:
    """
    Validate tree depth doesn't exceed max_depth
    Returns (is_valid, error_messages)
    """
    errors = []
    
    def check_depth(node, current_depth, path):
        if current_depth > max_depth:
            errors.append(f"Depth {current_depth} exceeds limit at: {' > '.join(path)}")
            return
        
        if 'nodes' in node:
            for child in node['nodes']:
                check_depth(child, current_depth + 1, path + [child.get('title', '')])
    
    for node in tree:
        check_depth(node, 1, [node.get('title', '')])
    
    return len(errors) == 0, errors


def add_node_ids(tree: List[Dict], prefix: str = "") -> None:
    """
    Add sequential IDs to tree nodes (0000, 0001, etc.)
    """
    counter = [0]
    
    def assign_id(node, parent_id=""):
        current_id = f"{parent_id}{counter[0]:04d}"
        node['node_id'] = current_id
        counter[0] += 1
        
        if 'nodes' in node:
            for child in node['nodes']:
                assign_id(child, current_id)
    
    for node in tree:
        assign_id(node)


def calculate_tree_depth(node: Dict) -> int:
    """Calculate maximum depth of a tree node"""
    if 'nodes' not in node or not node['nodes']:
        return 1
    
    return 1 + max(calculate_tree_depth(child) for child in node['nodes'])


def merge_deep_nodes(tree: List[Dict], max_depth: int = 4) -> List[Dict]:
    """
    Merge nodes that exceed max_depth into their parent
    """
    def process_node(node, current_depth):
        if current_depth >= max_depth:
            # Remove children, merge their content
            if 'nodes' in node:
                # Flatten children titles into current node
                child_titles = []
                def collect_titles(n):
                    child_titles.append(n.get('title', ''))
                    if 'nodes' in n:
                        for c in n['nodes']:
                            collect_titles(c)
                
                for child in node['nodes']:
                    collect_titles(child)
                
                if child_titles:
                    node['sub_items'] = child_titles
                del node['nodes']
        else:
            # Recurse
            if 'nodes' in node:
                for child in node['nodes']:
                    process_node(child, current_depth + 1)
    
    for node in tree:
        process_node(node, 1)
    
    return tree


def transform_dots_to_colon(text: str) -> str:
    """
    Transform TOC dots (...... 5) to colon format (:: 5)
    """
    # Replace 5+ dots with colon
    text = re.sub(r'\.{5,}', ': ', text)
    # Handle dots with spaces
    text = re.sub(r'(?:\. ){5,}\.?', ': ', text)
    return text


def group_pages_by_tokens(
    pages: List[Tuple[str, int]], 
    max_tokens: int = 20000
) -> List[List[int]]:
    """
    Group page indices by token limit
    Returns list of groups, each containing page indices
    """
    groups = []
    current_group = []
    current_tokens = 0
    
    for i, (content, tokens) in enumerate(pages):
        if current_tokens + tokens > max_tokens and current_group:
            groups.append(current_group)
            current_group = [i]
            current_tokens = tokens
        else:
            current_group.append(i)
            current_tokens += tokens
    
    if current_group:
        groups.append(current_group)
    
    return groups


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """
    Count tokens in text (approximation)
    """
    # Simple approximation: 1 token ≈ 4 chars for English, 2 chars for Chinese
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    
    # Chinese: ~2 chars per token, English: ~4 chars per token
    return (chinese_chars // 2) + (other_chars // 4)


def get_leaf_nodes(structure: List[Dict]) -> List[Dict]:
    """
    识别扁平结构中的叶子节点（没有子节点的项）
    
    叶子节点判断规则：
    - structure="1.2.3"的项，如果后面没有"1.2.3.x"，则是叶子
    - structure="1"的项，如果后面有"1.1"，则不是叶子
    
    Args:
        structure: 扁平的TOC结构列表
    
    Returns:
        叶子节点列表
    
    Example:
        Input: [
            {"structure": "1", "title": "第一章"},
            {"structure": "1.1", "title": "引言"},
            {"structure": "1.2", "title": "背景"},
            {"structure": "2", "title": "第二章"}
        ]
        Output: [
            {"structure": "1.1", "title": "引言"},  # 叶子
            {"structure": "1.2", "title": "背景"},  # 叶子
            {"structure": "2", "title": "第二章"}   # 叶子
        ]
    """
    if not structure:
        return []
    
    leaf_nodes = []
    
    for i, item in enumerate(structure):
        struct_code = item.get('structure', '')
        if not struct_code:
            # 没有structure code的项视为叶子
            leaf_nodes.append(item)
            continue
        
        # 检查后续项是否有以该code为前缀的子项
        is_leaf = True
        for j in range(i + 1, len(structure)):
            next_code = structure[j].get('structure', '')
            
            # 检查是否是当前项的子项
            # 如果next_code以"struct_code."开头，说明是子项
            if next_code.startswith(struct_code + '.'):
                is_leaf = False
                break
            
            # 如果遇到不以struct_code开头的项，说明已经到下一个分支了
            if not next_code.startswith(struct_code):
                break
        
        if is_leaf:
            leaf_nodes.append(item)
    
    return leaf_nodes


def count_leaf_nodes(structure: List[Dict]) -> int:
    """
    统计叶子节点数量
    
    Args:
        structure: 扁平的TOC结构列表
    
    Returns:
        叶子节点数量
    """
    return len(get_leaf_nodes(structure))
