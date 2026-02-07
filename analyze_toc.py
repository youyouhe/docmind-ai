"""
分析文档的嵌入式TOC提取结果
"""
import sys
from pathlib import Path
import json

# Fix Unicode encoding on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, str(Path(__file__).parent))

import PyPDF2

def analyze_embedded_toc(pdf_path):
    """分析PDF的嵌入式目录"""
    print("=" * 70)
    print("分析嵌入式TOC")
    print("=" * 70)
    
    with open(pdf_path, 'rb') as f:
        pdf = PyPDF2.PdfReader(f)
        
        # 尝试提取嵌入式TOC
        try:
            outline = pdf.outline
            
            def flatten_outline(items, level=1, result=None):
                """递归展平大纲结构"""
                if result is None:
                    result = []
                
                for item in items:
                    if isinstance(item, list):
                        flatten_outline(item, level + 1, result)
                    else:
                        # PyPDF2的outline item是Destination对象
                        title = item.get('/Title', 'N/A') if hasattr(item, 'get') else str(item)
                        result.append({
                            'title': title,
                            'level': level
                        })
                
                return result
            
            if outline:
                flat_outline = flatten_outline(outline)
                print(f"\n✓ 找到嵌入式TOC，共 {len(flat_outline)} 项")
                print("\n嵌入式TOC内容:")
                print("-" * 70)
                
                for i, item in enumerate(flat_outline[:30]):  # 只显示前30项
                    level = item['level']
                    title = item['title']
                    
                    indent = "  " * (level - 1)
                    print(f"{i+1:2d}. {indent}[Level {level}] {title}")
                
                if len(flat_outline) > 30:
                    print(f"\n... 还有 {len(flat_outline) - 30} 项未显示")
                
                # 分析TOC的层级分布
                level_counts = {}
                for item in flat_outline:
                    level = item['level']
                    level_counts[level] = level_counts.get(level, 0) + 1
                
                print(f"\n层级分布:")
                for level in sorted(level_counts.keys()):
                    print(f"  Level {level}: {level_counts[level]} 项")
                
            else:
                print("\n✗ 没有找到嵌入式TOC")
                
        except Exception as e:
            print(f"\n✗ 读取嵌入式TOC时出错: {e}")
            import traceback
            traceback.print_exc()
        
        # 检查文档页数
        print(f"\n文档总页数: {len(pdf.pages)}")

if __name__ == "__main__":
    doc_id = "53b33b4f-9c5e-43db-b91d-354d5aaa00b1"
    pdf_path = Path(__file__).parent / "data" / "uploads" / f"{doc_id}.pdf"
    
    if not pdf_path.exists():
        print(f"错误: 找不到文件 {pdf_path}")
        sys.exit(1)
    
    analyze_embedded_toc(pdf_path)
