"""
Test script for Gap Filler functionality
"""

import json
import sys
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def analyze_structure(json_file):
    """Analyze structure JSON and report gap fill status"""
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("=" * 70)
    print("GAP FILLER ANALYSIS REPORT")
    print("=" * 70)
    
    # Basic info
    print(f"\n📄 Source File: {data.get('source_file', 'N/A')}")
    print(f"📊 Total Pages: {data.get('total_pages', 'N/A')}")
    
    # Gap fill info
    if 'gap_fill_info' in data:
        gap_info = data['gap_fill_info']
        print(f"\n🔧 Gap Fill Information:")
        print(f"   Gaps Found: {gap_info['gaps_found']}")
        print(f"   Original Coverage: {gap_info['original_coverage']} ({gap_info['coverage_percentage']:.1f}%)")
        
        if gap_info['gaps_found'] > 0:
            print(f"\n   Gap Ranges:")
            for gap_start, gap_end in gap_info['gaps_filled']:
                gap_size = gap_end - gap_start + 1
                print(f"      • Pages {gap_start}-{gap_end} ({gap_size} pages)")
        else:
            print(f"   ✅ No gaps - structure is complete!")
    else:
        print(f"\n⚠️  No gap_fill_info found (old version?)")
    
    # Structure analysis
    structure = data.get('structure', [])
    print(f"\n📋 Structure:")
    print(f"   Total Nodes: {len(structure)}")
    
    gap_nodes = [n for n in structure if n.get('is_gap_fill')]
    regular_nodes = [n for n in structure if not n.get('is_gap_fill')]
    
    print(f"   Regular Nodes: {len(regular_nodes)}")
    print(f"   Gap Fill Nodes: {len(gap_nodes)}")
    
    if gap_nodes:
        print(f"\n🔧 Gap Fill Nodes (showing first 5):")
        for i, node in enumerate(gap_nodes[:5]):
            title = node.get('title', 'Untitled')
            start = node.get('start_index', '?')
            end = node.get('end_index', '?')
            children_count = len(node.get('nodes', []))
            
            print(f"   {i+1}. [{start}-{end}] {title}")
            if children_count > 0:
                print(f"      └─ {children_count} child nodes")
    
    # Page coverage
    covered_pages = set()
    
    def collect_pages(nodes):
        for node in nodes:
            if 'start_index' in node:
                covered_pages.add(node['start_index'])
            if 'end_index' in node:
                covered_pages.add(node['end_index'])
            if 'start_index' in node and 'end_index' in node:
                for p in range(node['start_index'], node['end_index'] + 1):
                    covered_pages.add(p)
            if 'nodes' in node:
                collect_pages(node['nodes'])
    
    collect_pages(structure)
    
    total_pages = data.get('total_pages', 0)
    print(f"\n✅ Final Coverage:")
    print(f"   Pages Covered: {len(covered_pages)}/{total_pages} ({len(covered_pages)/total_pages*100:.1f}%)")
    
    missing_pages = set(range(1, total_pages + 1)) - covered_pages
    if missing_pages:
        print(f"   ⚠️  Still Missing: {sorted(missing_pages)}")
    else:
        print(f"   ✓ All pages covered!")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_gap_filler.py <structure_json_file>")
        sys.exit(1)
    
    analyze_structure(sys.argv[1])
