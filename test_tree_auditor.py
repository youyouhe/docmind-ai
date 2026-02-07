"""
测试Tree Auditor - 审核并修复tree.json

使用方法:
    cd lib/docmind-ai
    python test_tree_auditor.py
"""

import asyncio
import os
import sys

# Fix Windows encoding issues
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pageindex_v2.phases.tree_auditor import audit_tree_file
from pageindex_v2.core.llm_client import LLMClient


async def test_audit():
    """测试审核功能"""
    
    # 配置
    tree_file = "data/parsed/0dd284d5-3bbc-4bc8-aa51-621201f23b33_tree.json"
    
    if not os.path.exists(tree_file):
        print(f"❌ File not found: {tree_file}")
        return
    
    print("="*70)
    print("🔍 Tree Quality Auditor Test")
    print("="*70)
    print(f"\nInput file: {tree_file}")
    print()
    
    # 创建LLM客户端（使用DeepSeek）
    try:
        llm = LLMClient(
            provider="deepseek",
            model="deepseek-chat",  # 使用chat模型（更快更便宜）
            debug=True
        )
        print("✓ LLM client initialized (DeepSeek)")
    except Exception as e:
        print(f"⚠ Failed to initialize LLM: {e}")
        print("  Continuing with rule-based audit only...")
        llm = None
    
    print()
    
    # 执行审核
    try:
        audited_path, report_path = await audit_tree_file(
            tree_file_path=tree_file,
            llm=llm,
            debug=True
        )
        
        print("\n" + "="*70)
        print("✅ Audit Complete!")
        print("="*70)
        print(f"\n📄 Audited tree: {audited_path}")
        print(f"📊 Report: {report_path}")
        
        # 读取并显示报告摘要
        import json
        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        
        print(f"\n📈 Quality Score: {report['quality_score']:.1f}/100")
        print(f"\n📋 Summary:")
        print(f"  - Total nodes: {report['total_nodes']}")
        print(f"  - Issues found: {report['summary']['issues_found']}")
        print(f"  - Fixes applied: {report['summary']['fixes_applied']}")
        print(f"  - Nodes removed: {report['summary']['nodes_removed']}")
        print(f"  - Content deduplicated: {report['summary']['content_deduplicated']}")
        
        if report.get('issues_by_type'):
            print(f"\n🔍 Issues by Type:")
            for issue_type, count in report['issues_by_type'].items():
                print(f"  - {issue_type}: {count}")
        
        if report.get('recommendations'):
            print(f"\n💡 Recommendations:")
            for i, rec in enumerate(report['recommendations'], 1):
                print(f"  {i}. {rec}")
        
        print("\n" + "="*70)
        
    except Exception as e:
        print(f"\n❌ Audit failed: {e}")
        import traceback
        traceback.print_exc()


async def test_comparison():
    """对比审核前后的差异"""
    
    original_file = "data/parsed/0dd284d5-3bbc-4bc8-aa51-621201f23b33_tree.json"
    audited_file = "data/parsed/0dd284d5-3bbc-4bc8-aa51-621201f23b33_tree_audited.json"
    
    if not os.path.exists(audited_file):
        print("⚠ Run test_audit() first to generate audited tree")
        return
    
    import json
    
    # 读取两个文件
    with open(original_file, 'r', encoding='utf-8') as f:
        original = json.load(f)
    
    with open(audited_file, 'r', encoding='utf-8') as f:
        audited = json.load(f)
    
    # 统计节点数量
    def count_nodes(tree):
        count = 0
        def recurse(node):
            nonlocal count
            count += 1
            # 支持 "nodes" 和 "children" 两种字段名
            for child in node.get('nodes', node.get('children', [])):
                recurse(child)
        
        # 支持 "structure" 和 "children" 两种字段名
        structure = tree.get('structure', tree.get('children', []))
        for root in structure:
            recurse(root)
        return count
    
    original_count = count_nodes(original)
    audited_count = count_nodes(audited)
    
    print("\n" + "="*70)
    print("📊 Before vs After Comparison")
    print("="*70)
    print(f"\nOriginal nodes: {original_count}")
    print(f"Audited nodes:  {audited_count}")
    if original_count > 0:
        print(f"Removed:        {original_count - audited_count} ({(original_count - audited_count) / original_count * 100:.1f}%)")
    
    # 显示被移除的节点示例
    def extract_titles(tree):
        titles = set()
        def recurse(node):
            titles.add(node.get('title', ''))
            # 支持 "nodes" 和 "children" 两种字段名
            for child in node.get('nodes', node.get('children', [])):
                recurse(child)
        
        # 支持 "structure" 和 "children" 两种字段名
        structure = tree.get('structure', tree.get('children', []))
        for root in structure:
            recurse(root)
        return titles
    
    original_titles = extract_titles(original)
    audited_titles = extract_titles(audited)
    removed_titles = original_titles - audited_titles
    
    if removed_titles:
        print(f"\n🗑️  Removed Titles (first 5):")
        for i, title in enumerate(list(removed_titles)[:5], 1):
            print(f"  {i}. {title[:60]}{'...' if len(title) > 60 else ''}")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("🧪 Tree Auditor Test Suite")
    print("="*70)
    
    # Test 1: 审核
    asyncio.run(test_audit())
    
    # Test 2: 对比
    print("\n\n")
    asyncio.run(test_comparison())
    
    print("\n✨ All tests complete!\n")
