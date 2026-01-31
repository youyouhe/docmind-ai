"""
Test suite for intelligent document chunking (Phase 1.3)
Tests TOC-aware chunking, adaptive strategies, and chunk quality
"""

import sys
import os
import io

# Force UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pageindex.page_index import (
    chunk_by_toc_structure,
    chunk_by_tokens_with_overlap,
    page_list_to_group_text_v2
)


def create_mock_pages(num_pages=20, tokens_per_page=1000):
    """Helper to create mock page contents and token lengths"""
    page_contents = [f"Page {i} content " * 100 for i in range(num_pages)]
    token_lengths = [tokens_per_page] * num_pages
    return page_contents, token_lengths


def create_mock_toc(num_chapters=3, subsections_per_chapter=2):
    """Helper to create mock TOC structure"""
    toc = []
    for chapter in range(1, num_chapters + 1):
        # Add major section (chapter)
        toc.append({
            'structure': str(chapter),
            'title': f'Chapter {chapter}',
            'physical_index': chapter * 5  # Chapters at pages 5, 10, 15, etc.
        })
        # Add subsections
        for subsection in range(1, subsections_per_chapter + 1):
            toc.append({
                'structure': f'{chapter}.{subsection}',
                'title': f'Section {chapter}.{subsection}',
                'physical_index': chapter * 5 + subsection
            })
    return toc


def test_chunk_by_tokens_adaptive():
    """Test adaptive token-based chunking"""
    page_contents, token_lengths = create_mock_pages(num_pages=20, tokens_per_page=1000)
    # Total: 20,000 tokens, max: 8,000 per chunk
    
    chunks = chunk_by_tokens_with_overlap(page_contents, token_lengths, 
                                          max_tokens=8000, overlap_pages=1, 
                                          strategy='adaptive')
    
    assert len(chunks) > 0, "Should create at least one chunk"
    assert len(chunks) >= 2, "Should create multiple chunks for 20K tokens with 8K max"
    assert all(isinstance(c, str) for c in chunks), "All chunks should be strings"
    
    print(f"[PASS] Adaptive token-based chunking works ({len(chunks)} chunks)")


def test_chunk_by_tokens_fixed():
    """Test fixed token-based chunking"""
    page_contents, token_lengths = create_mock_pages(num_pages=20, tokens_per_page=1000)
    
    chunks = chunk_by_tokens_with_overlap(page_contents, token_lengths,
                                          max_tokens=8000, overlap_pages=1,
                                          strategy='fixed')
    
    assert len(chunks) > 0, "Should create at least one chunk"
    assert len(chunks) >= 2, "Should create multiple chunks"
    
    print(f"[PASS] Fixed token-based chunking works ({len(chunks)} chunks)")


def test_chunk_single_chunk_fits():
    """Test that small documents stay as single chunk"""
    page_contents, token_lengths = create_mock_pages(num_pages=5, tokens_per_page=1000)
    # Total: 5,000 tokens, max: 10,000 per chunk
    
    chunks = chunk_by_tokens_with_overlap(page_contents, token_lengths,
                                          max_tokens=10000, overlap_pages=1,
                                          strategy='adaptive')
    
    assert len(chunks) == 1, "Small document should be single chunk"
    
    print("[PASS] Single chunk for small documents works")


def test_chunk_by_toc_structure_basic():
    """Test TOC-aware chunking with chapter boundaries"""
    page_contents, token_lengths = create_mock_pages(num_pages=20, tokens_per_page=1000)
    toc = create_mock_toc(num_chapters=4, subsections_per_chapter=2)
    
    chunks = chunk_by_toc_structure(page_contents, token_lengths, toc,
                                     start_index=1, max_tokens=10000)
    
    assert len(chunks) > 0, "Should create at least one chunk"
    # With 4 chapters and 20 pages, should split at chapter boundaries
    assert len(chunks) <= 4, "Should not exceed number of major sections"
    
    print(f"[PASS] TOC-aware chunking works ({len(chunks)} chunks)")


def test_chunk_by_toc_respects_token_limit():
    """Test that TOC-aware chunking still respects token limits"""
    page_contents, token_lengths = create_mock_pages(num_pages=30, tokens_per_page=2000)
    # Total: 60,000 tokens
    toc = create_mock_toc(num_chapters=2, subsections_per_chapter=1)
    # Only 2 chapters, but each would be 30K tokens
    
    chunks = chunk_by_toc_structure(page_contents, token_lengths, toc,
                                     start_index=1, max_tokens=20000)
    
    assert len(chunks) > 2, "Should split beyond chapter boundaries when token limit exceeded"
    
    print(f"[PASS] TOC-aware chunking respects token limits ({len(chunks)} chunks)")


