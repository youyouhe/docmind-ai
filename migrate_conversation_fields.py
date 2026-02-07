"""
Database migration script to add system_prompt and raw_output fields to conversations table.

This script adds two new columns to the conversations table:
- system_prompt: TEXT (nullable) - stores the complete system prompt used for the conversation
- raw_output: TEXT (nullable) - stores the raw LLM output, truncated to 500 characters

Usage:
    python migrate_conversation_fields.py
"""

import sqlite3
import os
from pathlib import Path


def get_database_path():
    """Get the path to the database file."""
    # Try to find the database in the expected location
    possible_paths = [
        Path(__file__).parent / "data" / "documents.db",
        Path(__file__).parent.parent.parent / "data" / "documents.db",
        Path("data") / "documents.db",
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path)
    
    # If not found, use the default location
    return str(Path(__file__).parent / "data" / "documents.db")


def check_columns_exist(cursor):
    """Check if the new columns already exist."""
    cursor.execute("PRAGMA table_info(conversations)")
    columns = [row[1] for row in cursor.fetchall()]
    return "system_prompt" in columns and "raw_output" in columns


def migrate_database():
    """Add system_prompt and raw_output columns to conversations table."""
    db_path = get_database_path()
    
    if not os.path.exists(db_path):
        print(f"Database not found at: {db_path}")
        print("Creating new database with updated schema...")
        # Database will be created automatically with the new schema
        return
    
    print(f"Migrating database at: {db_path}")
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        if check_columns_exist(cursor):
            print("[OK] Columns already exist. No migration needed.")
            return
        
        # Add system_prompt column
        print("Adding system_prompt column...")
        cursor.execute("""
            ALTER TABLE conversations 
            ADD COLUMN system_prompt TEXT
        """)
        
        # Add raw_output column
        print("Adding raw_output column...")
        cursor.execute("""
            ALTER TABLE conversations 
            ADD COLUMN raw_output TEXT
        """)
        
        # Commit changes
        conn.commit()
        print("[OK] Migration completed successfully!")
        
        # Verify columns were added
        cursor.execute("PRAGMA table_info(conversations)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"\nCurrent columns in conversations table: {', '.join(columns)}")
        
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Conversation Fields Migration Script")
    print("=" * 60)
    print()
    
    migrate_database()
    
    print()
    print("=" * 60)
    print("Migration process completed")
    print("=" * 60)
