"""
Database models and management for PageIndex document storage.

Uses SQLite with SQLAlchemy for metadata storage only.
File contents are stored in the filesystem.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship


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
