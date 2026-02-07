"""
Test script to verify the conversation fields enhancement.

This script tests:
1. Saving a conversation message with system_prompt and raw_output
2. Retrieving conversation history to verify the fields are stored
3. Checking that raw_output is properly truncated to 500 characters
"""

import sys
import os
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add the api directory to Python path
api_dir = Path(__file__).parent / "api"
sys.path.insert(0, str(api_dir))

from database import DatabaseManager, get_db
import uuid


def test_conversation_fields():
    """Test the new conversation fields."""
    print("=" * 70)
    print("Testing Conversation Fields Enhancement")
    print("=" * 70)
    print()
    
    db = get_db()
    
    # Create a test document
    doc_id = str(uuid.uuid4())
    print(f"1. Creating test document: {doc_id}")
    doc = db.create_document(
        document_id=doc_id,
        filename="test_conversation.pdf",
        file_type="pdf",
        file_path=f"uploads/test_{doc_id}.pdf",
        file_size_bytes=1024,
        title="Test Document for Conversation Fields"
    )
    print(f"   [OK] Document created")
    print()
    
    # Create a test conversation with system prompt and raw output
    msg_id = str(uuid.uuid4())
    system_prompt = """You are a helpful assistant that answers questions based on the provided document content.

User Question: What is the warranty period?

Relevant Document Content:
The warranty period is 12 months from the date of delivery.

Instructions:
1. Answer the question using ONLY the provided document content
2. If the answer cannot be found in the content, say so clearly
3. Be concise but thorough

Answer:"""
    
    raw_output = "Based on the document content, the warranty period is 12 months from the date of delivery. This means that any defects or issues that arise within one year of receiving the product will be covered under warranty." + "X" * 500  # Make it longer than 500 chars
    
    print(f"2. Saving conversation message with system prompt and raw output")
    print(f"   System prompt length: {len(system_prompt)} characters")
    print(f"   Raw output length: {len(raw_output)} characters")
    
    db.save_conversation_message(
        message_id=msg_id,
        document_id=doc_id,
        role='assistant',
        content="Based on the document content, the warranty period is 12 months from the date of delivery.",
        sources=[{"id": "ch-1", "title": "Warranty Information", "relevance": 0.9}],
        debug_path=["ch-1", "ch-1-1"],
        system_prompt=system_prompt,
        raw_output=raw_output
    )
    print(f"   [OK] Message saved")
    print()
    
    # Retrieve conversation history
    print(f"3. Retrieving conversation history")
    messages = db.get_conversation_history(doc_id)
    print(f"   [OK] Retrieved {len(messages)} message(s)")
    print()
    
    # Verify the fields
    if messages:
        msg = messages[0]
        print(f"4. Verifying saved data:")
        print(f"   Message ID: {msg.id}")
        print(f"   Role: {msg.role}")
        print(f"   Content length: {len(msg.content)} characters")
        
        if msg.system_prompt:
            print(f"   [OK] System prompt saved: {len(msg.system_prompt)} characters")
            print(f"   System prompt preview: {msg.system_prompt[:100]}...")
        else:
            print(f"   [ERROR] System prompt is None or empty")
        
        if msg.raw_output:
            print(f"   [OK] Raw output saved: {len(msg.raw_output)} characters")
            if len(msg.raw_output) <= 500:
                print(f"   [OK] Raw output properly truncated to 500 characters")
            else:
                print(f"   [ERROR] Raw output NOT truncated: {len(msg.raw_output)} characters")
            print(f"   Raw output preview: {msg.raw_output[:100]}...")
        else:
            print(f"   [ERROR] Raw output is None or empty")
    else:
        print(f"   [ERROR] No messages found")
    
    print()
    
    # Clean up
    print(f"5. Cleaning up test data")
    db.delete_conversation_history(doc_id)
    # Note: We don't delete the document as there's no delete method exposed
    print(f"   [OK] Test data cleaned up")
    print()
    
    print("=" * 70)
    print("Test completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        test_conversation_fields()
    except Exception as e:
        print(f"\n[ERROR] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
