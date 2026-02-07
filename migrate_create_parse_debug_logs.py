"""
Database migration script to create parse_debug_logs table.

This table stores LLM call logs during document parsing for debugging purposes.

Usage:
    python migrate_create_parse_debug_logs.py
"""

import sqlite3
import os
from pathlib import Path


def get_database_path():
    """Get the path to the database file."""
    possible_paths = [
        Path(__file__).parent / "data" / "documents.db",
        Path(__file__).parent.parent.parent / "data" / "documents.db",
        Path("data") / "documents.db",
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path)
    
    return str(Path(__file__).parent / "data" / "documents.db")


def table_exists(cursor, table_name):
    """Check if a table exists."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def migrate_create_parse_debug_logs():
    """Create parse_debug_logs table."""
    db_path = get_database_path()
    
    if not os.path.exists(db_path):
        print(f"[WARNING] Database not found at: {db_path}")
        print("[INFO] Creating new database with updated schema...")
        return
    
    print(f"[INFO] Migrating database at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if table already exists
        if table_exists(cursor, "parse_debug_logs"):
            print("[OK] parse_debug_logs table already exists")
            return
        
        # Create parse_debug_logs table
        print("[INFO] Creating parse_debug_logs table...")
        cursor.execute("""
            CREATE TABLE parse_debug_logs (
                id VARCHAR PRIMARY KEY,
                document_id VARCHAR NOT NULL,
                operation_type VARCHAR NOT NULL,
                prompt TEXT,
                response TEXT,
                model_used VARCHAR,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                duration_ms INTEGER,
                success BOOLEAN NOT NULL DEFAULT 1,
                error_message TEXT,
                metadata_json TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX idx_parse_debug_logs_document_id 
            ON parse_debug_logs(document_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_parse_debug_logs_operation_type 
            ON parse_debug_logs(operation_type)
        """)
        
        conn.commit()
        print("[OK] parse_debug_logs table created successfully")
        
        # Verify table was created
        cursor.execute("PRAGMA table_info(parse_debug_logs)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"[OK] Table columns: {', '.join(columns)}")
        
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Parse Debug Logs Table Migration")
    print("=" * 60)
    print()
    
    migrate_create_parse_debug_logs()
    
    print()
    print("=" * 60)
    print("Migration completed successfully!")
    print("=" * 60)
