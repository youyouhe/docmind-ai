"""
Test suite for Phase 1.5: Multi-Stage TOC Detection

Tests the enhanced TOC detection system with likelihood scoring
and multi-stage validation.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pageindex.page_index import calculate_toc_likelihood_score


def test_high_confidence_toc():
    """Test TOC page with clear indicators - should get high score"""
    content = """
Table of Contents

Chapter 1: Introduction ........................... 1
Chapter 2: Literature Review ..................... 15
    2.1 Background .............................. 16
    2.2 Related Work ............................ 20
Chapter 3: Methodology ........................... 35
    3.1 Data Collection ......................... 36
    3.2 Analysis Methods ........................ 42
Chapter 4: Results ............................... 58
Chapter 5: Conclusion ............................ 75
References ....................................... 82
"""
    
    score = calculate_toc_likelihood_score(content)
    
    assert score >= 70, f"High-confidence TOC should score >= 70, got {score}"
    print(f"[PASS] High confidence TOC scored {score} (expected >= 70)")


def test_medium_confidence_toc():
    """Test TOC-like page with some indicators - should get medium score"""
    content = """
Contents

1. Introduction - 5
2. Background - 12
3. Methods - 25
4. Results - 40
5. Discussion - 55
"""
    
    score = calculate_toc_likelihood_score(content)
    
    assert 50 <= score < 70, f"Medium-confidence TOC should score 50-70, got {score}"
    print(f"[PASS] Medium confidence TOC scored {score} (expected 50-70)")


def test_low_confidence_toc():
    """Test page that's not a TOC - should get low score"""
    content = """
This is a regular page with some text content.
It contains paragraphs and sentences but no
table of contents structure or page numbers.

The document discusses various topics and includes
references to chapters but not in a structured way.
"""
    
    score = calculate_toc_likelihood_score(content)
    
    assert score < 50, f"Non-TOC page should score < 50, got {score}"
    print(f"[PASS] Non-TOC page scored {score} (expected < 50)")


def test_false_positive_list_of_figures():
    """Test that list of figures gets penalized"""
    content = """
List of Figures

Figure 1.1: System Architecture .................. 10
Figure 1.2: Data Flow Diagram .................... 12
Figure 2.1: Experimental Setup ................... 25
Figure 2.2: Results Graph ........................ 30
"""
    
    score = calculate_toc_likelihood_score(content)
    
    # Should have page citations (+points) but "list of figures" penalty (-30)
    assert score < 70, f"List of figures should score < 70 due to penalty, got {score}"
    print(f"[PASS] List of figures scored {score} (expected < 70 with penalty)")


def test_false_positive_abstract():
    """Test that abstract gets penalized"""
    content = """
Abstract

This paper presents a novel approach to machine learning
with applications in natural language processing.
We demonstrate significant improvements over baseline methods.
"""
    
    score = calculate_toc_likelihood_score(content)
    
    assert score < 50, f"Abstract should score < 50, got {score}"
    print(f"[PASS] Abstract scored {score} (expected < 50)")


def test_hierarchical_structure_bonus():
    """Test that hierarchical numbering increases score"""
    content = """
Contents

1. Introduction ............................... 1
    1.1 Background ........................... 2
    1.2 Motivation ........................... 5
2. Methods .................................... 10
    2.1 Data ................................. 11
    2.2 Analysis ............................. 15
3. Results .................................... 20
    3.1 Findings ............................. 21
    3.2 Discussion ........................... 28
"""
    
    score = calculate_toc_likelihood_score(content)
    
    # Should get hierarchical structure bonus
    assert score >= 70, f"Hierarchical TOC should score >= 70, got {score}"
    print(f"[PASS] Hierarchical TOC scored {score} (expected >= 70)")


def test_chinese_toc():
    """Test Chinese TOC detection"""
    content = """
目录

第一章 介绍 ............................ 第1页
第二章 文献综述 ........................ 第10页
    2.1 背景 ............................ 第11页
    2.2 相关工作 ........................ 第15页
第三章 方法 ............................ 第25页
第四章 结果 ............................ 第40页
"""
    
    score = calculate_toc_likelihood_score(content)
    
    assert score >= 60, f"Chinese TOC should score >= 60, got {score}"
    print(f"[PASS] Chinese TOC scored {score} (expected >= 60)")


def test_dotted_line_page_references():
    """Test TOC with dotted line style page references"""
    content = """
Table of Contents

Introduction................................1
Literature Review..........................15
    Background.............................16
    Related Work...........................22
Methodology................................35
Results....................................50
Conclusion.................................70
"""
    
    score = calculate_toc_likelihood_score(content)
    
    # This TOC has good page citations but lacks headings and is short
    # Expect medium confidence (45), which should trigger LLM confirmation
    assert score >= 40, f"Dotted-line TOC should score >= 40, got {score}"
    print(f"[PASS] Dotted-line TOC scored {score} (expected >= 40)")


def test_length_appropriateness():
    """Test that very short or very long content gets penalized"""
    
    # Very short content
    short_content = "Contents\nChapter 1"
    short_score = calculate_toc_likelihood_score(short_content)
    
    # Normal length content with good structure
    normal_content = """
Table of Contents

Chapter 1: Introduction ........................... 1
Chapter 2: Background ............................. 15
Chapter 3: Methods ................................ 30
Chapter 4: Results ................................ 50
Chapter 5: Conclusion ............................. 70
"""
    normal_score = calculate_toc_likelihood_score(normal_content)
    
    assert normal_score > short_score, f"Normal-length TOC should score higher than very short content"
    print(f"[PASS] Length appropriateness: short={short_score}, normal={normal_score}")


def test_page_citation_thresholds():
    """Test different levels of page citations"""
    
    # Many page citations (>10)
    many_citations = """
Contents
Chapter 1 - p.1
Chapter 2 - p.5
Chapter 3 - p.10
Chapter 4 - p.15
Chapter 5 - p.20
Chapter 6 - p.25
Chapter 7 - p.30
Chapter 8 - p.35
Chapter 9 - p.40
Chapter 10 - p.45
Chapter 11 - p.50
"""
    
    # Few page citations (2-4)
    few_citations = """
Contents
Chapter 1 - p.1
Chapter 2 - p.10
Chapter 3 - p.20
"""
    
    # No page citations
    no_citations = """
Contents
Chapter 1: Introduction
Chapter 2: Background
Chapter 3: Methods
"""
    
    many_score = calculate_toc_likelihood_score(many_citations)
    few_score = calculate_toc_likelihood_score(few_citations)
    no_score = calculate_toc_likelihood_score(no_citations)
    
    assert many_score > few_score > no_score, \
        f"More page citations should increase score: many={many_score}, few={few_score}, no={no_score}"
    print(f"[PASS] Page citation thresholds: many={many_score}, few={few_score}, no={no_score}")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("Testing Multi-Stage TOC Detection (Phase 1.5)")
    print("="*60 + "\n")
    
    try:
        test_high_confidence_toc()
        test_medium_confidence_toc()
        test_low_confidence_toc()
        test_false_positive_list_of_figures()
        test_false_positive_abstract()
        test_hierarchical_structure_bonus()
        test_chinese_toc()
        test_dotted_line_page_references()
        test_length_appropriateness()
        test_page_citation_thresholds()
        
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
    run_all_tests()
