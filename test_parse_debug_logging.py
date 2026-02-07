"""
Test script to verify parse debug logging is working.
"""
import sys
import os
from pathlib import Path

# Add paths
api_dir = Path(__file__).parent / "api"
sys.path.insert(0, str(api_dir))

from database import DatabaseManager, get_db
import uuid


def test_callback(operation_type: str, prompt: str, response: str,
                 model: str, duration_ms: int, success: bool,
                 error_msg: str, metadata: dict):
    """Test callback function."""
    print(f"[CALLBACK] {operation_type} | {model} | {duration_ms}ms | success={success}")


def test_parse_debug_logging():
    """Test that parse debug logging works."""
    print("=" * 70)
    print("Testing Parse Debug Logging")
    print("=" * 70)
    print()
    
    # Test 1: Set callback in utils
    print("1. Setting callback in pageindex.utils...")
    try:
        from pageindex.utils import set_llm_log_callback, get_llm_log_callback, _llm_log_callback
        set_llm_log_callback(test_callback)
        callback = get_llm_log_callback()
        if callback == test_callback:
            print("   [OK] Callback set successfully")
        else:
            print(f"   [ERROR] Callback not set correctly: {callback}")
    except Exception as e:
        print(f"   [ERROR] Failed to set callback: {e}")
    print()
    
    # Test 2: Direct database save
    print("2. Testing direct database save...")
    try:
        db = get_db()
        doc_id = "test-doc-123"
        
        # Create test document if not exists
        try:
            doc = db.create_document(
                document_id=doc_id,
                filename="test.pdf",
                file_type="pdf",
                file_path="uploads/test.pdf",
                file_size_bytes=1024,
                title="Test Document"
            )
            print(f"   [OK] Test document created")
        except Exception as e:
            print(f"   [INFO] Test document may already exist: {e}")
        
        # Save debug log
        log = db.save_parse_debug_log(
            document_id=doc_id,
            operation_type="test_operation",
            prompt="Test prompt",
            response="Test response",
            model_used="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            duration_ms=1000,
            success=True,
            error_message=None,
            metadata={"test": True}
        )
        print(f"   [OK] Debug log saved with ID: {log.id}")
        
        # Verify it was saved
        logs = db.get_parse_debug_logs(doc_id)
        print(f"   [OK] Retrieved {len(logs)} log(s) for test document")
        
        # Clean up
        db.delete_parse_debug_logs(doc_id)
        print(f"   [OK] Test logs cleaned up")
        
    except Exception as e:
        print(f"   [ERROR] Database test failed: {e}")
        import traceback
        traceback.print_exc()
    print()
    
    # Test 3: Check if pageindex.utils has logging code
    print("3. Checking pageindex.utils modifications...")
    try:
        import inspect
        from pageindex.utils import ChatGPT_API, ChatGPT_API_async, ChatGPT_API_with_finish_reason
        
        # Check if _llm_log_callback is used in functions
        for func_name, func in [
            ("ChatGPT_API", ChatGPT_API),
            ("ChatGPT_API_async", ChatGPT_API_async),
            ("ChatGPT_API_with_finish_reason", ChatGPT_API_with_finish_reason)
        ]:
            source = inspect.getsource(func)
            if "_llm_log_callback" in source:
                print(f"   [OK] {func_name} contains _llm_log_callback")
            else:
                print(f"   [WARNING] {func_name} does NOT contain _llm_log_callback")
    except Exception as e:
        print(f"   [ERROR] Failed to check functions: {e}")
    print()
    
    print("=" * 70)
    print("Test completed")
    print("=" * 70)


if __name__ == "__main__":
    test_parse_debug_logging()
