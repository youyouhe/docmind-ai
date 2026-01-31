"""
Test suite for physical index validation pipeline (Phase 1.2)
Tests interpolation, duplicate resolution, and monotonic validation
"""

import sys
import os
import io

# Force UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pageindex.page_index import (
    interpolate_missing_indices,
    resolve_duplicate_indices,
    validate_monotonic_increasing,
    validate_and_correct_physical_indices
)


def test_interpolate_missing_indices_both_bounds():
    """Test interpolation when both prev and next indices exist"""
    toc = [
        {'title': 'Chapter 1', 'physical_index': 10},
        {'title': 'Section 1.1', 'physical_index': None},
        {'title': 'Section 1.2', 'physical_index': None},
        {'title': 'Chapter 2', 'physical_index': 20},
    ]
    
    result = interpolate_missing_indices(toc, page_list_length=100, start_index=1)
    
    # Should interpolate values between 10 and 20
    assert result[1]['physical_index'] is not None, "Should interpolate index for Section 1.1"
    assert result[2]['physical_index'] is not None, "Should interpolate index for Section 1.2"
    assert 10 < result[1]['physical_index'] < 20, "Interpolated value should be between bounds"
    assert result[1]['physical_index'] < result[2]['physical_index'], "Should maintain order"
    
    print("[PASS] Interpolation with both bounds works")


def test_interpolate_missing_indices_only_prev():
    """Test interpolation when only previous index exists"""
    toc = [
        {'title': 'Chapter 1', 'physical_index': 10},
        {'title': 'Section 1.1', 'physical_index': None},
        {'title': 'Section 1.2', 'physical_index': None},
    ]
    
    result = interpolate_missing_indices(toc, page_list_length=100, start_index=1)
    
    # Should increment from previous
    assert result[1]['physical_index'] == 11, "Should be prev + 1"
    assert result[2]['physical_index'] == 12, "Should be prev + 1"
    
    print("[PASS] Interpolation with only previous index works")


def test_interpolate_missing_indices_only_next():
    """Test interpolation when only next index exists"""
    toc = [
        {'title': 'Section 1.1', 'physical_index': None},
        {'title': 'Section 1.2', 'physical_index': None},
        {'title': 'Chapter 2', 'physical_index': 20},
    ]
    
    result = interpolate_missing_indices(toc, page_list_length=100, start_index=1)
    
    # Should decrement from next
    assert result[0]['physical_index'] is not None, "Should interpolate first item"
    assert result[0]['physical_index'] < 20, "Should be less than next index"
    
    print("[PASS] Interpolation with only next index works")


def test_interpolate_respects_boundaries():
    """Test that interpolation respects document boundaries"""
    toc = [
        {'title': 'Late Chapter', 'physical_index': 95},
        {'title': 'Section', 'physical_index': None},
    ]
    
    result = interpolate_missing_indices(toc, page_list_length=100, start_index=1)
    
    # Should not exceed max_allowed_page (100)
    assert result[1]['physical_index'] is not None, "Should interpolate"
    assert result[1]['physical_index'] <= 100, "Should not exceed document length"
    
    print("[PASS] Interpolation respects document boundaries")


def test_resolve_duplicate_indices():
    """Test duplicate index resolution"""
    toc = [
        {'title': 'Chapter 1', 'physical_index': 10},
        {'title': 'Section 1.1', 'physical_index': 15},
        {'title': 'Section 1.2', 'physical_index': 15},  # Duplicate
        {'title': 'Section 1.3', 'physical_index': 15},  # Duplicate
        {'title': 'Chapter 2', 'physical_index': 20},
    ]
    
    result = resolve_duplicate_indices(toc)
    
    # First occurrence should remain unchanged
    assert result[1]['physical_index'] == 15, "First occurrence should remain"
    
    # Duplicates should be incremented
    assert result[2]['physical_index'] == 16, "First duplicate should be incremented"
    assert result[3]['physical_index'] == 17, "Second duplicate should be incremented again"
    
    # All indices should be unique
    indices = [item['physical_index'] for item in result if item.get('physical_index') is not None]
    assert len(indices) == len(set(indices)), "All indices should be unique"
    
    print("[PASS] Duplicate index resolution works")


