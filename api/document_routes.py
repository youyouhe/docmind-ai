"""
Document management routes for PageIndex API.

Provides endpoints for:
- Document upload with automatic parsing
- Document listing and filtering
- Document details
- Document deletion
- Manual re-parse
- File download
- Tree structure retrieval
"""

import asyncio
import json
import time
import traceback
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse

# Configure logging
logger = logging.getLogger("pageindex.api.documents")

from api.database import get_db, DatabaseManager
from api.storage import StorageService
from api.services import LLMProvider, ParseService
from api.models import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentDetail,
    DocumentDeleteResponse,
    TreeParseResponse,
    TreeStats,
)


# =============================================================================
# Router Configuration
# =============================================================================

router = APIRouter(
    prefix="/api/documents",
    tags=["documents"],
)

# Global instances (set during app startup)
llm_provider: Optional[LLMProvider] = None
storage_service: Optional[StorageService] = None


def initialize_services(llm: LLMProvider, storage: StorageService):
    """Initialize global service instances."""
    global llm_provider, storage_service
    llm_provider = llm
    storage_service = storage


# =============================================================================
# Helper Functions
# =============================================================================

async def parse_document_background(
    document_id: str,
    file_path: str,
    file_type: str,
    model: str,
    parse_config: dict,
    db: DatabaseManager,
    storage: StorageService,
):
    """
    Background task to parse a document with performance tracking.

    Args:
        document_id: Document ID
        file_path: Absolute path to file
        file_type: 'pdf' or 'markdown'
        model: Model to use for parsing
        parse_config: Parse configuration options
        db: Database manager
        storage: Storage service
    """
    # Import performance monitor
    from pageindex.performance_monitor import reset_monitor, get_monitor

    try:
        # Clear any previous PDF performance data
        ParseService.clear_last_pdf_performance()

        # Update status to processing
        db.update_document_status(document_id, "processing")

        start_time = time.time()

        # Parse the document
        if file_type == "pdf":
            page_index_tree = await ParseService.parse_pdf(
                file_path=file_path,
                model=model,
                toc_check_pages=parse_config.get("toc_check_pages", 20),
                max_pages_per_node=parse_config.get("max_pages_per_node", 10),
                max_tokens_per_node=parse_config.get("max_tokens_per_node", 20000),
                if_add_node_summary=parse_config.get("if_add_node_summary", True),
                if_add_node_id=parse_config.get("if_add_node_id", True),
                if_add_node_text=parse_config.get("if_add_node_text", False),
            )
        else:  # markdown
            # Initialize performance monitor for markdown (which uses LLM calls directly)
            reset_monitor()
            monitor = get_monitor()

            async with monitor.stage("markdown_parsing"):
                page_index_tree = await ParseService.parse_markdown(
                    file_path=file_path,
                    model=model,
                    if_add_node_summary=parse_config.get("if_add_node_summary", True),
                    if_add_node_text=parse_config.get("if_add_node_text", True),
                )

        # Convert to API format
        api_tree = ParseService.convert_page_index_to_api_format(page_index_tree)

        # Calculate statistics
        stats_dict = ParseService.calculate_tree_stats(api_tree)

        # Save parse results
        tree_path, stats_path = storage.save_parse_result(
            document_id=document_id,
            tree_data=api_tree,
            stats_data=stats_dict,
        )

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Get performance statistics
        if file_type == "pdf":
            # PDF: Get performance data from page_index_main
            perf_summary = ParseService.get_last_pdf_performance()
        else:
            # Markdown: Get performance data from monitor
            perf_summary = monitor.get_summary()

        # Create parse result record with performance stats
        db.create_parse_result(
            result_id=document_id,
            document_id=document_id,
            tree_path=tree_path,
            stats_path=stats_path,
            model_used=model,
            parse_duration_ms=duration_ms,
        )

        # Save detailed performance statistics
        db.update_parse_performance_stats(document_id, perf_summary)

        # Log performance summary
        print("\n" + "=" * 50)
        print(f"Parse completed for document: {document_id}")
        print(f"Duration: {duration_ms}ms ({perf_summary.get('total_duration_seconds', 0):.2f}s)")
        print(f"LLM calls: {perf_summary.get('total_llm_calls', 0)}")
        print(f"Tokens: {perf_summary.get('total_input_tokens', 0):,} input, {perf_summary.get('total_output_tokens', 0):,} output")
        print("=" * 50 + "\n")

        # Update document status to completed
        db.update_document_status(document_id, "completed")

    except Exception as e:
        # Update document status to failed
        error_msg = f"Parse failed: {str(e)}"
        db.update_document_status(document_id, "failed", error_message=error_msg)
        traceback.print_exc()


