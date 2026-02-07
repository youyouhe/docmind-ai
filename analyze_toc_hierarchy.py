"""
诊断工具：分析 TOC 层级结构问题
"""
import fitz  # PyMuPDF
import json
from pathlib import Path
import sys
import io

# Force UTF-8 output for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def analyze_embedded_toc(pdf_path):
    """分析 PDF 内嵌 TOC 结构"""
    print("=" * 80)
    print("📚 分析内嵌 TOC 结构")
    print("=" * 80)
    
    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    
    print(f"\n原始 TOC 条目数: {len(toc)}")
    print("\n内嵌 TOC 结构 (level, title, page):")
    print("-" * 80)
    
    for i, (level, title, page) in enumerate(toc, 1):
        indent = "  " * (level - 1)
        print(f"{i:3d}. {indent}[L{level}] {title} (页码: {page})")
    
    doc.close()
    return toc

def analyze_parsed_tree(tree_path):
    """分析已解析的树结构"""
    print("\n" + "=" * 80)
    print("🌳 分析解析后的树结构")
    print("=" * 80)
    
    with open(tree_path, 'r', encoding='utf-8') as f:
        tree = json.load(f)
    
    def print_node(node, depth=0):
        indent = "  " * depth
        title = node.get('title', 'Unknown')
        level = node.get('level', 0)
        page_start = node.get('page_start', '?')
        page_end = node.get('page_end', '?')
        node_id = node.get('id', '?')
        
        if depth > 0:  # Skip root
            print(f"{indent}[L{level}] {title}")
            print(f"{indent}     ID: {node_id}, Pages: {page_start}-{page_end}")
        
        for child in node.get('children', []):
            print_node(child, depth + 1)
    
    print("\n解析后的树结构:")
    print("-" * 80)
    print_node(tree)
    
    return tree

def compare_structures(toc, tree):
    """对比 TOC 和树结构，找出差异"""
    print("\n" + "=" * 80)
    print("🔍 对比分析")
    print("=" * 80)
    
    # 提取 TOC 中的章节标题
    toc_chapters = []
    for level, title, page in toc:
        if '第' in title and '章' in title:
            toc_chapters.append((level, title, page))
    
    print(f"\n内嵌 TOC 中找到的章节:")
    for level, title, page in toc_chapters:
        print(f"  [L{level}] {title} (页码: {page})")
    
    # 提取树中的章节
    def extract_chapters(node, chapters=None):
        if chapters is None:
            chapters = []
        
        title = node.get('title', '')
        if '第' in title and '章' in title:
            chapters.append({
                'title': title,
                'level': node.get('level'),
                'page_start': node.get('page_start'),
                'id': node.get('id')
            })
        
        for child in node.get('children', []):
            extract_chapters(child, chapters)
        
        return chapters
    
    tree_chapters = extract_chapters(tree)
    
    print(f"\n解析树中找到的章节:")
    for ch in tree_chapters:
        print(f"  [L{ch['level']}] {ch['title']} (页码: {ch['page_start']}, ID: {ch['id']})")
    
    # 识别问题
    print("\n" + "=" * 80)
    print("⚠️  发现的问题")
    print("=" * 80)
    
    issues = []
    
    # 问题1: 章节数量不匹配
    if len(toc_chapters) != len(tree_chapters):
        issues.append(f"章节数量不匹配: TOC 有 {len(toc_chapters)} 章，树中只有 {len(tree_chapters)} 章")
    
    # 问题2: 检查第四章的位置
    for ch in tree_chapters:
        if '第四章' in ch['title']:
            if ch['level'] != 1:
                issues.append(f"第四章层级错误: 应该是 L1，实际是 L{ch['level']} (ID: {ch['id']})")
    
    # 问题3: 检查每个章节是否存在
    expected_chapters = ['第一章', '第二章', '第三章', '第四章', '第五章', '第六章']
    found_chapters = [ch['title'] for ch in tree_chapters]
    
    for expected in expected_chapters:
        found = any(expected in title for title in found_chapters)
        if not found:
            issues.append(f"缺失章节: {expected}")
    
    if issues:
        for i, issue in enumerate(issues, 1):
            print(f"\n{i}. {issue}")
    else:
        print("\n✅ 未发现明显问题")
    
    return issues

