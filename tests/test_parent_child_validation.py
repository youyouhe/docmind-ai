"""
Test suite for parent-child consistency validation (Phase 1.4)
Tests hierarchical structure validation and auto-correction
"""

import sys
import os
import io

# Force UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pageindex.utils import validate_parent_child_consistency


def test_valid_hierarchy():
    """Test validation passes for correct parent-child structure"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 10},
        {'structure': '1.1', 'title': 'Section 1.1', 'physical_index': 15},
        {'structure': '1.2', 'title': 'Section 1.2', 'physical_index': 20},
        {'structure': '2', 'title': 'Chapter 2', 'physical_index': 30},
        {'structure': '2.1', 'title': 'Section 2.1', 'physical_index': 35},
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['status'] == 'success', "Should have no violations"
    assert report['violations_count'] == 0, "Should have 0 violations"
    assert report['fixes_applied'] == 0, "Should apply 0 fixes"
    
    print("[PASS] Valid hierarchy passes validation")


def test_parent_after_child():
    """Test detection and fix of parent appearing after child"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 50},  # Wrong: parent after child
        {'structure': '1.1', 'title': 'Section 1.1', 'physical_index': 15},
        {'structure': '1.2', 'title': 'Section 1.2', 'physical_index': 20},
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['status'] == 'violations_found', "Should find violations"
    assert report['violations_count'] > 0, "Should have violations"
    assert report['violation_types']['parent_after_child'] == 2, "Should have 2 parent_after_child violations"
    assert report['fixes_applied'] == 2, "Should apply 2 fixes"
    
    # Check that parent was fixed
    parent = next(item for item in result if item['structure'] == '1')
    assert parent['physical_index'] == 15, "Parent should be adjusted to child's minimum page"
    
    print("[PASS] Parent-after-child violation detected and fixed")


def test_orphaned_child():
    """Test detection of orphaned children (parent doesn't exist)"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 10},
        {'structure': '2.1', 'title': 'Section 2.1', 'physical_index': 20},  # Orphaned: no Chapter 2
        {'structure': '2.2', 'title': 'Section 2.2', 'physical_index': 25},  # Orphaned: no Chapter 2
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['status'] == 'violations_found', "Should find violations"
    assert report['violation_types']['orphaned_child'] == 2, "Should have 2 orphaned children"
    
    print("[PASS] Orphaned children detected")


def test_non_monotonic_same_level():
    """Test detection of non-monotonic ordering at same hierarchy level"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 10},
        {'structure': '2', 'title': 'Chapter 2', 'physical_index': 30},
        {'structure': '3', 'title': 'Chapter 3', 'physical_index': 20},  # Wrong: goes backward
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['status'] == 'violations_found', "Should find violations"
    assert report['violation_types']['non_monotonic_same_level'] >= 1, "Should have non-monotonic violation"
    
    print("[PASS] Non-monotonic same-level ordering detected")


def test_deep_hierarchy():
    """Test validation with deep nested structure"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 10},
        {'structure': '1.1', 'title': 'Section 1.1', 'physical_index': 15},
        {'structure': '1.1.1', 'title': 'Subsection 1.1.1', 'physical_index': 16},
        {'structure': '1.1.2', 'title': 'Subsection 1.1.2', 'physical_index': 18},
        {'structure': '1.2', 'title': 'Section 1.2', 'physical_index': 20},
        {'structure': '1.2.1', 'title': 'Subsection 1.2.1', 'physical_index': 21},
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['status'] == 'success', "Deep hierarchy should be valid"
    assert report['violations_count'] == 0, "Should have no violations"
    
    print("[PASS] Deep hierarchy validates correctly")


def test_multiple_violation_types():
    """Test handling of multiple violation types simultaneously"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 50},  # parent_after_child
        {'structure': '1.1', 'title': 'Section 1.1', 'physical_index': 15},
        {'structure': '2.1', 'title': 'Section 2.1', 'physical_index': 20},  # orphaned_child
        {'structure': '3', 'title': 'Chapter 3', 'physical_index': 30},
        {'structure': '4', 'title': 'Chapter 4', 'physical_index': 25},  # non_monotonic
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['status'] == 'violations_found', "Should find multiple violation types"
    assert report['violations_count'] >= 3, "Should have at least 3 violations"
    assert report['violation_types']['parent_after_child'] >= 1, "Should have parent_after_child"
    assert report['violation_types']['orphaned_child'] >= 1, "Should have orphaned_child"
    assert report['violation_types']['non_monotonic_same_level'] >= 1, "Should have non_monotonic"
    
    print("[PASS] Multiple violation types detected correctly")