def get_llm_provider() -> LLMProvider:
    """Get the LLM provider instance."""
    if llm_provider is None:
        raise HTTPException(
            status_code=503,
            detail="LLM provider not initialized"
        )
    return llm_provider


def get_storage() -> StorageService:
    """Get the storage service instance."""
    if storage_service is None:
        # Create default instance if not initialized
        return StorageService()
    return storage_service


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(..., description="Document file to upload (PDF or Markdown)"),
    model: Optional[str] = Form(default=None, description="LLM model to use (default: provider's configured model)"),
    # PDF options
    toc_check_pages: int = Form(default=20, description="PDF: Pages to check for TOC", ge=1, le=100),
    max_pages_per_node: int = Form(default=10, description="PDF: Max pages per node", ge=1, le=100),
    max_tokens_per_node: int = Form(default=20000, description="PDF: Max tokens per node", ge=1000, le=100000),
    if_add_node_id: bool = Form(default=True, description="PDF: Add node IDs"),
    # Common options
    if_add_node_summary: bool = Form(default=True, description="Add node summaries"),
    if_add_node_text: bool = Form(default=False, description="Add full text content"),
    auto_parse: bool = Form(default=True, description="Automatically parse after upload"),
):
    """
    Upload a new document.

    The document is saved and automatically parsed in the background.
    Use the GET /api/documents/{id} endpoint to check parse status.

    - **file**: Document file (PDF or Markdown)
    - **model**: LLM model for parsing (default: uses provider's configured model from LLM_MODEL env var)
    - **toc_check_pages**: For PDF - pages to scan for table of contents (default: 20)
    - **max_pages_per_node**: For PDF - maximum pages per tree node (default: 10)
    - **max_tokens_per_node**: For PDF - maximum tokens per node (default: 20000)
    - **if_add_node_id**: For PDF - add sequential node IDs (default: true)
    - **if_add_node_summary**: Add LLM-generated summaries (default: true)
    - **if_add_node_text**: Include full text content (default: false)
    - **auto_parse**: Automatically start parsing after upload (default: true)
    """
    llm = get_llm_provider()
    storage = get_storage()
    db = get_db()

    # Use provider's configured model if not specified
    model = model or llm.model

    # Validate and save file
    document_id, relative_path, file_size = await storage.save_upload(file)

    # Detect file type
    file_type = storage.detect_file_type(file.filename or "")

    # Build parse config
    parse_config = {
        "model": model,
        "toc_check_pages": toc_check_pages,
        "max_pages_per_node": max_pages_per_node,
        "max_tokens_per_node": max_tokens_per_node,
        "if_add_node_id": if_add_node_id,
        "if_add_node_summary": if_add_node_summary,
        "if_add_node_text": if_add_node_text,
    }

    # Create document record
    db.create_document(
        document_id=document_id,
        filename=file.filename or "unknown",
        file_type=file_type,
        file_path=relative_path,
        file_size_bytes=file_size,
        parse_config=json.dumps(parse_config),
    )

    # Start background parsing if requested
    if auto_parse:
        absolute_path = storage.get_upload_path(relative_path)
        # Run parsing in background
        asyncio.create_task(
            parse_document_background(
                document_id=document_id,
                file_path=str(absolute_path),
                file_type=file_type,
                model=model,
                parse_config=parse_config,
                db=db,
                storage=storage,
            )
        )

    return DocumentUploadResponse(
        id=document_id,
        filename=file.filename or "unknown",
        file_type=file_type,
        file_size_bytes=file_size,
        parse_status="pending" if auto_parse else "pending",
        message="Document uploaded successfully. Parsing will begin shortly." if auto_parse else "Document uploaded. Use the parse endpoint to start parsing.",
    )


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    file_type: Optional[str] = Query(None, description="Filter by file type (pdf/markdown)"),
    parse_status: Optional[str] = Query(None, description="Filter by parse status (pending/processing/completed/failed)"),
    limit: int = Query(100, description="Maximum results", ge=1, le=1000),
    offset: int = Query(0, description="Offset for pagination", ge=0),
):
    """
    List all documents with optional filtering.

    - **file_type**: Filter by file type ('pdf' or 'markdown')
    - **parse_status**: Filter by parse status ('pending', 'processing', 'completed', 'failed')
    - **limit**: Maximum number of results (default: 100)
    - **offset**: Offset for pagination (default: 0)
    """
    logger.info(f"=== list_documents called ===")
    logger.info(f"Filters: file_type={file_type}, parse_status={parse_status}")
    logger.info(f"Pagination: limit={limit}, offset={offset}")

    db = get_db()

    # Debug: Check database file exists
    logger.info(f"Database path: {db.db_path}")
    from pathlib import Path
    db_file = Path(db.db_path)
    logger.info(f"Database file exists: {db_file.exists()}")
    if db_file.exists():
        logger.info(f"Database file size: {db_file.stat().st_size} bytes")

    # Validate filters
    if file_type and file_type not in ("pdf", "markdown"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file_type: {file_type}. Use 'pdf' or 'markdown'."
        )

    if parse_status and parse_status not in ("pending", "processing", "completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parse_status: {parse_status}. Use 'pending', 'processing', 'completed', or 'failed'."
        )

    # Get documents
    documents = db.list_documents(
        file_type=file_type,
        parse_status=parse_status,
        limit=limit,
        offset=offset,
    )

    logger.info(f"Found {len(documents)} documents in database")

    # Convert to response format
    items = [doc.to_dict() for doc in documents]

    logger.info(f"Returning {len(items)} items")
    logger.info(f"==========================")

    return DocumentListResponse(
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str):
    """
    Get document details by ID.

    Includes parse status, result information, and performance statistics if available.
    """
    db = get_db()

    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Get parse result if available
    parse_result = db.get_parse_result(document_id)

    # Build response
    response_data = doc.to_dict()
    if parse_result:
        response_data["parse_result"] = parse_result.to_dict()

        # Add performance statistics if available
        if parse_result.performance_stats:
            import json
            try:
                perf_stats = json.loads(parse_result.performance_stats)
                response_data["performance"] = perf_stats
            except json.JSONDecodeError:
                response_data["performance"] = {"error": "Failed to parse performance stats"}
        else:
            response_data["performance"] = None

    return DocumentDetail(**response_data)


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(document_id: str):
    """
    Delete a document and all associated data.

    This will:
    - Delete the uploaded file
    - Delete parse result files
    - Remove database records

    **This action cannot be undone.**
    """
    storage = get_storage()
    db = get_db()

    # Check if document exists
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Delete files
    deletion_results = storage.delete_all_document_data(document_id)

    # Delete database record (will cascade to parse_results)
    deleted = db.delete_document(document_id)

    return DocumentDeleteResponse(
        id=document_id,
        deleted=deleted,
        files_deleted=deletion_results,
    )


