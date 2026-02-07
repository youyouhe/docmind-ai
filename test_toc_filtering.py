"""
Test TOC filtering improvements on the problematic PDF
"""
import sys
from pathlib import Path

# Fix Unicode encoding on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, str(Path(__file__).parent))

import fitz  # PyMuPDF

def is_valid_toc_title(title: str) -> bool:
    """
    Validate if a TOC title looks reasonable and not content fragments.
    (Copy of the validation logic from main.py for testing)
    """
    title = title.strip()
    
    # 1. Length check
    if len(title) <= 1:
        return False
    
    if len(title) > 80:
        return False
    
    # 2. Sentence pattern check
    content_indicators = ['。', '，', '！', '？']
    if any(p in title for p in content_indicators):
        legitimate_prefixes = ['第', '（', '(', '附件', '表', '图']
        if not any(title.startswith(prefix) for prefix in legitimate_prefixes):
            return False
    
    # 3. Check for known garbage patterns
    single_char_words = ['报', '价', '文', '件', '供', '应', '商', '称', '章']
    if title in single_char_words:
        return False
    
    # 4. Check if title is just punctuation or special characters
    if all(not c.isalnum() for c in title):
        return False
    
    # 5. Filter out form-like entries
    if title.endswith('：') or title.endswith(':'):
        form_keywords = ['地址', '时间', '日期', '名称', '公章', '签字', '盖章', '电话', '传真', '邮编']
        has_form_keyword = any(kw in title for kw in form_keywords)
        has_multiple_spaces = '  ' in title
        
        if has_form_keyword or has_multiple_spaces:
            return False
    
    # 6. Filter entries that start with single letters
    if len(title) > 2 and title[0].isalpha() and title[1] == '.':
        if not any(title[2:].strip().startswith(prefix) for prefix in ['附', '补', '表', '图']):
            return False
    
    return True

def test_toc_filtering():
    """Test the new TOC filtering logic"""
    doc_id = "53b33b4f-9c5e-43db-b91d-354d5aaa00b1"
    pdf_path = Path(__file__).parent / "data" / "uploads" / f"{doc_id}.pdf"
    
    if not pdf_path.exists():
        print(f"错误: 找不到文件 {pdf_path}")
        sys.exit(1)
    
    print("=" * 70)
    print("测试 TOC 过滤功能")
    print("=" * 70)
    
    # Extract embedded TOC using PyMuPDF (same as main.py)
    doc = fitz.open(str(pdf_path))
    embedded_toc = doc.get_toc()
    doc.close()
    
    print(f"\n原始嵌入式 TOC: {len(embedded_toc)} 项")
    
    # Filter the TOC
    valid_entries = []
    invalid_entries = []
    
    for level, title, page in embedded_toc:
        title = title.strip()
        if is_valid_toc_title(title):
            valid_entries.append((level, title, page))
        else:
            invalid_entries.append((level, title, page))
    
    print(f"\n过滤结果:")
    print(f"  ✓ 有效项: {len(valid_entries)}")
    print(f"  ✗ 无效项: {len(invalid_entries)}")
    print(f"  质量比率: {len(valid_entries)/len(embedded_toc)*100:.1f}%")
    
    print(f"\n有效的 TOC 项:")
    print("-" * 70)
    for i, (level, title, page) in enumerate(valid_entries):
        indent = "  " * (level - 1)
        print(f"{i+1:2d}. {indent}[Level {level}] {title} → 第{page}页")
    
    print(f"\n被过滤的无效项:")
    print("-" * 70)
    for i, (level, title, page) in enumerate(invalid_entries):
        # Truncate long titles
        display_title = title[:60] + "..." if len(title) > 60 else title
        print(f"{i+1:2d}. [Level {level}] {display_title}")
    
    # Quality assessment
    quality_ratio = len(valid_entries) / len(embedded_toc) if len(embedded_toc) > 0 else 0
    
    print(f"\n质量评估:")
    print(f"  原始项数: {len(embedded_toc)}")
    print(f"  有效项数: {len(valid_entries)}")
    print(f"  过滤项数: {len(embedded_toc) - len(valid_entries)}")
    print(f"  质量比率: {quality_ratio:.1%}")
    
    if quality_ratio < 0.5 and len(valid_entries) < 5:
        print(f"\n⚠ 警告: TOC 质量过低，系统会回退到文本检测!")
    else:
        print(f"\n✓ TOC 质量可接受，可以使用嵌入式TOC")

if __name__ == "__main__":
    test_toc_filtering()
