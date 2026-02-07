"""
测试章节检测和层级规范化优化
"""
import fitz
import re
from pathlib import Path
import sys
import io

# Force UTF-8 output for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def is_valid_toc_title(title: str) -> bool:
    """验证 TOC 标题是否有效（简化版）"""
    title = title.strip()
    
    # 长度检查
    if len(title) <= 1 or len(title) > 80:
        return False
    
    # 内容标点检查
    content_indicators = ['。', '，', '！', '？']
    if any(p in title for p in content_indicators):
        legitimate_prefixes = ['第', '（', '(', '附件', '表', '图']
        if not any(title.startswith(prefix) for prefix in legitimate_prefixes):
            return False
    
    # 单字检查
    single_char_words = ['报', '价', '文', '件', '供', '应', '商', '称', '章']
    if title in single_char_words:
        return False
    
    # 纯符号检查
    if all(not c.isalnum() for c in title):
        return False
    
    # 表单字段检查
    if title.endswith('：') or title.endswith(':'):
        form_keywords = ['地址', '时间', '日期', '名称', '公章', '签字', '盖章', '电话', '传真', '邮编']
        has_form_keyword = any(kw in title for kw in form_keywords)
        has_multiple_spaces = '  ' in title
        
        if has_form_keyword or has_multiple_spaces:
            return False
    
    # 列表标记检查
    if len(title) > 2 and title[0].isalpha() and title[1] == '.':
        if not any(title[2:].strip().startswith(prefix) for prefix in ['附', '补', '表', '图']):
            return False
    
    return True

def is_chapter_title(title: str) -> bool:
    """检测是否为章节标题"""
    # 第X章 模式
    if re.match(r'^第[一二三四五六七八九十0-9]+章', title):
        return True
    
    # Chapter X 模式
    if re.match(r'^(?:chapter|CHAPTER)\s*[0-9IVX]+', title, re.IGNORECASE):
        return True
    
    return False

def convert_toc_with_optimization(embedded_toc):
    """使用优化后的逻辑转换 TOC"""
    structure = []
    level_counters = {}
    filtered_count = 0
    chapter_counter = 0
    normalized_count = 0
    
    print("\n处理 TOC 条目:")
    print("-" * 80)
    
    for i, (level, title, page) in enumerate(embedded_toc, 1):
        title = title.strip()
        
        # 过滤无效标题
        if not is_valid_toc_title(title):
            preview = title[:50] + "..." if len(title) > 50 else title
            print(f"  [SKIP {i:2d}] L{level} '{preview}' (无效标题)")
            filtered_count += 1
            continue
        
        # 章节检测
        is_chapter = is_chapter_title(title)
        original_level = level
        
        if is_chapter:
            level = 1  # 强制章节为 level 1
            chapter_counter += 1
            if original_level != 1:
                normalized_count += 1
                print(f"  [NORM {i:2d}] L{original_level}→L{level} '{title}' (页 {page}) ✓ 章节检测")
            else:
                print(f"  [KEEP {i:2d}] L{level} '{title}' (页 {page}) ✓ 章节")
        else:
            print(f"  [KEEP {i:2d}] L{level} '{title}' (页 {page})")
        
        # 更新计数器
        if level not in level_counters:
            level_counters[level] = 0
        level_counters[level] += 1
        
        # 重置更深层级
        keys_to_delete = [k for k in level_counters if k > level]
        for k in keys_to_delete:
            del level_counters[k]
        
        # 构建结构代码
        structure_code_parts = []
        for lv in sorted([k for k in level_counters if k <= level]):
            structure_code_parts.append(str(level_counters[lv]))
        structure_code = ".".join(structure_code_parts)
        
        structure.append({
            "structure": structure_code,
            "title": title,
            "page": page,
            "level": level,
            "is_chapter": is_chapter
        })
    
    return structure, filtered_count, chapter_counter, normalized_count

def main():
    pdf_path = Path("data/uploads/40f6c928-f465-4033-8465-8bad6f912750.pdf")
    
    if not pdf_path.exists():
        print(f"❌ PDF 文件不存在: {pdf_path}")
        return
    
    print("=" * 80)
    print("测试章节检测和层级规范化优化")
    print("=" * 80)
    
    # 提取 TOC
    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    doc.close()
    
    print(f"\n原始 TOC 条目: {len(toc)}")
    
    # 应用优化
    structure, filtered, chapters, normalized = convert_toc_with_optimization(toc)
    
    print("\n" + "=" * 80)
    print("处理结果统计")
    print("=" * 80)
    print(f"原始 TOC 条目:     {len(toc)}")
    print(f"过滤掉的无效条目: {filtered}")
    print(f"保留的有效条目:   {len(structure)}")
    print(f"检测到的章节:     {chapters}")
    print(f"层级规范化的条目: {normalized}")
    
    print("\n" + "=" * 80)
    print("最终结构（前 15 项）")
    print("=" * 80)
    
    for i, item in enumerate(structure[:15], 1):
        chapter_mark = "📘" if item.get('is_chapter') else "  "
        print(f"{i:2d}. {chapter_mark} [{item['structure']:6s}] L{item['level']} {item['title'][:50]:50s} (页 {item['page']})")
    
    if len(structure) > 15:
        print(f"     ... 还有 {len(structure) - 15} 项")
    
    # 检查章节是否全部在 level 1
    print("\n" + "=" * 80)
    print("章节层级验证")
    print("=" * 80)
    
    chapters_in_structure = [s for s in structure if s.get('is_chapter')]
    all_level_1 = all(ch['level'] == 1 for ch in chapters_in_structure)
    
    print(f"检测到的章节:")
    for ch in chapters_in_structure:
        print(f"  [{ch['structure']}] L{ch['level']} {ch['title']}")
    
    if all_level_1:
        print("\n✅ 所有章节都在 level 1 (正确)")
    else:
        print("\n❌ 某些章节不在 level 1 (需要进一步修复)")
    
    print("\n" + "=" * 80)
    print("优化效果评估")
    print("=" * 80)
    
    expected_chapters = ['第一章', '第二章', '第三章', '第四章', '第五章', '第六章']
    found_chapters = [ch['title'] for ch in chapters_in_structure]
    
    print("预期的章节:")
    for exp in expected_chapters:
        found = any(exp in title for title in found_chapters)
        status = "✓" if found else "✗"
        matching = [t for t in found_chapters if exp in t]
        if matching:
            print(f"  {status} {exp:8s} → 找到: {matching[0]}")
        else:
            print(f"  {status} {exp:8s} → 未找到")
    
    missing = sum(1 for exp in expected_chapters if not any(exp in title for title in found_chapters))
    
    if missing == 0:
        print("\n🎉 完美! 所有预期章节都被正确识别!")
        quality_score = 100
    else:
        print(f"\n⚠️  仍缺失 {missing} 个章节")
        quality_score = ((len(expected_chapters) - missing) / len(expected_chapters)) * 100
    
    print(f"\n质量评分: {quality_score:.0f}% (章节识别率)")
    
    if normalized > 0:
        print(f"✓ 规范化了 {normalized} 个错误的层级分配")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
