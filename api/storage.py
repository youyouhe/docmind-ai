"""
File storage service for PageIndex documents.

Handles file upload, download, and deletion operations.
Uses UUID-based naming for safe concurrent access.
"""

import os
import uuid
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

import aiofiles
from fastapi import UploadFile, HTTPException


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
        Delete parse result files for a document.

        Args:
            document_id: Document ID

        Returns:
            True if any files were deleted
        """
        tree_path = self.parsed_dir / f"{document_id}_tree.json"
        stats_path = self.parsed_dir / f"{document_id}_stats.json"

        deleted = False
        if tree_path.exists():
            tree_path.unlink()
            deleted = True
        if stats_path.exists():
            stats_path.unlink()
            deleted = True

        return deleted

    # -------------------------------------------------------------------------
    # File Download
    # -------------------------------------------------------------------------

    def get_upload_path(self, relative_path: str) -> Path:
        """
        Get absolute path for uploaded file.

        Args:
            relative_path: Relative path from data directory

        Returns:
            Absolute file path
        """
        return self.data_dir / relative_path

    def file_exists(self, relative_path: str) -> bool:
        """
        Check if file exists.

        Args:
            relative_path: Relative path from data directory

        Returns:
            True if file exists
        """
        return (self.data_dir / relative_path).exists()

    def get_pdf_pages(self, file_path: str, page_start: int, page_end: int) -> list:
        """
        Extract text content from specific pages of a PDF file.

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
            pages.append((page_num + 1, page_text))

        doc.close()
        return pages

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def delete_all_document_data(self, document_id: str) -> dict:
        """
        Delete all files associated with a document.

        Args:
            document_id: Document ID

        Returns:
            Dictionary with deletion status
        """
        results = {
            "upload_deleted": False,
            "parse_results_deleted": False,
        }

        # Find and delete upload file
        for ext in [".pdf", ".md"]:
            upload_path = self.uploads_dir / f"{document_id}{ext}"
            if upload_path.exists():
                upload_path.unlink()
                results["upload_deleted"] = True
                break

        # Delete parse results
        results["parse_results_deleted"] = self.delete_parse_results(document_id)

        return results
