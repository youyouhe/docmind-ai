"""
Test suite for Phase 1.6: Fuzzy Title Matching

Tests the enhanced title matching system with typo tolerance
and formatting variation handling.
"""

import sys
import os
import asyncio
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pageindex.page_index import check_title_appearance_v2


async def test_exact_match():
    """Test exact title match"""
    item = {
        'title': 'Introduction to Machine Learning',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("Introduction to Machine Learning\n\nThis chapter covers...", {}),
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'yes', f"Should find exact match"
    assert result['confidence'] == 100, f"Exact match should have 100% confidence, got {result['confidence']}"
    print(f"[PASS] Exact match: confidence={result['confidence']}")


async def test_case_insensitive_match():
    """Test case-insensitive matching"""
    item = {
        'title': 'Data Collection Methods',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("DATA COLLECTION METHODS\n\nWe collected data from various sources...", {}),
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'yes', f"Should find case-insensitive match"
    assert result['confidence'] == 100, f"Case-insensitive should be treated as exact"
    print(f"[PASS] Case-insensitive match: confidence={result['confidence']}")


async def test_punctuation_variation():
    """Test handling of punctuation variations"""
    item = {
        'title': 'Background and Motivation',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("Background & Motivation!\n\nOur work is motivated by...", {}),
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'yes', f"Should handle punctuation variations"
    assert result['confidence'] >= 85, f"Normalized match should have high confidence, got {result['confidence']}"
    print(f"[PASS] Punctuation variation: confidence={result['confidence']}")


async def test_typo_tolerance():
    """Test tolerance for minor typos"""
    item = {
        'title': 'Experimental Methodology',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("Expermental Methodolgy\n\nWe designed our experiments...", {}),  # 2 typos
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'yes', f"Should tolerate minor typos"
    assert result['confidence'] >= 85, f"Fuzzy match should succeed with minor typos, got {result['confidence']}"
    print(f"[PASS] Typo tolerance: confidence={result['confidence']}")


async def test_spacing_variation():
    """Test handling of extra/missing spaces"""
    item = {
        'title': 'Results and Discussion',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("Results   and   Discussion\n\nIn this section...", {}),  # Extra spaces
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'yes', f"Should handle spacing variations"
    assert result['confidence'] >= 90, f"Normalized match should handle spaces, got {result['confidence']}"
    print(f"[PASS] Spacing variation: confidence={result['confidence']}")


async def test_word_level_match():
    """Test word-level matching for partial matches"""
    item = {
        'title': 'Deep Learning Applications in Healthcare',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("Applications of Deep Learning in Healthcare Systems\n\nThis chapter explores...", {}),
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'yes', f"Should match with word-level matching"
    # All words present: Deep, Learning, Applications, Healthcare
    print(f"[PASS] Word-level match: confidence={result['confidence']}")


async def test_no_match():
    """Test that unrelated titles don't match"""
    item = {
        'title': 'Quantum Computing Fundamentals',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("Classical Computing Methods\n\nTraditional computers use binary logic...", {}),
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'no', f"Should not match unrelated content"
    assert result['confidence'] == 0, f"No match should have 0% confidence"
    print(f"[PASS] No match correctly detected: confidence={result['confidence']}")


async def test_abbreviation_expansion():
    """Test matching with abbreviation expansion"""
    item = {
        'title': 'Natural Language Processing',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("NLP Techniques\n\nNatural language processing has evolved...", {}),
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    # This should match via word-level matching (Natural, Language, Processing all appear)
    assert result['answer'] == 'yes', f"Should match with abbreviation expansion"
    print(f"[PASS] Abbreviation handling: confidence={result['confidence']}")


async def test_chinese_title_match():
    """Test matching Chinese titles"""
    item = {
        'title': '实验方法与数据分析',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("实验方法与数据分析\n\n本章介绍实验设计...", {}),
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    assert result['answer'] == 'yes', f"Should match Chinese titles"
    assert result['confidence'] == 100, f"Exact Chinese match should have 100% confidence"
    print(f"[PASS] Chinese title match: confidence={result['confidence']}")


async def test_long_title_fuzzy_match():
    """Test fuzzy matching with longer titles"""
    item = {
        'title': 'A Comprehensive Study of Neural Network Architectures for Computer Vision',
        'physical_index': 1,
        'list_index': 0
    }
    
    page_list = [
        ("A Comprehnsive Study of Neural Netwrk Architectures for Computer Visoin\n\n", {}),  # Multiple typos
    ]
    
    result = await check_title_appearance_v2(item, page_list, start_index=1)
    
    # Should still match with high similarity despite multiple typos
    assert result['answer'] == 'yes', f"Should handle multiple typos in long titles"
    print(f"[PASS] Long title with typos: confidence={result['confidence']}")


async def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("Testing Fuzzy Title Matching (Phase 1.6)")
    print("="*60 + "\n")
    
    try:
        await test_exact_match()
        await test_case_insensitive_match()
        await test_punctuation_variation()
        await test_typo_tolerance()
        await test_spacing_variation()
        await test_word_level_match()
        await test_no_match()
        await test_abbreviation_expansion()
        await test_chinese_title_match()
        await test_long_title_fuzzy_match()
        
        print("\n" + "="*60)
        print("[SUCCESS] All tests passed!")
        print("="*60 + "\n")
        
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