def test_validate_monotonic_increasing_valid():
    """Test monotonic validation with valid sequence"""
    toc = [
        {'title': 'Chapter 1', 'physical_index': 10},
        {'title': 'Section 1.1', 'physical_index': 15},
        {'title': 'Chapter 2', 'physical_index': 20},
        {'title': 'Section 2.1', 'physical_index': 25},
    ]
    
    is_valid, violations = validate_monotonic_increasing(toc)
    
    assert is_valid is True, "Sequence should be valid"
    assert len(violations) == 0, "Should have no violations"
    
    print("[PASS] Monotonic validation with valid sequence works")


def test_validate_monotonic_increasing_invalid():
    """Test monotonic validation with invalid sequence"""
    toc = [
        {'title': 'Chapter 1', 'physical_index': 10},
        {'title': 'Section 1.1', 'physical_index': 20},
        {'title': 'Section 1.2', 'physical_index': 15},  # Violation: goes backward
        {'title': 'Chapter 2', 'physical_index': 25},
    ]
    
    is_valid, violations = validate_monotonic_increasing(toc)
    
    assert is_valid is False, "Sequence should be invalid"
    assert len(violations) == 1, "Should have one violation"
    assert violations[0]['position'] == 2, "Violation should be at position 2"
    
    print("[PASS] Monotonic validation with invalid sequence works")


def test_validate_monotonic_with_none_values():
    """Test that None values are skipped in monotonic validation"""
    toc = [
        {'title': 'Chapter 1', 'physical_index': 10},
        {'title': 'Section 1.1', 'physical_index': None},
        {'title': 'Chapter 2', 'physical_index': 20},
        {'title': 'Section 2.1', 'physical_index': None},
        {'title': 'Chapter 3', 'physical_index': 30},
    ]
    
    is_valid, violations = validate_monotonic_increasing(toc)
    
    assert is_valid is True, "Should be valid (None values skipped)"
    assert len(violations) == 0, "Should have no violations"
    
    print("[PASS] Monotonic validation skips None values correctly")


def test_full_validation_pipeline():
    """Test the complete validation pipeline"""
    toc = [
        {'title': 'Chapter 1', 'physical_index': 10},
        {'title': 'Section 1.1', 'physical_index': None},  # Will be interpolated
        {'title': 'Section 1.2', 'physical_index': 15},
        {'title': 'Section 1.3', 'physical_index': 15},    # Duplicate - will be resolved
        {'title': 'Chapter 2', 'physical_index': None},     # Will be interpolated
        {'title': 'Section 2.1', 'physical_index': 30},
    ]
    
    result, report = validate_and_correct_physical_indices(
        toc,
        page_list_length=100,
        start_index=1
    )
    
    # Check report
    assert report['status'] == 'success', "Pipeline should succeed"
    assert report['final_valid_count'] > report['initial_valid_count'], "Should fill missing indices"
    
    # Check that all items now have valid indices
    none_count = sum(1 for item in result if item.get('physical_index') is None)
    assert none_count == 0, "All items should have physical_index"
    
    # Check monotonic property
    assert report['is_monotonic'] is True, "Result should be monotonically increasing"
    
    # Check uniqueness (duplicates resolved)
    indices = [item['physical_index'] for item in result]
    assert len(indices) == len(set(indices)), "All indices should be unique"
    
    print("[PASS] Full validation pipeline works")


def test_empty_toc():
    """Test that empty TOC is handled gracefully"""
    toc = []
    
    result = interpolate_missing_indices(toc, page_list_length=100, start_index=1)
    assert result == [], "Empty TOC should remain empty"
    
    result = resolve_duplicate_indices(toc)
    assert result == [], "Empty TOC should remain empty"
    
    is_valid, violations = validate_monotonic_increasing(toc)
    assert is_valid is True, "Empty TOC is trivially valid"
    
    result, report = validate_and_correct_physical_indices(toc, 100, 1)
    assert report['status'] == 'empty', "Should report empty status"
    
    print("[PASS] Empty TOC handling works")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("Testing Physical Index Validation Pipeline (Phase 1.2)")
    print("="*60 + "\n")
    
    try:
        test_interpolate_missing_indices_both_bounds()
        test_interpolate_missing_indices_only_prev()
        test_interpolate_missing_indices_only_next()
        test_interpolate_respects_boundaries()
        test_resolve_duplicate_indices()
        test_validate_monotonic_increasing_valid()
        test_validate_monotonic_increasing_invalid()
        test_validate_monotonic_with_none_values()
        test_full_validation_pipeline()
        test_empty_toc()
        
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
