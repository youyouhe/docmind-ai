"""
File storage service for PageIndex documents.

Handles file upload, download, and deletion operations.
Uses UUID-based naming for safe concurrent access.
"""

import os
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

import aiofiles
from fastapi import UploadFile, HTTPException

# Configure logging
logger = logging.getLogger("pageindex.api.storage")


# =============================================================================
# Configuration
# =============================================================================

def get_data_dir() -> Path:
    """Get data directory path."""
    db_path = os.getenv("PAGEINDEX_DB_PATH", "data/documents.db")
    return Path(db_path).parent


# =============================================================================
# Storage Service
# =============================================================================

class StorageService:
    """
    File storage service for document uploads and parsed results.

    Storage structure:
        data/
        ├── uploads/           # Original uploaded files
        │   ├── {uuid}.pdf
        │   └── {uuid}.md
        └── parsed/            # Parse result JSON files
            ├── {uuid}_tree.json
            └── {uuid}_stats.json
    """

    # File size limits (in bytes)
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB default

    # Allowed file extensions
    ALLOWED_PDF_EXTENSIONS = {".pdf"}
    ALLOWED_MARKDOWN_EXTENSIONS = {".md", ".markdown"}

    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize storage service.

        Args:
            data_dir: Data directory path (default: from env or data/)
        """
        self.data_dir = data_dir or get_data_dir()
        self.uploads_dir = self.data_dir / "uploads"
        self.parsed_dir = self.data_dir / "parsed"

        # Ensure directories exist
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure storage directories exist."""
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # File Type Detection
    # -------------------------------------------------------------------------

    @staticmethod
    def detect_file_type(filename: str) -> Optional[str]:
        """
        Detect file type from filename.

        Args:
            filename: Name of the file

        Returns:
            'pdf', 'markdown', or None
        """
        name_lower = filename.lower()
        if name_lower.endswith(".pdf"):
            return "pdf"
        elif name_lower.endswith((".md", ".markdown")):
            return "markdown"
        return None

    @staticmethod
    def get_file_extension(file_type: str) -> str:
        """
        Get file extension for file type.

        Args:
            file_type: 'pdf' or 'markdown'

        Returns:
            File extension including dot
        """
        extensions = {
            "pdf": ".pdf",
            "markdown": ".md",
        }
        return extensions.get(file_type, "")

    @staticmethod
    def validate_file_type(filename: str) -> Tuple[bool, Optional[str]]:
        """
        Validate file type.

        Args:
            filename: Name of the file

        Returns:
            Tuple of (is_valid, file_type)
        """
        file_type = StorageService.detect_file_type(filename)
        if file_type is None:
            return False, None
        return True, file_type

    # -------------------------------------------------------------------------
    # File Upload
    # -------------------------------------------------------------------------

    async def save_upload(
        self,
        file: UploadFile,
        max_size: Optional[int] = None,
    ) -> Tuple[str, str, int]:
        """
        Save uploaded file to storage.

        Args:
            file: FastAPI UploadFile
            max_size: Maximum file size in bytes (default: MAX_FILE_SIZE)

        Returns:
            Tuple of (document_id, relative_path, file_size)

        Raises:
            HTTPException: If file type is invalid or size exceeds limit
        """
        max_size = max_size or self.MAX_FILE_SIZE

        # Validate file type
        is_valid, file_type = self.validate_file_type(file.filename or "")
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: .pdf, .md, .markdown"
            )

        # Ensure directory exists (in case it was deleted)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        # Generate UUID for document
        document_id = str(uuid.uuid4())
        extension = self.get_file_extension(file_type)
        filename = f"{document_id}{extension}"
        file_path = self.uploads_dir / filename
        relative_path = f"uploads/{filename}"

        # Save file
        file_size = 0
        try:
            async with aiofiles.open(file_path, "wb") as f:
                while content := await file.read(1024 * 1024):  # 1MB chunks
                    file_size += len(content)
                    if file_size > max_size:
                        await f.close()
                        # Delete partial file
                        file_path.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File size exceeds limit of {max_size} bytes"
                        )
                    await f.write(content)
        except HTTPException:
            raise
        except Exception as e:
            # Clean up on error
            file_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save file: {str(e)}"
            )

        return document_id, relative_path, file_size

    def delete_upload(self, relative_path: str) -> bool:
        """
        Delete uploaded file.

        Args:
            relative_path: Relative path from data directory

        Returns:
            True if deleted, False if not found
        """
        file_path = self.data_dir / relative_path
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    # -------------------------------------------------------------------------
    # Parse Result Storage
    # -------------------------------------------------------------------------

    def save_parse_result(
        self,
        document_id: str,
        tree_data: dict,
        stats_data: dict,
    ) -> Tuple[str, str]:
        """
        Save parse result to storage.

        Args:
            document_id: Document ID
            tree_data: Tree structure dictionary
            stats_data: Statistics dictionary

        Returns:
            Tuple of (tree_path, stats_path) relative to data directory
        """
        import json

        # Ensure directory exists (in case it was deleted)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)

        tree_filename = f"{document_id}_tree.json"
        stats_filename = f"{document_id}_stats.json"

        tree_path = self.parsed_dir / tree_filename
        stats_path = self.parsed_dir / stats_filename

        # Write tree data
        with open(tree_path, "w", encoding="utf-8") as f:
            json.dump(tree_data, f, ensure_ascii=False, indent=2)

        # Write stats data
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats_data, f, ensure_ascii=False, indent=2)

        return f"parsed/{tree_filename}", f"parsed/{stats_filename}"

    def save_audit_report(
        self,
        document_id: str,
        audit_data: dict,
    ) -> str:
        """
        Save tree audit report to storage.

        Args:
            document_id: Document ID
            audit_data: Audit report dictionary

        Returns:
            Audit report path relative to data directory
        """
        import json

        # Ensure directory exists (in case it was deleted)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)

        audit_filename = f"{document_id}_audit_report.json"
        audit_path = self.parsed_dir / audit_filename

        # Write audit data
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, ensure_ascii=False, indent=2)

        return f"parsed/{audit_filename}"

    async def load_parse_result(self, document_id: str) -> Optional[dict]:
        """
        Load parse result from storage.

        Args:
            document_id: Document ID

        Returns:
            Tree data dictionary or None
        """
        import json

        tree_path = self.parsed_dir / f"{document_id}_tree.json"

        if not tree_path.exists():
            return None

        async with aiofiles.open(tree_path, "r", encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)

    async def load_stats(self, document_id: str) -> Optional[dict]:
        """
        Load statistics from storage.

        Args:
            document_id: Document ID

        Returns:
            Statistics dictionary or None
        """
        import json

        stats_path = self.parsed_dir / f"{document_id}_stats.json"

        if not stats_path.exists():
            return None

        async with aiofiles.open(stats_path, "r", encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)

    def delete_parse_results(self, document_id: str) -> bool:
        """
        Delete ALL parse result files for a document, including:
        - tree.json
        - stats.json
        - audit_report.json
        - All audit backup files (audit_backup_*.json)
        - All other document-related JSON files

        Args:
            document_id: Document ID

        Returns:
            True if any files were deleted
        """
        deleted = False
        deleted_files = []
        
        # Define specific file patterns to delete
        file_patterns = [
            f"{document_id}_tree.json",
            f"{document_id}_stats.json",
            f"{document_id}_audit_report.json",
        ]
        
        # Delete specific files
        for filename in file_patterns:
            file_path = self.parsed_dir / filename
            if file_path.exists():
                file_path.unlink()
                deleted = True
                deleted_files.append(filename)
        
        # Delete all audit backup files (using glob pattern)
        # Pattern: {document_id}_audit_backup_*.json
        audit_backup_pattern = f"{document_id}_audit_backup_*.json"
        for backup_file in self.parsed_dir.glob(audit_backup_pattern):
            backup_file.unlink()
            deleted = True
            deleted_files.append(backup_file.name)
        
        # Log deleted files for debugging
        if deleted_files:
            logger.info(f"Deleted {len(deleted_files)} parse result files for document {document_id}: {deleted_files}")
        else:
            logger.debug(f"No parse result files found for document {document_id}")

        return deleted

    # -------------------------------------------------------------------------
    # File Download
    # -------------------------------------------------------------------------

    def _safe_resolve(self, relative_path: str) -> Path:
        """
        Resolve a relative path safely, preventing path traversal attacks.

        Args:
            relative_path: Relative path from data directory

        Returns:
            Resolved absolute file path

        Raises:
            ValueError: If path traversal is detected
        """
        full_path = (self.data_dir / relative_path).resolve()
        if not str(full_path).startswith(str(self.data_dir.resolve())):
            raise ValueError(f"Path traversal detected: {relative_path}")
        return full_path

    def get_upload_path(self, relative_path: str) -> Path:
        """
        Get absolute path for uploaded file.

        Args:
            relative_path: Relative path from data directory

        Returns:
            Absolute file path

        Raises:
            ValueError: If path traversal is detected
        """
        return self._safe_resolve(relative_path)

    def file_exists(self, relative_path: str) -> bool:
        """
        Check if file exists.

        Args:
            relative_path: Relative path from data directory

        Returns:
            True if file exists
        """
        try:
            return self._safe_resolve(relative_path).exists()
        except ValueError:
            return False

    def get_pdf_pages(self, file_path: str, page_start: int, page_end: int) -> list:
        """
        Extract text content from specific pages of a PDF file.
        Falls back to OCR cache for scanned pages with little/no text.

        Args:
            file_path: Path to the PDF file
            page_start: Starting page number (1-based)
            page_end: Ending page number (1-based, inclusive)

        Returns:
            List of tuples (page_number, page_text)
        """
        import pymupdf

        pages = []
        doc = pymupdf.open(file_path)

        for page_num in range(page_start - 1, min(page_end, len(doc))):
            page = doc[page_num]
            page_text = page.get_text("text")

            # For scanned pages with little text, try OCR cache
            if len(page_text.strip()) < 50:
                ocr_text = self._get_ocr_cached_text(file_path, page_num + 1)
                if ocr_text:
                    page_text = ocr_text

            pages.append((page_num + 1, page_text))

        doc.close()
        return pages

    def _get_ocr_cached_text(self, file_path: str, page_number: int):
        """Try to load OCR cached text for a page. Returns None if not cached."""
        try:
            from api.ocr_client import OCRClient
            client = OCRClient()
            if client.has_cached_ocr(file_path):
                return client._get_cached_page(file_path, page_number)
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def delete_all_document_data(self, document_id: str) -> dict:
        """
        Delete all files associated with a document, including:
        - Upload file (PDF/Markdown)
        - Parse results (tree, stats, audit reports, backups)
        - Debug logs

        Args:
            document_id: Document ID

        Returns:
            Dictionary with deletion status
        """
        results = {
            "upload_deleted": False,
            "parse_results_deleted": False,
            "debug_log_deleted": False,
        }

        # Find and delete upload file
        for ext in [".pdf", ".md"]:
            upload_path = self.uploads_dir / f"{document_id}{ext}"
            if upload_path.exists():
                upload_path.unlink()
                results["upload_deleted"] = True
                logger.info(f"Deleted upload file: {upload_path.name}")
                break

        # Delete parse results (tree, stats, audit reports, backups)
        results["parse_results_deleted"] = self.delete_parse_results(document_id)

        # Delete debug log file
        debug_log_path = self.data_dir.parent / "debug_logs" / f"{document_id}.log"
        if debug_log_path.exists():
            debug_log_path.unlink()
            results["debug_log_deleted"] = True
            logger.info(f"Deleted debug log file: {debug_log_path.name}")

        # Delete OCR cache for the document's PDF
        try:
            from api.ocr_client import OCRClient
            for ext in [".pdf"]:
                pdf_path = self.uploads_dir / f"{document_id}{ext}"
                if pdf_path.exists():
                    client = OCRClient()
                    client.clear_cache(str(pdf_path))
                    logger.info(f"Cleared OCR cache for: {pdf_path.name}")
        except Exception:
            pass

        return results
