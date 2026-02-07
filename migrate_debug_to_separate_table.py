"""
Database migration script to separate debug information into a separate table.

This script:
1. Creates a new conversation_debugs table
2. Migrates existing debug data from conversations table (if any)
3. Removes system_prompt and raw_output columns from conversations table

Usage:
    python migrate_debug_to_separate_table.py
"""

import sqlite3
import os
import json
from pathlib import Path
import uuid


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


def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def migrate_debug_to_separate_table():
    """Migrate debug information to separate table."""
    db_path = get_database_path()
    
    if not os.path.exists(db_path):
        print(f"[WARNING] Database not found at: {db_path}")
        print("[INFO] Creating new database with updated schema...")
        return
    
    print(f"[INFO] Migrating database at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if conversation_debugs table already exists
        if table_exists(cursor, "conversation_debugs"):
            print("[OK] conversation_debugs table already exists")
        else:
            # Create conversation_debugs table
            print("[INFO] Creating conversation_debugs table...")
            cursor.execute("""
                CREATE TABLE conversation_debugs (
                    id VARCHAR PRIMARY KEY,
                    message_id VARCHAR NOT NULL,
                    document_id VARCHAR NOT NULL,
                    system_prompt TEXT,
                    raw_output TEXT,
                    model_used VARCHAR,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (message_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                )
            """)
            print("[OK] conversation_debugs table created")
        
        # Migrate existing data from conversations table (if columns exist and have data)
        if column_exists(cursor, "conversations", "system_prompt"):
            print("[INFO] Checking for existing debug data in conversations table...")
            cursor.execute("""
                SELECT id, document_id, system_prompt, raw_output, created_at
                FROM conversations
                WHERE system_prompt IS NOT NULL OR raw_output IS NOT NULL
            """)
            rows = cursor.fetchall()
            
            if rows:
                print(f"[INFO] Found {len(rows)} messages with debug data to migrate...")
                for row in rows:
                    msg_id, doc_id, sys_prompt, raw_out, created_at = row
                    cursor.execute("""
                        INSERT INTO conversation_debugs
                        (id, message_id, document_id, system_prompt, raw_output, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        str(uuid.uuid4()),
                        msg_id,
                        doc_id,
                        sys_prompt,
                        raw_out[:500] if raw_out else None,  # Truncate to 500 chars
                        created_at
                    ))
                print(f"[OK] Migrated {len(rows)} debug records")
            else:
                print("[INFO] No debug data to migrate")
        
        # Remove columns from conversations table (SQLite doesn't support DROP COLUMN directly)
        # We need to recreate the table
        print("[INFO] Removing debug columns from conversations table...")
        
        # Get current schema
        cursor.execute("PRAGMA table_info(conversations)")
        columns_info = cursor.fetchall()
        
        # Check if we need to remove columns
        columns_to_remove = ['system_prompt', 'raw_output']
        existing_columns = [col[1] for col in columns_info]
        columns_to_remove = [col for col in columns_to_remove if col in existing_columns]
        
        if columns_to_remove:
            # Build new table schema without debug columns
            new_columns = [col for col in existing_columns if col not in columns_to_remove]
            
            # Create new table
            columns_def = []
            for col in columns_info:
                col_name = col[1]
                if col_name in columns_to_remove:
                    continue
                col_type = col[2]
                not_null = "NOT NULL" if col[3] else ""
                default = f"DEFAULT {col[4]}" if col[4] is not None else ""
                pk = "PRIMARY KEY" if col[5] else ""
                columns_def.append(f"{col_name} {col_type} {not_null} {default} {pk}".strip())
            
            # SQLite requires special handling for table recreation
            # Start transaction
            cursor.execute("BEGIN TRANSACTION")
            
            # Rename old table
            cursor.execute("ALTER TABLE conversations RENAME TO conversations_old")
            
            # Create new table without debug columns
            create_sql = f"""
                CREATE TABLE conversations (
                    {', '.join(columns_def)}
                )
            """
            cursor.execute(create_sql)
            
            # Copy data
            columns_str = ', '.join(new_columns)
            cursor.execute(f"""
                INSERT INTO conversations ({columns_str})
                SELECT {columns_str} FROM conversations_old
            """)
            
            # Drop old table
            cursor.execute("DROP TABLE conversations_old")
            
            print(f"[OK] Removed columns: {', '.join(columns_to_remove)}")
        else:
            print("[INFO] No columns to remove")
        
        # Commit changes
        conn.commit()
        
        # Verify schema
        cursor.execute("PRAGMA table_info(conversations)")
        conversations_columns = [row[1] for row in cursor.fetchall()]
        print(f"\n[OK] Current conversations table columns: {', '.join(conversations_columns)}")
        
        cursor.execute("PRAGMA table_info(conversation_debugs)")
        debug_columns = [row[1] for row in cursor.fetchall()]
        print(f"[OK] conversation_debugs table columns: {', '.join(debug_columns)}")
        
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Debug Information Separation Migration")
    print("=" * 60)
    print()
    
    migrate_debug_to_separate_table()
    
    print()
    print("=" * 60)
    print("Migration completed successfully!")
    print("=" * 60)