@router.post("/{document_id}/parse", response_model=TreeParseResponse)
async def reparse_document(
    document_id: str,
    model: str = Form(default=None, description="Override model (optional)"),
):
    """
    Manually trigger re-parsing of a document.

    Useful for:
    - Re-parsing failed documents
    - Re-parsing with different settings (not yet supported)
    - Refreshing parse results

    The parsing happens synchronously - this endpoint will wait
    for parsing to complete.
    """
    llm = get_llm_provider()
    storage = get_storage()
    db = get_db()

    # Get document
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Check if file exists
    if not storage.file_exists(doc.file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Uploaded file not found: {doc.file_path}"
        )

    # Get parse config
    parse_config = json.loads(doc.parse_config) if doc.parse_config else {}
    model_override = model or parse_config.get("model", llm.model)

    # Get absolute file path
    file_path = str(storage.get_upload_path(doc.file_path))

    # Update status to processing
    db.update_document_status(document_id, "processing")

    try:
        start_time = time.time()

        # Parse the document
        if doc.file_type == "pdf":
            page_index_tree = await ParseService.parse_pdf(
                file_path=file_path,
                model=model_override,
                toc_check_pages=parse_config.get("toc_check_pages", 20),
                max_pages_per_node=parse_config.get("max_pages_per_node", 10),
                max_tokens_per_node=parse_config.get("max_tokens_per_node", 20000),
                if_add_node_summary=parse_config.get("if_add_node_summary", True),
                if_add_node_id=parse_config.get("if_add_node_id", True),
                if_add_node_text=parse_config.get("if_add_node_text", False),
            )
        else:  # markdown
            page_index_tree = await ParseService.parse_markdown(
                file_path=file_path,
                model=model_override,
                if_add_node_summary=parse_config.get("if_add_node_summary", True),
                if_add_node_text=parse_config.get("if_add_node_text", True),
            )

        # Convert to API format
        api_tree = ParseService.convert_page_index_to_api_format(page_index_tree)

        # Calculate statistics
        stats_dict = ParseService.calculate_tree_stats(api_tree)
        stats = TreeStats(**stats_dict)

        # Save parse results
        tree_path, stats_path = storage.save_parse_result(
            document_id=document_id,
            tree_data=api_tree,
            stats_data=stats_dict,
        )

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Create or update parse result record
        existing = db.get_parse_result(document_id)
        if existing:
            db.delete_parse_results(document_id)

        db.create_parse_result(
            result_id=document_id,
            document_id=document_id,
            tree_path=tree_path,
            stats_path=stats_path,
            model_used=model_override,
            parse_duration_ms=duration_ms,
        )

        # Update document status
        db.update_document_status(document_id, "completed")

        return TreeParseResponse(
            success=True,
            message=f"Successfully re-parsed document: {doc.filename}",
            tree=api_tree,
            stats=stats,
        )

    except Exception as e:
        traceback.print_exc()
        db.update_document_status(document_id, "failed", error_message=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse document: {str(e)}"
        )