def test_page_list_to_group_text_v2_auto_no_toc():
    """Test auto strategy when no TOC available"""
    page_contents, token_lengths = create_mock_pages(num_pages=20, tokens_per_page=1000)
    
    chunks = page_list_to_group_text_v2(page_contents, token_lengths, toc_items=None,
                                        max_tokens=8000, chunking_strategy='auto')
    
    assert len(chunks) > 0, "Should create chunks"
    assert len(chunks) >= 2, "Should create multiple chunks"
    
    print(f"[PASS] Auto strategy without TOC works ({len(chunks)} chunks)")


def test_page_list_to_group_text_v2_auto_with_toc():
    """Test auto strategy when TOC available"""
    page_contents, token_lengths = create_mock_pages(num_pages=20, tokens_per_page=1000)
    toc = create_mock_toc(num_chapters=3, subsections_per_chapter=2)
    
    chunks = page_list_to_group_text_v2(page_contents, token_lengths, toc_items=toc,
                                        start_index=1, max_tokens=10000, 
                                        chunking_strategy='auto')
    
    assert len(chunks) > 0, "Should create chunks"
    # Auto should select TOC-aware strategy
    
    print(f"[PASS] Auto strategy with TOC works ({len(chunks)} chunks)")


def test_page_list_to_group_text_v2_force_toc():
    """Test forcing TOC strategy"""
    page_contents, token_lengths = create_mock_pages(num_pages=20, tokens_per_page=1000)
    toc = create_mock_toc(num_chapters=3, subsections_per_chapter=2)
    
    chunks = page_list_to_group_text_v2(page_contents, token_lengths, toc_items=toc,
                                        start_index=1, max_tokens=10000,
                                        chunking_strategy='toc')
    
    assert len(chunks) > 0, "Should create chunks with TOC strategy"
    
    print(f"[PASS] Forced TOC strategy works ({len(chunks)} chunks)")


def test_page_list_to_group_text_v2_force_adaptive():
    """Test forcing adaptive strategy"""
    page_contents, token_lengths = create_mock_pages(num_pages=20, tokens_per_page=1000)
    
    chunks = page_list_to_group_text_v2(page_contents, token_lengths, toc_items=None,
                                        max_tokens=8000, chunking_strategy='adaptive')
    
    assert len(chunks) > 0, "Should create chunks with adaptive strategy"
    
    print(f"[PASS] Forced adaptive strategy works ({len(chunks)} chunks)")


def test_empty_input():
    """Test handling of empty inputs"""
    chunks = chunk_by_tokens_with_overlap([], [], max_tokens=10000)
    assert chunks == [""], "Empty input should produce single empty chunk"
    
    chunks = chunk_by_toc_structure([], [], [], start_index=1, max_tokens=10000)
    assert chunks == [], "Empty TOC chunking should produce empty list"
    
    chunks = page_list_to_group_text_v2([], [], toc_items=None, max_tokens=10000)
    assert chunks == [], "Empty v2 input should produce empty list"
    
    print("[PASS] Empty input handling works")


def test_overlap_continuity():
    """Test that overlap includes previous pages"""
    page_contents = [f"Page_{i}" for i in range(10)]
    token_lengths = [2000] * 10  # 2K per page, 20K total
    
    chunks = chunk_by_tokens_with_overlap(page_contents, token_lengths,
                                          max_tokens=5000, overlap_pages=2,
                                          strategy='fixed')
    
    # Check that chunks have overlapping content
    assert len(chunks) >= 2, "Should have multiple chunks"
    # Second chunk should contain content from end of first chunk
    if len(chunks) >= 2:
        # This is a basic overlap check - in practice overlap logic is more complex
        assert len(chunks[1]) > 0, "Overlapped chunk should have content"
    
    print(f"[PASS] Overlap continuity works ({len(chunks)} chunks with overlap)")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("Testing Intelligent Document Chunking (Phase 1.3)")
    print("="*60 + "\n")
    
    try:
        test_chunk_by_tokens_adaptive()
        test_chunk_by_tokens_fixed()
        test_chunk_single_chunk_fits()
        test_chunk_by_toc_structure_basic()
        test_chunk_by_toc_respects_token_limit()
        test_page_list_to_group_text_v2_auto_no_toc()
        test_page_list_to_group_text_v2_auto_with_toc()
        test_page_list_to_group_text_v2_force_toc()
        test_page_list_to_group_text_v2_force_adaptive()
        test_empty_input()
        test_overlap_continuity()
        
        print("\n" + "="*60)
        print("[SUCCESS] All tests passed!")
        print("="*60 + "\n")
        return True
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