def test_empty_structure():
    """Test handling of empty structure"""
    structure = []
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['status'] == 'empty', "Should report empty status"
    assert result == [], "Should return empty list"
    
    print("[PASS] Empty structure handled correctly")


def test_structure_with_none_indices():
    """Test handling of items with None physical_index"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 10},
        {'structure': '1.1', 'title': 'Section 1.1', 'physical_index': None},  # None index
        {'structure': '2', 'title': 'Chapter 2', 'physical_index': 20},
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    # Should skip validation for items with None indices
    assert report['status'] == 'success', "Should skip None indices"
    
    print("[PASS] None indices handled correctly")


def test_fix_preserves_other_fields():
    """Test that fixes don't corrupt other fields"""
    structure = [
        {'structure': '1', 'title': 'Chapter 1', 'physical_index': 50, 'extra_field': 'data1'},
        {'structure': '1.1', 'title': 'Section 1.1', 'physical_index': 15, 'extra_field': 'data2'},
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    # Check that extra fields are preserved
    for item in result:
        assert 'extra_field' in item, "Extra fields should be preserved"
        assert 'title' in item, "Title should be preserved"
        assert 'structure' in item, "Structure should be preserved"
    
    print("[PASS] Fixes preserve other fields correctly")


def test_complex_real_world_scenario():
    """Test realistic document structure with various issues"""
    structure = [
        {'structure': '0', 'title': 'Preface', 'physical_index': 1},
        {'structure': '1', 'title': 'Introduction', 'physical_index': 5},
        {'structure': '1.1', 'title': 'Background', 'physical_index': 6},
        {'structure': '1.2', 'title': 'Motivation', 'physical_index': 8},
        {'structure': '2', 'title': 'Methodology', 'physical_index': 3},  # Wrong: before children
        {'structure': '2.1', 'title': 'Data Collection', 'physical_index': 10},
        {'structure': '2.2', 'title': 'Analysis', 'physical_index': 15},
        {'structure': '3', 'title': 'Results', 'physical_index': 20},
        {'structure': '3.1', 'title': 'Findings', 'physical_index': 21},
        {'structure': '4', 'title': 'Conclusion', 'physical_index': 25},
    ]
    
    result, report = validate_parent_child_consistency(structure)
    
    assert report['violations_count'] > 0, "Should find violations"
    assert report['fixes_applied'] > 0, "Should apply fixes"
    
    # Check that Chapter 2 was fixed to be before its children
    chapter2 = next(item for item in result if item['structure'] == '2')
    assert chapter2['physical_index'] <= 10, "Chapter 2 should be adjusted to be before children"
    
    print("[PASS] Complex real-world scenario handled correctly")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("Testing Parent-Child Consistency Validation (Phase 1.4)")
    print("="*60 + "\n")
    
    try:
        test_valid_hierarchy()
        test_parent_after_child()
        test_orphaned_child()
        test_non_monotonic_same_level()
        test_deep_hierarchy()
        test_multiple_violation_types()
        test_empty_structure()
        test_structure_with_none_indices()
        test_fix_preserves_other_fields()
        test_complex_real_world_scenario()
        
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