@router.get("/{document_id}/download")
async def download_document(document_id: str):
    """
    Download the original uploaded file.

    Returns the file as a download attachment.
    """
    storage = get_storage()
    db = get_db()

    # Get document
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Check if file exists
    if not storage.file_exists(doc.file_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {doc.file_path}"
        )

    # Get absolute path
    file_path = storage.get_upload_path(doc.file_path)

    # Determine media type
    media_type = "application/pdf" if doc.file_type == "pdf" else "text/markdown"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=doc.filename,
    )


@router.get("/{document_id}/tree")
async def get_document_tree(document_id: str):
    """
    Get the parsed tree structure for a document.

    Returns the tree structure if the document has been parsed.
    """
    storage = get_storage()
    db = get_db()

    # Get document
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Check parse status
    if doc.parse_status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Document not parsed yet. Current status: {doc.parse_status}"
        )

    # Get parse result
    parse_result = db.get_parse_result(document_id)
    if parse_result is None:
        raise HTTPException(
            status_code=404,
            detail="Parse result not found"
        )

    # Load tree data
    tree_data = await storage.load_parse_result(document_id)
    if tree_data is None:
        raise HTTPException(
            status_code=404,
            detail="Tree data file not found"
        )

    return tree_data


@router.get("/{document_id}/stats")
async def get_document_stats(document_id: str):
    """
    Get parse statistics for a document.

    Returns statistics including node count, depth, tokens, etc.
    """
    storage = get_storage()
    db = get_db()

    # Get document
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Check parse status
    if doc.parse_status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Document not parsed yet. Current status: {doc.parse_status}"
        )

    # Load stats
    stats_data = await storage.load_stats(document_id)
    if stats_data is None:
        raise HTTPException(
            status_code=404,
            detail="Statistics not found"
        )

    return stats_data
