"""
Database models and management for PageIndex document storage.

Uses SQLite with SQLAlchemy for metadata storage only.
File contents are stored in the filesystem.
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# Initialize logger
logger = logging.getLogger("pageindex.api.database")


# =============================================================================
# Configuration
# =============================================================================

# Default database path
DEFAULT_DB_PATH = "data/documents.db"
DEFAULT_DATA_DIR = "data"


def get_database_path() -> str:
    """Get database path from environment or use default."""
    return os.getenv("PAGEINDEX_DB_PATH", DEFAULT_DB_PATH)


def get_data_dir() -> Path:
    """Get data directory path."""
    db_path = Path(get_database_path())
    return db_path.parent


# =============================================================================
# SQLAlchemy Setup
# =============================================================================

Base = declarative_base()


# =============================================================================
# Database Models
# =============================================================================

class Document(Base):
    """
    Document table - stores only metadata.

    File content is stored in filesystem at data/uploads/{id}.{ext}
    """
    __tablename__ = "documents"

    id = Column(String, primary_key=True)  # UUID v4
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # 'pdf' or 'markdown'
    file_path = Column(String, nullable=False)  # Relative path to uploaded file
    file_size_bytes = Column(Integer, nullable=False)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    parse_status = Column(String, nullable=False, default="pending")  # pending/processing/completed/failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    parse_config = Column(Text, nullable=True)  # JSON string
    category = Column(String, nullable=True)  # Document category (e.g., "教育招标")
    tags = Column(Text, nullable=True)  # Document tags as JSON string (e.g., '["教育", "大学"]')

    # Relationship to parse results
    parse_results = relationship("ParseResult", back_populates="document", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        import json

        tags_list = []
        if self.tags:
            try:
                tags_list = json.loads(self.tags)
            except:
                tags_list = []

        return {
            "id": self.id,
            "filename": self.filename,
            "file_type": self.file_type,
            "file_size_bytes": self.file_size_bytes,
            "title": self.title,
            "description": self.description,
            "parse_status": self.parse_status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "category": self.category,
            "tags": tags_list,
        }


class ParseResult(Base):
    """
    Parse results table - stores only metadata and file paths.

    Actual tree data is stored in filesystem at data/parsed/{id}_tree.json
    Statistics are stored at data/parsed/{id}_stats.json
    """
    __tablename__ = "parse_results"

    id = Column(String, primary_key=True)  # UUID v4 (same as document_id or separate)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    tree_path = Column(String, nullable=False)  # Relative path to tree JSON
    stats_path = Column(String, nullable=False)  # Relative path to stats JSON
    model_used = Column(String, nullable=False)
    parsed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    parse_duration_ms = Column(Integer, nullable=True)
    performance_stats = Column(Text, nullable=True)  # JSON: detailed performance metrics

    # Relationship to document
    document = relationship("Document", back_populates="parse_results")

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "model_used": self.model_used,
            "parsed_at": self.parsed_at.isoformat() if self.parsed_at else None,
            "parse_duration_ms": self.parse_duration_ms,
            "performance_stats": self.performance_stats,
        }


class Conversation(Base):
    """
    Conversation history table - stores chat messages for documents.

    Each message is stored as a separate row with document_id reference.
    """
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)  # UUID v4
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Optional metadata
    sources = Column(Text, nullable=True)  # JSON: source information
    debug_path = Column(Text, nullable=True)  # JSON: debug path for highlighting
    # Note: Debug information is stored separately in conversation_debugs table

    # Relationship to document
    document = relationship("Document")

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sources": self.sources,
            "debug_path": self.debug_path,
            # Note: Debug info is stored separately in conversation_debugs table
        }


class ConversationDebug(Base):
    """
    Conversation debug information table - stores detailed debug data for conversation messages.
    
    This table is separate from the main conversations table to keep business data clean.
    Debug information can be deleted without affecting conversation history.
    """
    __tablename__ = "conversation_debugs"
    
    id = Column(String, primary_key=True)  # UUID v4
    message_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    system_prompt = Column(Text, nullable=True)  # Complete system prompt used
    raw_output = Column(Text, nullable=True)  # Raw LLM output (truncated to 500 chars)
    model_used = Column(String, nullable=True)  # LLM model name (e.g., 'gpt-4')
    prompt_tokens = Column(Integer, nullable=True)  # Number of tokens in prompt
    completion_tokens = Column(Integer, nullable=True)  # Number of tokens in completion
    total_tokens = Column(Integer, nullable=True)  # Total tokens used
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship to conversation message
    conversation = relationship("Conversation")
    # Relationship to document
    document = relationship("Document")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "message_id": self.message_id,
            "document_id": self.document_id,
            "system_prompt": self.system_prompt,
            "raw_output": self.raw_output,
            "model_used": self.model_used,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ParseDebugLog(Base):
    """
    Parse debug log table - stores LLM call logs during document parsing.
    
    This table records all LLM interactions during the parsing process,
    including prompts, responses, tokens used, and timing information.
    Useful for debugging parse quality and LLM performance.
    """
    __tablename__ = "parse_debug_logs"
    
    id = Column(String, primary_key=True)  # UUID v4
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    operation_type = Column(String, nullable=False)  # e.g., 'toc_extraction', 'node_summary', 'structure_analysis'
    prompt = Column(Text, nullable=True)  # The prompt sent to LLM
    response = Column(Text, nullable=True)  # The LLM response (truncated)
    model_used = Column(String, nullable=True)  # LLM model name
    prompt_tokens = Column(Integer, nullable=True)  # Number of tokens in prompt
    completion_tokens = Column(Integer, nullable=True)  # Number of tokens in response
    total_tokens = Column(Integer, nullable=True)  # Total tokens used
    duration_ms = Column(Integer, nullable=True)  # Call duration in milliseconds
    success = Column(Boolean, nullable=False, default=True)  # Whether the call succeeded
    error_message = Column(Text, nullable=True)  # Error message if failed
    metadata_json = Column(Text, nullable=True)  # Additional metadata as JSON (e.g., node_id, page_range)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship to document
    document = relationship("Document")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        import json
        return {
            "id": self.id,
            "document_id": self.document_id,
            "operation_type": self.operation_type,
            "prompt": self.prompt,
            "response": self.response,
            "model_used": self.model_used,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": json.loads(self.metadata_json) if self.metadata_json else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditReport(Base):
    """
    Audit report table - stores metadata for document structure audits.
    
    The actual audit content is stored in filesystem at data/parsed/{doc_id}_audit_report.json
    """
    __tablename__ = "audit_reports"
    
    audit_id = Column(String, primary_key=True)  # UUID v4
    doc_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String, nullable=True)  # e.g., "招标文件"
    quality_score = Column(Integer, nullable=True)  # Overall quality score (0-100)
    total_suggestions = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="pending")  # pending/applied/rolled_back
    applied_at = Column(DateTime, nullable=True)  # When suggestions were applied
    backup_id = Column(String, nullable=True)  # Reference to backup snapshot
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship to document
    document = relationship("Document")
    
    # Relationship to suggestions
    suggestions = relationship("AuditSuggestion", back_populates="audit_report", cascade="all, delete-orphan")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "audit_id": self.audit_id,
            "doc_id": self.doc_id,
            "document_type": self.document_type,
            "quality_score": self.quality_score,
            "total_suggestions": self.total_suggestions,
            "status": self.status,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "backup_id": self.backup_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditSuggestion(Base):
    """
    Audit suggestion table - stores individual suggestions for tree modifications.
    
    Tracks user review status and actions for each suggestion.
    """
    __tablename__ = "audit_suggestions"
    
    suggestion_id = Column(String, primary_key=True)  # UUID v4
    audit_id = Column(String, ForeignKey("audit_reports.audit_id", ondelete="CASCADE"), nullable=False)
    doc_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    action = Column(String, nullable=False)  # DELETE, ADD, MODIFY_FORMAT, MODIFY_PAGE
    node_id = Column(String, nullable=True)  # Target node ID (null for ADD actions)
    status = Column(String, nullable=False, default="pending")  # pending/accepted/rejected/applied
    confidence = Column(String, nullable=True)  # high, medium, low
    reason = Column(Text, nullable=True)  # Explanation for the suggestion
    current_title = Column(Text, nullable=True)  # Current title (for MODIFY actions)
    suggested_title = Column(Text, nullable=True)  # Suggested title (for MODIFY/ADD actions)
    node_info = Column(Text, nullable=True)  # JSON: additional context (siblings, parent, etc.)
    user_action = Column(String, nullable=True)  # accept/reject (set by user)
    user_comment = Column(Text, nullable=True)  # Optional user comment
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)  # When user reviewed
    
    # Relationships
    audit_report = relationship("AuditReport", back_populates="suggestions")
    document = relationship("Document")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        import json
        
        node_info_dict = None
        if self.node_info:
            try:
                node_info_dict = json.loads(self.node_info)
            except:
                node_info_dict = {}
        
        return {
            "suggestion_id": self.suggestion_id,
            "audit_id": self.audit_id,
            "doc_id": self.doc_id,
            "action": self.action,
            "node_id": self.node_id,
            "status": self.status,
            "confidence": self.confidence,
            "reason": self.reason,
            "current_title": self.current_title,
            "suggested_title": self.suggested_title,
            "node_info": node_info_dict,
            "user_action": self.user_action,
            "user_comment": self.user_comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


class AuditBackup(Base):
    """
    Audit backup table - stores tree snapshots for rollback functionality.
    
    Backup data is stored in filesystem at data/parsed/{doc_id}_audit_backup_{backup_id}.json
    """
    __tablename__ = "audit_backups"
    
    backup_id = Column(String, primary_key=True)  # UUID v4
    doc_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    audit_id = Column(String, ForeignKey("audit_reports.audit_id", ondelete="CASCADE"), nullable=False)
    backup_path = Column(String, nullable=False)  # Path to backup JSON file
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    document = relationship("Document")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "backup_id": self.backup_id,
            "doc_id": self.doc_id,
            "audit_id": self.audit_id,
            "backup_path": self.backup_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# Database Manager
# =============================================================================

class DatabaseManager:
    """
    Manages database connections and operations.

    Usage:
        db = DatabaseManager()
        doc = db.create_document(document_id, filename, file_type, ...)
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file (default: from env or data/documents.db)
        """
        self.db_path = db_path or get_database_path()
        self.data_dir = Path(self.db_path).parent

        # Ensure data directory exists
        self._ensure_data_dir()

        # Create engine
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},  # Needed for FastAPI
            echo=False,
        )

        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

    def _ensure_data_dir(self):
        """Ensure data directory exists."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.data_dir / "uploads").mkdir(exist_ok=True)
        (self.data_dir / "parsed").mkdir(exist_ok=True)

    def init_db(self):
        """Create all tables in the database and run migrations."""
        Base.metadata.create_all(bind=self.engine)
        self._run_migrations()

    def _run_migrations(self):
        """Run database migrations to add missing columns."""
        from sqlalchemy import inspect, text

        with self.engine.connect() as conn:
            inspector = inspect(conn)

            # Migration for documents table
            doc_columns = [col['name'] for col in inspector.get_columns('documents')]

            # Migration 1: Add category column if missing
            if 'category' not in doc_columns:
                print("[Migration] Adding category column to documents table...")
                conn.execute(text("ALTER TABLE documents ADD COLUMN category TEXT"))
                conn.commit()
                print("[Migration] Done: category column added")

            # Migration 2: Add tags column if missing
            if 'tags' not in doc_columns:
                print("[Migration] Adding tags column to documents table...")
                conn.execute(text("ALTER TABLE documents ADD COLUMN tags TEXT"))
                conn.commit()
                print("[Migration] Done: tags column added")

            # Migration for parse_results table
            result_columns = [col['name'] for col in inspector.get_columns('parse_results')]

            # Migration 3: Add performance_stats column if missing
            if 'performance_stats' not in result_columns:
                print("[Migration] Adding performance_stats column to parse_results table...")
                conn.execute(text("ALTER TABLE parse_results ADD COLUMN performance_stats TEXT"))
                conn.commit()
                print("[Migration] Done: performance_stats column added")
            
            # Migration 4-6: Create audit tables if missing
            tables = inspector.get_table_names()
            
            if 'audit_reports' not in tables:
                print("[Migration] Creating audit_reports table...")
                conn.execute(text("""
                    CREATE TABLE audit_reports (
                        audit_id VARCHAR PRIMARY KEY,
                        doc_id VARCHAR NOT NULL,
                        document_type VARCHAR,
                        quality_score INTEGER,
                        total_suggestions INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR NOT NULL DEFAULT 'pending',
                        applied_at TIMESTAMP,
                        backup_id VARCHAR,
                        created_at TIMESTAMP NOT NULL,
                        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
                    )
                """))
                conn.commit()
                print("[Migration] Done: audit_reports table created")
            
            if 'audit_suggestions' not in tables:
                print("[Migration] Creating audit_suggestions table...")
                conn.execute(text("""
                    CREATE TABLE audit_suggestions (
                        suggestion_id VARCHAR PRIMARY KEY,
                        audit_id VARCHAR NOT NULL,
                        doc_id VARCHAR NOT NULL,
                        action VARCHAR NOT NULL,
                        node_id VARCHAR,
                        status VARCHAR NOT NULL DEFAULT 'pending',
                        confidence VARCHAR,
                        reason TEXT,
                        current_title TEXT,
                        suggested_title TEXT,
                        node_info TEXT,
                        user_action VARCHAR,
                        user_comment TEXT,
                        created_at TIMESTAMP NOT NULL,
                        reviewed_at TIMESTAMP,
                        FOREIGN KEY (audit_id) REFERENCES audit_reports(audit_id) ON DELETE CASCADE,
                        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
                    )
                """))
                conn.commit()
                print("[Migration] Done: audit_suggestions table created")
            
            if 'audit_backups' not in tables:
                print("[Migration] Creating audit_backups table...")
                conn.execute(text("""
                    CREATE TABLE audit_backups (
                        backup_id VARCHAR PRIMARY KEY,
                        doc_id VARCHAR NOT NULL,
                        audit_id VARCHAR NOT NULL,
                        backup_path VARCHAR NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
                        FOREIGN KEY (audit_id) REFERENCES audit_reports(audit_id) ON DELETE CASCADE
                    )
                """))
                conn.commit()
                print("[Migration] Done: audit_backups table created")

    def drop_all(self):
        """Drop all tables (use with caution!)."""
        Base.metadata.drop_all(bind=self.engine)

    @contextmanager
    def get_session(self) -> Session:
        """
        Get a database session with automatic cleanup.

        Usage:
            with db.get_session() as session:
                docs = session.query(Document).all()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # Document Operations
    # -------------------------------------------------------------------------

    def create_document(
        self,
        document_id: str,
        filename: str,
        file_type: str,
        file_path: str,
        file_size_bytes: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        parse_config: Optional[str] = None,
    ) -> Document:
        """
        Create a new document record.

        Args:
            document_id: Unique document ID (UUID)
            filename: Original filename
            file_type: File type ('pdf' or 'markdown')
            file_path: Path to uploaded file (relative to data dir)
            file_size_bytes: File size in bytes
            title: Optional document title
            description: Optional document description
            parse_config: Optional JSON parse config

        Returns:
            Created Document instance
        """
        with self.get_session() as session:
            doc = Document(
                id=document_id,
                filename=filename,
                file_type=file_type,
                file_path=file_path,
                file_size_bytes=file_size_bytes,
                title=title,
                description=description,
                parse_status="pending",
                parse_config=parse_config,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            return doc

    def get_document(self, document_id: str) -> Optional[Document]:
        """Get a document by ID."""
        with self.get_session() as session:
            doc = session.query(Document).filter(Document.id == document_id).first()
            if doc is None:
                return None
            return self._merge_detached(doc)

    def list_documents(
        self,
        file_type: Optional[str] = None,
        parse_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Document]:
        """
        List documents with optional filters.

        Args:
            file_type: Filter by file type ('pdf' or 'markdown')
            parse_status: Filter by parse status
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of Document instances
        """
        with self.get_session() as session:
            query = session.query(Document)

            if file_type:
                query = query.filter(Document.file_type == file_type)
            if parse_status:
                query = query.filter(Document.parse_status == parse_status)

            results = query.order_by(Document.created_at.desc()).limit(limit).offset(offset).all()
            # Detach from session by converting to list of dicts and back
            # This ensures objects can be accessed after session closes
            return [self._merge_detached(doc) for doc in results]

    def _merge_detached(self, doc: Document) -> Document:
        """Create a detached copy of a document for use outside session."""
        if doc is None:
            return None
        # Create a new instance with same attributes
        return Document(
            id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            file_path=doc.file_path,
            file_size_bytes=doc.file_size_bytes,
            title=doc.title,
            description=doc.description,
            parse_status=doc.parse_status,
            error_message=doc.error_message,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            parse_config=doc.parse_config,
            category=doc.category,
            tags=doc.tags,
        )

    def update_document_status(
        self,
        document_id: str,
        parse_status: str,
        error_message: Optional[str] = None,
    ) -> Optional[Document]:
        """
        Update document parse status.

        Args:
            document_id: Document ID
            parse_status: New parse status
            error_message: Optional error message

        Returns:
            Updated Document instance or None
        """
        with self.get_session() as session:
            doc = session.query(Document).filter(Document.id == document_id).first()
            if doc:
                doc.parse_status = parse_status
                if error_message:
                    doc.error_message = error_message
                doc.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(doc)
                return doc
            return None

    def update_document_category_tags(
        self,
        document_id: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[Document]:
        """
        Update document category and tags.

        Args:
            document_id: Document ID
            category: Category name (e.g., "教育招标")
            tags: List of tags (e.g., ["教育", "大学"])

        Returns:
            Updated Document instance or None
        """
        import json

        with self.get_session() as session:
            doc = session.query(Document).filter(Document.id == document_id).first()
            if doc:
                if category is not None:
                    doc.category = category
                if tags is not None:
                    doc.tags = json.dumps(tags, ensure_ascii=False)
                doc.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(doc)
                return doc
            return None

    def delete_document(self, document_id: str) -> bool:
        """
        Delete a document and associated parse results.

        Args:
            document_id: Document ID

        Returns:
            True if deleted, False if not found
        """
        with self.get_session() as session:
            doc = session.query(Document).filter(Document.id == document_id).first()
            if doc:
                # Explicitly delete audit backup records first
                # This is needed because the foreign key constraint is NO ACTION instead of CASCADE
                backup_count = session.query(AuditBackup).filter(
                    AuditBackup.doc_id == document_id
                ).delete()
                if backup_count > 0:
                    logger.info(f"Deleted {backup_count} audit backup records for document {document_id}")
                
                # Now delete the document
                session.delete(doc)
                session.commit()
                return True
            return False

    # -------------------------------------------------------------------------
    # Parse Result Operations
    # -------------------------------------------------------------------------

    def create_parse_result(
        self,
        result_id: str,
        document_id: str,
        tree_path: str,
        stats_path: str,
        model_used: str,
        parse_duration_ms: Optional[int] = None,
    ) -> ParseResult:
        """
        Create a parse result record.

        Args:
            result_id: Unique result ID
            document_id: Document ID
            tree_path: Path to tree JSON file (relative to data dir)
            stats_path: Path to stats JSON file (relative to data dir)
            model_used: Model used for parsing
            parse_duration_ms: Parse duration in milliseconds

        Returns:
            Created ParseResult instance
        """
        with self.get_session() as session:
            result = ParseResult(
                id=result_id,
                document_id=document_id,
                tree_path=tree_path,
                stats_path=stats_path,
                model_used=model_used,
                parse_duration_ms=parse_duration_ms,
            )
            session.add(result)
            session.commit()
            session.refresh(result)
            return result

    def get_parse_result(self, document_id: str) -> Optional[ParseResult]:
        """Get the latest parse result for a document."""
        with self.get_session() as session:
            result = session.query(ParseResult).filter(
                ParseResult.document_id == document_id
            ).order_by(ParseResult.parsed_at.desc()).first()
            if result is None:
                return None
            # Return a detached copy
            return ParseResult(
                id=result.id,
                document_id=result.document_id,
                tree_path=result.tree_path,
                stats_path=result.stats_path,
                model_used=result.model_used,
                parsed_at=result.parsed_at,
                parse_duration_ms=result.parse_duration_ms,
                performance_stats=result.performance_stats,
            )

    def delete_parse_results(self, document_id: str) -> int:
        """
        Delete all parse results for a document.

        Args:
            document_id: Document ID

        Returns:
            Number of results deleted
        """
        with self.get_session() as session:
            count = session.query(ParseResult).filter(
                ParseResult.document_id == document_id
            ).delete()
            session.commit()
            return count

    def update_parse_performance_stats(
        self,
        result_id: str,
        performance_stats: Dict[str, Any]
    ) -> bool:
        """
        Update performance statistics for a parse result.

        Args:
            result_id: Parse result ID
            performance_stats: Performance statistics dictionary

        Returns:
            True if updated, False if not found
        """
        import json

        with self.get_session() as session:
            result = session.query(ParseResult).filter(
                ParseResult.id == result_id
            ).first()

            if result is None:
                return False

            result.performance_stats = json.dumps(performance_stats)
            result.updated_at = datetime.utcnow()
            session.commit()
            return True

    def get_parse_performance_stats(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Get performance statistics for a document's parse result.

        Args:
            document_id: Document ID

        Returns:
            Performance statistics dictionary or None if not found
        """
        result = self.get_parse_result(document_id)
        if result and result.performance_stats:
            try:
                return json.loads(result.performance_stats)
            except json.JSONDecodeError:
                return {"error": "Failed to parse performance stats"}
        return None

    # -------------------------------------------------------------------------
    # Conversation Operations
    # -------------------------------------------------------------------------

    def save_conversation_message(
        self,
        message_id: str,
        document_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        debug_path: Optional[List[str]] = None,
    ) -> Conversation:
        """
        Save a conversation message.

        Args:
            message_id: Unique message ID (UUID)
            document_id: Document ID
            role: Message role ('user' or 'assistant')
            content: Message content
            sources: Optional source information
            debug_path: Optional debug path for highlighting

        Returns:
            Created Conversation instance
        """
        import json

        with self.get_session() as session:
            message = Conversation(
                id=message_id,
                document_id=document_id,
                role=role,
                content=content,
                sources=json.dumps(sources) if sources else None,
                debug_path=json.dumps(debug_path) if debug_path else None,
            )
            session.add(message)
            session.commit()
            session.refresh(message)
            return message

    def save_conversation_debug(
        self,
        message_id: str,
        document_id: str,
        system_prompt: Optional[str] = None,
        raw_output: Optional[str] = None,
        model_used: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ) -> ConversationDebug:
        """
        Save conversation debug information to separate table.

        Args:
            message_id: Associated message ID (UUID)
            document_id: Document ID
            system_prompt: System prompt used for this message
            raw_output: Raw LLM output (will be truncated to 500 chars)
            model_used: LLM model name used
            prompt_tokens: Number of tokens in prompt
            completion_tokens: Number of tokens in completion
            total_tokens: Total tokens used

        Returns:
            Created ConversationDebug instance
        """
        import uuid

        # Truncate raw_output to 500 characters if provided
        truncated_output = raw_output[:500] if raw_output else None

        with self.get_session() as session:
            debug = ConversationDebug(
                id=str(uuid.uuid4()),
                message_id=message_id,
                document_id=document_id,
                system_prompt=system_prompt,
                raw_output=truncated_output,
                model_used=model_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
            session.add(debug)
            session.commit()
            session.refresh(debug)
            return debug

    def get_conversation_history(self, document_id: str, limit: int = 100) -> List[Conversation]:
        """
        Get conversation history for a document.

        Args:
            document_id: Document ID
            limit: Maximum number of messages to return

        Returns:
            List of Conversation instances, ordered by creation time
        """
        with self.get_session() as session:
            messages = session.query(Conversation).filter(
                Conversation.document_id == document_id
            ).order_by(Conversation.created_at.asc()).limit(limit).all()

            # Return detached copies
            return [
                Conversation(
                    id=m.id,
                    document_id=m.document_id,
                    role=m.role,
                    content=m.content,
                    created_at=m.created_at,
                    sources=m.sources,
                    debug_path=m.debug_path,
                )
                for m in messages
            ]

    def get_conversation_debug(self, message_id: str) -> Optional[ConversationDebug]:
        """
        Get debug information for a specific conversation message.

        Args:
            message_id: Message ID

        Returns:
            ConversationDebug instance or None if not found
        """
        with self.get_session() as session:
            debug = session.query(ConversationDebug).filter(
                ConversationDebug.message_id == message_id
            ).first()
            
            if not debug:
                return None
            
            # Return detached copy
            return ConversationDebug(
                id=debug.id,
                message_id=debug.message_id,
                document_id=debug.document_id,
                system_prompt=debug.system_prompt,
                raw_output=debug.raw_output,
                model_used=debug.model_used,
                prompt_tokens=debug.prompt_tokens,
                completion_tokens=debug.completion_tokens,
                total_tokens=debug.total_tokens,
                created_at=debug.created_at,
            )

    def delete_conversation_history(self, document_id: str) -> int:
        """
        Delete all conversation history for a document.

        Args:
            document_id: Document ID

        Returns:
            Number of messages deleted
        """
        with self.get_session() as session:
            count = session.query(Conversation).filter(
                Conversation.document_id == document_id
            ).delete()
            session.commit()
            return count

    # -------------------------------------------------------------------------
    # Parse Debug Log Operations
    # -------------------------------------------------------------------------

    def save_parse_debug_log(
        self,
        document_id: str,
        operation_type: str,
        prompt: Optional[str] = None,
        response: Optional[str] = None,
        model_used: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        duration_ms: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParseDebugLog:
        """
        Save a parse debug log entry for LLM calls during document parsing.

        Args:
            document_id: Document ID
            operation_type: Type of operation (e.g., 'toc_extraction', 'node_summary')
            prompt: The prompt sent to LLM
            response: The LLM response (will be truncated to 1000 chars)
            model_used: LLM model name
            prompt_tokens: Number of tokens in prompt
            completion_tokens: Number of tokens in response
            total_tokens: Total tokens used
            duration_ms: Call duration in milliseconds
            success: Whether the call succeeded
            error_message: Error message if failed
            metadata: Additional metadata as dict

        Returns:
            Created ParseDebugLog instance
        """
        import uuid
        import json

        # Truncate response to 1000 characters if provided
        truncated_response = response[:1000] if response else None

        with self.get_session() as session:
            log = ParseDebugLog(
                id=str(uuid.uuid4()),
                document_id=document_id,
                operation_type=operation_type,
                prompt=prompt,
                response=truncated_response,
                model_used=model_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
                metadata_json=json.dumps(metadata) if metadata else None,
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return log

    def get_parse_debug_logs(
        self,
        document_id: str,
        operation_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[ParseDebugLog]:
        """
        Get parse debug logs for a document.

        Args:
            document_id: Document ID
            operation_type: Optional filter by operation type
            limit: Maximum number of logs to return

        Returns:
            List of ParseDebugLog instances
        """
        with self.get_session() as session:
            query = session.query(ParseDebugLog).filter(
                ParseDebugLog.document_id == document_id
            )
            
            if operation_type:
                query = query.filter(ParseDebugLog.operation_type == operation_type)
            
            logs = query.order_by(ParseDebugLog.created_at.asc()).limit(limit).all()
            
            # Return detached copies
            return [
                ParseDebugLog(
                    id=log.id,
                    document_id=log.document_id,
                    operation_type=log.operation_type,
                    prompt=log.prompt,
                    response=log.response,
                    model_used=log.model_used,
                    prompt_tokens=log.prompt_tokens,
                    completion_tokens=log.completion_tokens,
                    total_tokens=log.total_tokens,
                    duration_ms=log.duration_ms,
                    success=log.success,
                    error_message=log.error_message,
                    metadata_json=log.metadata_json,
                    created_at=log.created_at,
                )
                for log in logs
            ]

    def delete_parse_debug_logs(self, document_id: str) -> int:
        """
        Delete all parse debug logs for a document.

        Args:
            document_id: Document ID

        Returns:
            Number of logs deleted
        """
        with self.get_session() as session:
            count = session.query(ParseDebugLog).filter(
                ParseDebugLog.document_id == document_id
            ).delete()
            session.commit()
            return count

    # -------------------------------------------------------------------------
    # Audit Report Operations
    # -------------------------------------------------------------------------

    def create_audit_report(
        self,
        audit_id: str,
        doc_id: str,
        document_type: Optional[str] = None,
        quality_score: Optional[int] = None,
        total_suggestions: int = 0,
    ) -> AuditReport:
        """
        Create a new audit report record.

        Args:
            audit_id: Unique audit ID (UUID)
            doc_id: Document ID
            document_type: Type of document (e.g., "招标文件")
            quality_score: Overall quality score (0-100)
            total_suggestions: Total number of suggestions

        Returns:
            Created AuditReport instance
        """
        with self.get_session() as session:
            report = AuditReport(
                audit_id=audit_id,
                doc_id=doc_id,
                document_type=document_type,
                quality_score=quality_score,
                total_suggestions=total_suggestions,
                status="pending",
            )
            session.add(report)
            session.commit()
            session.refresh(report)
            
            # Return detached copy
            return AuditReport(
                audit_id=report.audit_id,
                doc_id=report.doc_id,
                document_type=report.document_type,
                quality_score=report.quality_score,
                total_suggestions=report.total_suggestions,
                status=report.status,
                applied_at=report.applied_at,
                backup_id=report.backup_id,
                created_at=report.created_at,
            )

    def get_audit_report(self, doc_id: str) -> Optional[AuditReport]:
        """Get the latest audit report for a document."""
        with self.get_session() as session:
            report = session.query(AuditReport).filter(
                AuditReport.doc_id == doc_id
            ).order_by(AuditReport.created_at.desc()).first()
            
            if report is None:
                return None
            
            # Return detached copy
            return AuditReport(
                audit_id=report.audit_id,
                doc_id=report.doc_id,
                document_type=report.document_type,
                quality_score=report.quality_score,
                total_suggestions=report.total_suggestions,
                status=report.status,
                applied_at=report.applied_at,
                backup_id=report.backup_id,
                created_at=report.created_at,
            )

    def update_audit_report_status(
        self,
        audit_id: str,
        status: str,
        backup_id: Optional[str] = None,
    ) -> bool:
        """
        Update audit report status (e.g., mark as applied).

        Args:
            audit_id: Audit report ID
            status: New status ('pending', 'applied', 'rolled_back')
            backup_id: Optional backup ID reference

        Returns:
            True if updated, False if not found
        """
        with self.get_session() as session:
            report = session.query(AuditReport).filter(
                AuditReport.audit_id == audit_id
            ).first()
            
            if report is None:
                return False
            
            report.status = status
            if backup_id:
                report.backup_id = backup_id
            if status == "applied":
                report.applied_at = datetime.utcnow()
            
            session.commit()
            return True

    # -------------------------------------------------------------------------
    # Audit Suggestion Operations
    # -------------------------------------------------------------------------

    def create_audit_suggestion(
        self,
        suggestion_id: str,
        audit_id: str,
        doc_id: str,
        action: str,
        node_id: Optional[str] = None,
        confidence: Optional[str] = None,
        reason: Optional[str] = None,
        current_title: Optional[str] = None,
        suggested_title: Optional[str] = None,
        node_info: Optional[Dict[str, Any]] = None,
    ) -> AuditSuggestion:
        """
        Create a new audit suggestion record.

        Args:
            suggestion_id: Unique suggestion ID (UUID)
            audit_id: Audit report ID
            doc_id: Document ID
            action: Action type (DELETE, ADD, MODIFY_FORMAT, MODIFY_PAGE)
            node_id: Target node ID
            confidence: Confidence level (high, medium, low)
            reason: Explanation for the suggestion
            current_title: Current title (for MODIFY actions)
            suggested_title: Suggested title (for MODIFY/ADD actions)
            node_info: Additional context as dictionary

        Returns:
            Created AuditSuggestion instance
        """
        import json
        
        with self.get_session() as session:
            suggestion = AuditSuggestion(
                suggestion_id=suggestion_id,
                audit_id=audit_id,
                doc_id=doc_id,
                action=action,
                node_id=node_id,
                status="pending",
                confidence=confidence,
                reason=reason,
                current_title=current_title,
                suggested_title=suggested_title,
                node_info=json.dumps(node_info) if node_info else None,
            )
            session.add(suggestion)
            session.commit()
            session.refresh(suggestion)
            
            # Return detached copy
            return AuditSuggestion(
                suggestion_id=suggestion.suggestion_id,
                audit_id=suggestion.audit_id,
                doc_id=suggestion.doc_id,
                action=suggestion.action,
                node_id=suggestion.node_id,
                status=suggestion.status,
                confidence=suggestion.confidence,
                reason=suggestion.reason,
                current_title=suggestion.current_title,
                suggested_title=suggestion.suggested_title,
                node_info=suggestion.node_info,
                user_action=suggestion.user_action,
                user_comment=suggestion.user_comment,
                created_at=suggestion.created_at,
                reviewed_at=suggestion.reviewed_at,
            )

    def get_suggestions(
        self,
        audit_id: str,
        action: Optional[str] = None,
        status: Optional[str] = None,
        confidence: Optional[str] = None,
    ) -> List[AuditSuggestion]:
        """
        Get suggestions for an audit report with optional filters.

        Args:
            audit_id: Audit report ID
            action: Filter by action type (DELETE, ADD, MODIFY_FORMAT, MODIFY_PAGE)
            status: Filter by status (pending, accepted, rejected, applied)
            confidence: Filter by confidence (high, medium, low)

        Returns:
            List of AuditSuggestion instances
        """
        with self.get_session() as session:
            query = session.query(AuditSuggestion).filter(
                AuditSuggestion.audit_id == audit_id
            )
            
            if action:
                query = query.filter(AuditSuggestion.action == action)
            if status:
                query = query.filter(AuditSuggestion.status == status)
            if confidence:
                query = query.filter(AuditSuggestion.confidence == confidence)
            
            suggestions = query.order_by(AuditSuggestion.created_at.asc()).all()
            
            # Return detached copies
            return [
                AuditSuggestion(
                    suggestion_id=s.suggestion_id,
                    audit_id=s.audit_id,
                    doc_id=s.doc_id,
                    action=s.action,
                    node_id=s.node_id,
                    status=s.status,
                    confidence=s.confidence,
                    reason=s.reason,
                    current_title=s.current_title,
                    suggested_title=s.suggested_title,
                    node_info=s.node_info,
                    user_action=s.user_action,
                    user_comment=s.user_comment,
                    created_at=s.created_at,
                    reviewed_at=s.reviewed_at,
                )
                for s in suggestions
            ]

    def get_suggestion(self, suggestion_id: str) -> Optional[AuditSuggestion]:
        """Get a single suggestion by ID."""
        with self.get_session() as session:
            s = session.query(AuditSuggestion).filter(
                AuditSuggestion.suggestion_id == suggestion_id
            ).first()
            
            if s is None:
                return None
            
            return AuditSuggestion(
                suggestion_id=s.suggestion_id,
                audit_id=s.audit_id,
                doc_id=s.doc_id,
                action=s.action,
                node_id=s.node_id,
                status=s.status,
                confidence=s.confidence,
                reason=s.reason,
                current_title=s.current_title,
                suggested_title=s.suggested_title,
                node_info=s.node_info,
                user_action=s.user_action,
                user_comment=s.user_comment,
                created_at=s.created_at,
                reviewed_at=s.reviewed_at,
            )

    def update_suggestion_review(
        self,
        suggestion_id: str,
        user_action: str,
        user_comment: Optional[str] = None,
    ) -> bool:
        """
        Update suggestion with user review (accept/reject).

        Args:
            suggestion_id: Suggestion ID
            user_action: User action ('accept' or 'reject')
            user_comment: Optional user comment

        Returns:
            True if updated, False if not found
        """
        with self.get_session() as session:
            suggestion = session.query(AuditSuggestion).filter(
                AuditSuggestion.suggestion_id == suggestion_id
            ).first()
            
            if suggestion is None:
                return False
            
            suggestion.user_action = user_action
            suggestion.user_comment = user_comment
            suggestion.status = "accepted" if user_action == "accept" else "rejected"
            suggestion.reviewed_at = datetime.utcnow()
            
            session.commit()
            return True

    def update_suggestions_status(
        self,
        suggestion_ids: List[str],
        status: str,
    ) -> int:
        """
        Batch update suggestion status (e.g., mark as applied).

        Args:
            suggestion_ids: List of suggestion IDs
            status: New status

        Returns:
            Number of suggestions updated
        """
        with self.get_session() as session:
            count = session.query(AuditSuggestion).filter(
                AuditSuggestion.suggestion_id.in_(suggestion_ids)
            ).update({"status": status}, synchronize_session=False)
            session.commit()
            return count

    # -------------------------------------------------------------------------
    # Audit Backup Operations
    # -------------------------------------------------------------------------

    def create_audit_backup(
        self,
        backup_id: str,
        doc_id: str,
        audit_id: str,
        backup_path: str,
        max_backups: int = 10,
    ) -> AuditBackup:
        """
        Create a backup snapshot for rollback.
        
        Automatically cleans up old backups, keeping only the most recent max_backups.

        Args:
            backup_id: Unique backup ID (UUID)
            doc_id: Document ID
            audit_id: Audit report ID
            backup_path: Path to backup JSON file (relative to data dir)
            max_backups: Maximum number of backups to keep per document (default: 10)

        Returns:
            Created AuditBackup instance
        """
        import os
        from pathlib import Path
        
        with self.get_session() as session:
            backup = AuditBackup(
                backup_id=backup_id,
                doc_id=doc_id,
                audit_id=audit_id,
                backup_path=backup_path,
            )
            session.add(backup)
            session.commit()
            session.refresh(backup)
            
            # Auto-cleanup: Keep only the most recent max_backups backups for this document
            all_backups = session.query(AuditBackup).filter(
                AuditBackup.doc_id == doc_id
            ).order_by(AuditBackup.created_at.desc()).all()
            
            if len(all_backups) > max_backups:
                # Get backups to delete (oldest ones beyond max_backups limit)
                backups_to_delete = all_backups[max_backups:]
                data_dir = get_data_dir()
                
                for old_backup in backups_to_delete:
                    # Delete backup file from filesystem
                    backup_file = data_dir / old_backup.backup_path
                    try:
                        if backup_file.exists():
                            os.remove(backup_file)
                    except Exception as e:
                        print(f"Warning: Failed to delete backup file {backup_file}: {e}")
                    
                    # Delete backup record from database
                    session.delete(old_backup)
                
                session.commit()
                print(f"Cleaned up {len(backups_to_delete)} old backups for document {doc_id}")
            
            # Return detached copy
            return AuditBackup(
                backup_id=backup.backup_id,
                doc_id=backup.doc_id,
                audit_id=backup.audit_id,
                backup_path=backup.backup_path,
                created_at=backup.created_at,
            )

    def get_audit_backup(self, backup_id: str) -> Optional[AuditBackup]:
        """Get a backup by ID."""
        with self.get_session() as session:
            backup = session.query(AuditBackup).filter(
                AuditBackup.backup_id == backup_id
            ).first()
            
            if backup is None:
                return None
            
            return AuditBackup(
                backup_id=backup.backup_id,
                doc_id=backup.doc_id,
                audit_id=backup.audit_id,
                backup_path=backup.backup_path,
                created_at=backup.created_at,
            )

    def get_backups_by_document(self, doc_id: str) -> List[AuditBackup]:
        """
        Get all backups for a document, ordered by creation time (newest first).
        
        Args:
            doc_id: Document ID
            
        Returns:
            List of AuditBackup instances
        """
        with self.get_session() as session:
            backups = session.query(AuditBackup).filter(
                AuditBackup.doc_id == doc_id
            ).order_by(AuditBackup.created_at.desc()).all()
            
            return [
                AuditBackup(
                    backup_id=b.backup_id,
                    doc_id=b.doc_id,
                    audit_id=b.audit_id,
                    backup_path=b.backup_path,
                    created_at=b.created_at,
                )
                for b in backups
            ]

    def delete_audit_backups_by_document(self, doc_id: str) -> int:
        """
        Delete all audit backup records for a document.
        
        NOTE: This only deletes database records. Files should be deleted separately
        via storage.delete_all_document_data().
        
        Args:
            doc_id: Document ID
            
        Returns:
            Number of backup records deleted
        """
        with self.get_session() as session:
            count = session.query(AuditBackup).filter(
                AuditBackup.doc_id == doc_id
            ).delete()
            session.commit()
            logger.info(f"Deleted {count} audit backup records for document {doc_id}")
            return count


# =============================================================================
# Global Database Instance
# =============================================================================

_db_manager: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """Get the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
        _db_manager.init_db()
    return _db_manager


def init_database(db_path: Optional[str] = None) -> DatabaseManager:
    """
    Initialize the database.

    Args:
        db_path: Optional custom database path

    Returns:
        DatabaseManager instance
    """
    global _db_manager
    _db_manager = DatabaseManager(db_path)
    _db_manager.init_db()
    return _db_manager
