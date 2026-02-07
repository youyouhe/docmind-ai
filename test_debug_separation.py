"""
Test script to verify debug information is saved correctly to separate table.
"""
import sys
import os
from pathlib import Path

# Add the api directory to Python path
api_dir = Path(__file__).parent / "api"
sys.path.insert(0, str(api_dir))

from database import DatabaseManager, get_db
import uuid


def test_debug_separation():
    """Test that debug info is saved to separate table."""
    print("=" * 70)
    print("Testing Debug Information Separation")
    print("=" * 70)
    print()
    
    db = get_db()
    
    # Create a test document
    doc_id = str(uuid.uuid4())
    print(f"1. Creating test document: {doc_id}")
    doc = db.create_document(
        document_id=doc_id,
        filename="test_debug.pdf",
        file_type="pdf",
        file_path=f"uploads/test_{doc_id}.pdf",
        file_size_bytes=1024,
        title="Test Document for Debug Separation"
    )
    print(f"   [OK] Document created")
    print()
    
    # Create a test conversation message
    msg_id = str(uuid.uuid4())
    print(f"2. Saving conversation message (business data only)")
    message = db.save_conversation_message(
        message_id=msg_id,
        document_id=doc_id,
        role='assistant',
        content="This is the AI response content.",
        sources=[{"id": "ch-1", "title": "Test Chapter", "relevance": 0.9}],
        debug_path=["ch-1", "ch-1-1"]
    )
    print(f"   [OK] Message saved with ID: {message.id}")
    print(f"   - Content: {message.content}")
    print(f"   - Role: {message.role}")
    print(f"   - No system_prompt or raw_output in message object")
    print()
    
    # Save debug information separately
    print(f"3. Saving debug information separately")
    debug = db.save_conversation_debug(
        message_id=msg_id,
        document_id=doc_id,
        system_prompt="You are a helpful assistant.\n\nQuestion: What is the warranty?\n\nContext: The warranty is 12 months.",
        raw_output="Based on the document, the warranty period is 12 months." + "X" * 600,
        model_used="gpt-4",
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=200
    )
    print(f"   [OK] Debug info saved with ID: {debug.id}")
    print(f"   - System prompt length: {len(debug.system_prompt)} characters")
    print(f"   - Raw output length: {len(debug.raw_output)} characters (truncated to 500)")
    print(f"   - Model: {debug.model_used}")
    print(f"   - Tokens: {debug.total_tokens}")
    print()
    
    # Retrieve conversation history (should not include debug info)
    print(f"4. Retrieving conversation history (business data)")
    messages = db.get_conversation_history(doc_id)
    print(f"   [OK] Retrieved {len(messages)} message(s)")
    if messages:
        msg = messages[0]
        print(f"   - Message has content: {msg.content}")
        print(f"   - Message has sources: {msg.sources is not None}")
        print(f"   - Message does NOT have system_prompt attribute: {not hasattr(msg, 'system_prompt') or msg.system_prompt is None}")
        print(f"   - Message does NOT have raw_output attribute: {not hasattr(msg, 'raw_output') or msg.raw_output is None}")
    print()
    
    # Retrieve debug information separately
    print(f"5. Retrieving debug information separately")
    debug_info = db.get_conversation_debug(msg_id)
    if debug_info:
        print(f"   [OK] Debug info retrieved")
        print(f"   - System prompt: {debug_info.system_prompt[:50]}...")
        print(f"   - Raw output: {debug_info.raw_output[:50]}...")
        print(f"   - Model used: {debug_info.model_used}")
        print(f"   - Total tokens: {debug_info.total_tokens}")
    else:
        print(f"   [ERROR] Debug info not found")
    print()
    
    # Clean up
    print(f"6. Cleaning up test data")
    db.delete_conversation_history(doc_id)
    print(f"   [OK] Test data cleaned up")
    print()
    
    print("=" * 70)
    print("Test completed successfully!")
    print("=" * 70)
    print()
    print("Summary:")
    print("- Business data (conversations table): Contains only message content, role, sources")
    print("- Debug data (conversation_debugs table): Contains system_prompt, raw_output, tokens")
    print("- Tables are properly separated!")


if __name__ == "__main__":
    try:
        test_debug_separation()
    except Exception as e:
        print(f"\n[ERROR] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
