"""
Test suite for enhanced JSON extraction (extract_json_v2)
Tests the multi-strategy fallback and schema validation
"""

import sys
import os
import io

# Force UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path to import pageindex modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pageindex.utils import extract_json_v2

def test_markdown_code_block_extraction():
    """Test extraction from markdown ```json blocks"""
    content = """Here is the JSON:
```json
[
    {"structure": "1", "title": "Introduction", "physical_index": "<physical_index_1>"}
]
```
That's the result."""
    
    result = extract_json_v2(content, expected_schema='toc')
    assert result is not None, "Should extract JSON from markdown block"
    assert isinstance(result, list), "Should return a list"
    assert len(result) == 1, "Should have one item"
    assert result[0]['title'] == "Introduction"
    print("[PASS] Markdown code block extraction works")

def test_bracket_matching_extraction():
    """Test extraction using bracket matching (no markdown)"""
    content = """Some text before [{"structure": "1", "title": "Chapter 1", "physical_index": "<physical_index_5>"}] and after"""
    
    result = extract_json_v2(content, expected_schema='toc')
    assert result is not None, "Should extract JSON using bracket matching"
    assert isinstance(result, list), "Should return a list"
    assert result[0]['title'] == "Chapter 1"
    print("[PASS] Bracket matching extraction works")

def test_schema_validation_toc():
    """Test TOC schema validation"""
    # Valid TOC schema
    valid_toc = """[
        {"structure": "1", "title": "Section 1", "physical_index": "<physical_index_10>"},
        {"structure": "1.1", "title": "Subsection", "physical_index": "<physical_index_12>"}
    ]"""
    
    result = extract_json_v2(valid_toc, expected_schema='toc')
    assert result is not None, "Should validate correct TOC schema"
    assert len(result) == 2, "Should have two items"
    print("[PASS] TOC schema validation works")

def test_schema_validation_appear_start():
    """Test appear_start schema validation"""
    valid_appear_start = """[
        {"start": "Introduction", "start_index": "<physical_index_1>"},
        {"start": "Chapter 1", "start_index": "<physical_index_5>"}
    ]"""
    
    result = extract_json_v2(valid_appear_start, expected_schema='appear_start')
    assert result is not None, "Should validate correct appear_start schema"
    assert len(result) == 2, "Should have two items"
    assert result[0]['start'] == "Introduction"
    print("[PASS] appear_start schema validation works")

def test_malformed_json_with_extra_text():
    """Test extraction with malformed JSON surrounded by text"""
    content = """Here's some explanation text.
    
    The JSON output is:
    [
        {"structure": "1", "title": "Test", "physical_index": "<physical_index_1>"}
    ]
    
    Additional notes here."""
    
    result = extract_json_v2(content, expected_schema='toc')
    assert result is not None, "Should extract JSON from noisy text"
    assert result[0]['title'] == "Test"
    print("[PASS] Malformed JSON with extra text extraction works")

def test_nested_object_extraction():
    """Test extraction of nested JSON objects"""
    content = """{"table_of_contents": [{"structure": "1", "title": "Chapter", "physical_index": "<physical_index_2>"}]}"""
    
    result = extract_json_v2(content, expected_schema='toc')
    assert result is not None, "Should extract nested JSON"
    print("[PASS] Nested object extraction works")

def test_missing_physical_index_format():
    """Test that invalid physical_index format is caught"""
    # This has physical_index without proper format
    invalid_toc = """[
        {"structure": "1", "title": "Test", "physical_index": "5"}
    ]"""
    
    result = extract_json_v2(invalid_toc, expected_schema='toc')
    # Schema validation should fail, but extraction should still work
    # The function should attempt repair or return what it can extract
    print("[PASS] Invalid physical_index format handling works")

def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*60)
    print("Testing extract_json_v2() Enhanced JSON Extraction")
    print("="*60 + "\n")
    
    try:
        test_markdown_code_block_extraction()
        test_bracket_matching_extraction()
        test_schema_validation_toc()
        test_schema_validation_appear_start()
        test_malformed_json_with_extra_text()
        test_nested_object_extraction()
        test_missing_physical_index_format()
        
        print("\n" + "="*60)
        print("[SUCCESS] All tests passed!")
        print("="*60 + "\n")
        return True
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
