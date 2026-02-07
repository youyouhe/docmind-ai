"""
测试 Tree Auditor V2 - 智能文档结构审核系统

使用方法:
    cd lib/docmind-ai
    python test_tree_auditor_v2.py
"""

import asyncio
import os
import sys
import json

# Fix Windows encoding issues
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pageindex_v2.phases.tree_auditor_v2 import audit_tree_file_v2
from pageindex_v2.core.llm_client import LLMClient


async def test_auditor_v2():
    """测试V2审核系统"""
    
    # 配置文件路径
    tree_file = "data/parsed/0dd284d5-3bbc-4bc8-aa51-621201f23b33_tree.json"
    pdf_file = "data/raw/0dd284d5-3bbc-4bc8-aa51-621201f23b33.pdf"
    
    # 检查文件是否存在
    if not os.path.exists(tree_file):
        print(f"❌ Tree file not found: {tree_file}")
        return
    
    if not os.path.exists(pdf_file):
        print(f"⚠️  PDF file not found: {pdf_file}")
        print(f"  Will proceed without PDF verification")
        pdf_file = None
    
    print("="*70)
    print("🔍 Tree Auditor V2 Test - Progressive Mode")
    print("="*70)
    print(f"\nInput files:")
    print(f"  Tree: {tree_file}")
    print(f"  PDF:  {pdf_file if pdf_file else 'N/A'}")
    print()
    
    # 创建LLM客户端
    try:
        llm = LLMClient(
            provider="deepseek",
            model="deepseek-chat",
            debug=True
        )
        print("✅ LLM client initialized (DeepSeek)\n")
    except Exception as e:
        print(f"❌ Failed to initialize LLM: {e}")
        return
    
    # 执行审核（使用渐进式模式）
    try:
        output_path, report_path = await audit_tree_file_v2(
            tree_file_path=tree_file,
            pdf_path=pdf_file,
            llm=llm,
            mode="progressive",  # 使用渐进式5轮审核
            confidence_threshold=0.7,
            debug=True
        )
        
        # 读取报告
        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        
        # 显示摘要
        print("\n" + "="*70)
        print("📊 AUDIT SUMMARY (Progressive Mode)")
        print("="*70)
        
        summary = report.get("summary", {})
        phases = report.get("phases", {})
        
        print(f"\n📋 Document Type: {summary.get('document_type')} "
              f"(confidence: {summary.get('document_type_confidence', 0):.1%})")
        
        # 显示渐进式审核的轮次信息
        advice_gen = phases.get("advice_generation", {})
        if advice_gen.get("mode") == "progressive":
            print(f"\n🔄 Progressive Audit Rounds:")
            rounds = advice_gen.get("rounds", [])
            for round_info in rounds:
                round_num = round_info.get("round", 0)
                focus = round_info.get("focus", "")
                advice_count = len(round_info.get("advice", []))
                missing_count = len(round_info.get("missing_sequences", []))
                
                if focus == "CHECK_SEQUENCE":
                    print(f"  Round {round_num} ({focus}): Found {missing_count} missing sequences")
                else:
                    print(f"  Round {round_num} ({focus}): {advice_count} suggestions")
        
        print(f"\n📈 Node Statistics:")
        print(f"  Original nodes:  {summary.get('original_nodes', 0)}")
        print(f"  Optimized nodes: {summary.get('optimized_nodes', 0)}")
        print(f"  Removed:         {summary.get('nodes_removed', 0)} "
              f"({summary.get('removal_rate', 0):.1%})")
        
        print(f"\n🔧 Changes Applied:")
        changes = summary.get('changes_applied', {})
        print(f"  Deleted nodes:      {changes.get('deleted', 0)}")
        print(f"  Modified formats:   {changes.get('modified_format', 0)}")
        print(f"  Corrected pages:    {changes.get('modified_page', 0)}")
        
        print(f"\n⭐ Quality Score: {summary.get('quality_score', 0):.1f}/100")
        
        print(f"\n💡 Recommendations:")
        for i, rec in enumerate(summary.get('recommendations', []), 1):
            print(f"  {i}. {rec}")
        
        # 显示执行日志示例
        execution_log = report.get("phases", {}).get("execution", {}).get("log", [])
        if execution_log:
            print(f"\n📝 Execution Log (first 5):")
            for i, log in enumerate(execution_log[:5], 1):
                status_icon = "✅" if log["status"] == "executed" else "⏭️" if log["status"] == "skipped" else "❌"
                print(f"  {i}. {status_icon} {log['action']} node {log.get('node_id', 'N/A')}")
                print(f"     {log.get('reason', 'No reason provided')}")
                if log.get('details') and log['status'] == 'executed':
                    details = log['details']
                    if 'from' in details:
                        print(f"     From: {details['from'][:50]}...")
                        print(f"     To:   {details['to'][:50]}...")
        
        print("\n" + "="*70)
        print("✅ TEST COMPLETE")
        print("="*70)
        print(f"\n📄 Optimized tree: {output_path}")
        print(f"📊 Full report: {report_path}")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


async def compare_before_after():
    """对比优化前后的树结构"""
    print("\n\n" + "="*70)
    print("📊 BEFORE vs AFTER COMPARISON")
    print("="*70)
    
    original_file = "data/parsed/0dd284d5-3bbc-4bc8-aa51-621201f23b33_tree.json"
    optimized_file = "data/parsed/0dd284d5-3bbc-4bc8-aa51-621201f23b33_tree_progressive.json"
    
    if not os.path.exists(optimized_file):
        print("⚠️  Optimized tree not found. Run main test first.")
        return
    
    with open(original_file, 'r', encoding='utf-8') as f:
        original = json.load(f)
    
    with open(optimized_file, 'r', encoding='utf-8') as f:
        optimized = json.load(f)
    
    # 统计节点
    def count_and_collect_titles(tree):
        count = 0
        titles = []
        
        def traverse(node):
            nonlocal count
            count += 1
            titles.append(node.get('title', ''))
            for child in node.get('nodes', node.get('children', [])):
                traverse(child)
        
        structure = tree.get('structure', tree.get('children', []))
        for root in structure:
            traverse(root)
        
        return count, set(titles)
    
    orig_count, orig_titles = count_and_collect_titles(original)
    opt_count, opt_titles = count_and_collect_titles(optimized)
    
    removed_titles = orig_titles - opt_titles
    added_titles = opt_titles - orig_titles
    
    print(f"\n📊 Node Count:")
    print(f"  Original:  {orig_count}")
    print(f"  Optimized: {opt_count}")
    print(f"  Removed:   {orig_count - opt_count}")
    
    if removed_titles:
        print(f"\n🗑️  Removed Titles ({len(removed_titles)}):")
        for i, title in enumerate(list(removed_titles)[:10], 1):
            print(f"  {i}. {title[:70]}{'...' if len(title) > 70 else ''}")
        if len(removed_titles) > 10:
            print(f"  ... and {len(removed_titles) - 10} more")
    
    if added_titles:
        print(f"\n➕ Added Titles ({len(added_titles)}):")
        for i, title in enumerate(list(added_titles)[:5], 1):
            print(f"  {i}. {title[:70]}{'...' if len(title) > 70 else ''}")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    print("\n" + "="*70)
    print("🧪 Tree Auditor V2 Test Suite")
    print("="*70)
    
    # 运行主测试
    asyncio.run(test_auditor_v2())
    
    # 运行对比测试
    asyncio.run(compare_before_after())
    
    print("\n✨ All tests complete!\n")