def suggest_optimizations(issues):
    """基于问题提出优化建议"""
    print("\n" + "=" * 80)
    print("💡 优化建议")
    print("=" * 80)
    
    suggestions = []
    
    if any('层级错误' in issue for issue in issues):
        suggestions.append({
            'title': '修复层级判断逻辑',
            'description': '第四章被错误地嵌套在第二章下面。需要改进 _build_tree_from_structure() 方法中的层级判断逻辑。',
            'file': 'lib/docmind-ai/pageindex_v2/main.py',
            'location': '_build_tree_from_structure() 方法',
            'strategy': '检查 structure_code 解析逻辑，确保正确识别章节层级（"1", "2", "3", "4" 应该都是 level=1）'
        })
    
    if any('缺失章节' in issue for issue in issues):
        suggestions.append({
            'title': '改进 TOC 过滤逻辑',
            'description': '某些章节被过滤掉了。需要检查 _is_valid_toc_title() 方法是否过于严格。',
            'file': 'lib/docmind-ai/pageindex_v2/main.py',
            'location': '_is_valid_toc_title() 方法 (line 1028)',
            'strategy': '放宽对章节标题的过滤条件，确保所有"第X章"格式的标题都被保留'
        })
    
    if any('数量不匹配' in issue for issue in issues):
        suggestions.append({
            'title': '增强结构代码生成',
            'description': 'TOC 条目到树节点的转换过程中丢失了某些章节。',
            'file': 'lib/docmind-ai/pageindex_v2/main.py',
            'location': '_convert_embedded_toc_to_structure() 方法',
            'strategy': '添加日志记录每个 TOC 条目如何被转换，确保所有章节都被正确处理'
        })
    
    # 通用优化建议
    suggestions.append({
        'title': '标准化章节标题',
        'description': '在结构分析前，标准化所有章节标题格式（"第一章"/"1"/"一、"）',
        'file': '新建: lib/docmind-ai/pageindex_v2/title_normalizer.py',
        'location': '新模块',
        'strategy': '创建标题标准化函数，将"1 / 前言"、"第一章 招标公告"等统一转换为规范格式'
    })
    
    suggestions.append({
        'title': '添加层级验证',
        'description': '树构建完成后，验证章节层级是否合理（如第4章不应是第2章的子节点）',
        'file': 'lib/docmind-ai/pageindex_v2/main.py',
        'location': '新方法: _validate_tree_hierarchy()',
        'strategy': '后处理步骤：检测并修正明显的层级错误'
    })
    
    for i, sug in enumerate(suggestions, 1):
        print(f"\n建议 {i}: {sug['title']}")
        print(f"  描述: {sug['description']}")
        print(f"  文件: {sug['file']}")
        print(f"  位置: {sug['location']}")
        print(f"  策略: {sug['strategy']}")
    
    return suggestions

def main():
    # 路径
    pdf_path = Path("data/uploads/40f6c928-f465-4033-8465-8bad6f912750.pdf")
    tree_path = Path("data/parsed/40f6c928-f465-4033-8465-8bad6f912750_tree.json")
    
    if not pdf_path.exists():
        print(f"❌ PDF 文件不存在: {pdf_path}")
        return
    
    if not tree_path.exists():
        print(f"❌ 树文件不存在: {tree_path}")
        return
    
    # 分析
    toc = analyze_embedded_toc(pdf_path)
    tree = analyze_parsed_tree(tree_path)
    issues = compare_structures(toc, tree)
    suggestions = suggest_optimizations(issues)
    
    print("\n" + "=" * 80)
    print("✅ 分析完成")
    print("=" * 80)

if __name__ == "__main__":
    main()
