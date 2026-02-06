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
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
from api.websocket_manager import manager

# Import progress callback for real-time updates
try:
    from pageindex.progress_callback import ProgressCallback, set_document_id
except ImportError:
    ProgressCallback = None
    set_document_id = None


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

    # Create async callback for WebSocket updates
    async def ws_callback(doc_id: str, stage: str, progress: float, metadata: dict):
        """Async callback to send WebSocket updates."""
        message = metadata.get("message", f"Processing: {stage}")
        await manager.broadcast_status_update(
            doc_id,
            "processing",
            progress=progress,
            metadata={
                "stage": stage,
                "message": message,
                **metadata
            }
        )

    try:
        # Clear any previous PDF performance data
        ParseService.clear_last_pdf_performance()

        # Update status to processing
        db.update_document_status(document_id, "processing")

        # Broadcast status update via WebSocket
        await manager.broadcast_status_update(document_id, "processing", progress=0.0)

        # Set document_id for progress callbacks
        if set_document_id:
            set_document_id(document_id)

        start_time = time.time()

        # Create progress callback for real-time updates
        progress_callback = None
        if ProgressCallback and file_type == "pdf":
            progress_callback = ProgressCallback(document_id, ws_callback)

        # Parse the document
        if file_type == "pdf":
            # Stage 1: Analyzing document structure
            await manager.broadcast_status_update(
                document_id,
                "processing",
                progress=10.0,
                metadata={"stage": "Analyzing document structure..."}
            )

            page_index_tree = await ParseService.parse_pdf(
                file_path=file_path,
                model=model,
                toc_check_pages=parse_config.get("toc_check_pages", 20),
                max_pages_per_node=parse_config.get("max_pages_per_node", 10),
                max_tokens_per_node=parse_config.get("max_tokens_per_node", 20000),
                if_add_node_summary=parse_config.get("if_add_node_summary", True),
                if_add_node_id=parse_config.get("if_add_node_id", True),
                if_add_node_text=parse_config.get("if_add_node_text", False),
                custom_prompt=parse_config.get("custom_prompt"),
                progress_callback=progress_callback,
            )

            # Stage 2: Building tree structure
            await manager.broadcast_status_update(
                document_id,
                "processing",
                progress=96.0,
                metadata={"stage": "Finalizing tree structure..."}
            )
        else:  # markdown
            # Stage 1: Analyzing markdown structure
            await manager.broadcast_status_update(
                document_id,
                "processing",
                progress=10.0,
                metadata={"stage": "Analyzing markdown structure..."}
            )
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

            # Stage 2: Building tree structure
            await manager.broadcast_status_update(
                document_id,
                "processing",
                progress=60.0,
                metadata={"stage": "Building tree structure..."}
            )

        # Convert to API format
        api_tree = ParseService.convert_page_index_to_api_format(page_index_tree)

        # Stage 3: Tree Quality Audit (if enabled)
        audit_report = None
        if parse_config.get("enable_audit", False) and file_type == "pdf":
            await manager.broadcast_status_update(
                document_id,
                "processing",
                progress=95.0,
                metadata={"stage": "Auditing tree quality..."}
            )
            
            try:
                from pageindex_v2.phases.tree_auditor_v2 import TreeAuditorV2
                from pageindex_v2.core.llm_client import LLMClient
                
                # Create LLM client for auditor
                audit_llm = LLMClient(
                    provider=llm_provider.provider,
                    model=model,
                    api_key=llm_provider.api_key,
                    debug=False
                )
                
                # Create auditor
                auditor = TreeAuditorV2(
                    llm=audit_llm,
                    pdf_path=file_path,
                    mode=parse_config.get("audit_mode", "progressive"),
                    debug=False
                )
                
                # Run audit
                optimized_tree, audit_report = await auditor.audit_and_optimize(
                    tree=page_index_tree,
                    confidence_threshold=parse_config.get("audit_confidence", 0.7)
                )
                
                # Use optimized tree
                api_tree = ParseService.convert_page_index_to_api_format(optimized_tree)
                
                # Log audit summary
                if audit_report:
                    summary = audit_report.get("summary", {})
                    print(f"\n[AUDIT] Quality Score: {summary.get('quality_score', 0):.1f}/100")
                    print(f"[AUDIT] Nodes: {summary.get('original_nodes', 0)} → {summary.get('optimized_nodes', 0)}")
                    print(f"[AUDIT] Changes: {summary.get('changes_applied', {})}\n")
                    
            except Exception as e:
                print(f"[AUDIT] Warning: Audit failed - {e}")
                print("[AUDIT] Continuing with original tree...")
                # Continue with non-audited tree
                audit_report = {"error": str(e)}

        # Stage 4: Saving results
        await manager.broadcast_status_update(
            document_id,
            "processing",
            progress=97.0,
            metadata={"stage": "Saving results..."}
        )

        # Calculate statistics
        stats_dict = ParseService.calculate_tree_stats(api_tree)

        # Save parse results
        tree_path, stats_path = storage.save_parse_result(
            document_id=document_id,
            tree_data=api_tree,
            stats_data=stats_dict,
        )
        
        # Save audit report if available
        if audit_report:
            audit_path = storage.save_audit_report(document_id, audit_report)
            if audit_path:
                print(f"[AUDIT] Report saved: {audit_path}")

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

        # Broadcast completion status via WebSocket
        await manager.broadcast_status_update(
            document_id,
            "completed",
            progress=100.0,
            metadata={"duration_ms": duration_ms}
        )

    except Exception as e:
        # Update document status to failed
        error_msg = f"Parse failed: {str(e)}"
        db.update_document_status(document_id, "failed", error_message=error_msg)
        traceback.print_exc()

        # Broadcast failed status via WebSocket
        await manager.broadcast_status_update(
            document_id,
            "failed",
            error_message=error_msg
        )


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
    # Custom prompt for TOC extraction
    custom_prompt: Optional[str] = Form(default=None, description="Custom prompt to guide TOC extraction (helps LLM better identify document structure)"),
    # Tree Auditor V2 options
    enable_audit: bool = Form(default=False, description="Run intelligent tree auditor after parsing to fix quality issues"),
    audit_mode: str = Form(default="progressive", description="Audit mode: 'progressive' (5-round, recommended) or 'standard' (1-round)"),
    audit_confidence: float = Form(default=0.7, description="Confidence threshold for applying audit suggestions (0.0-1.0)", ge=0.0, le=1.0),
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
    - **enable_audit**: Run intelligent tree quality auditor after parsing (default: false)
    - **audit_mode**: Audit mode - 'progressive' (5-round, recommended) or 'standard' (1-round) (default: progressive)
    - **audit_confidence**: Confidence threshold for applying suggestions, 0.0-1.0 (default: 0.7)
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
        "custom_prompt": custom_prompt,
        # Audit config
        "enable_audit": enable_audit,
        "audit_mode": audit_mode,
        "audit_confidence": audit_confidence,
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
        task = asyncio.create_task(
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
        # Add callback to handle exceptions
        def task_done_callback(task):
            try:
                task.result()
            except Exception as e:
                logger.error(f"Background parsing task failed for document {document_id}: {e}")
                traceback.print_exc()
        
        task.add_done_callback(task_done_callback)

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
    custom_prompt: Optional[str] = Form(default=None, description="Custom prompt to guide TOC extraction"),
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

    # Broadcast status update via WebSocket
    await manager.broadcast_status_update(document_id, "processing")

    # Set document_id for progress callbacks
    if set_document_id:
        set_document_id(document_id)

    # Create progress callback for real-time updates
    progress_callback = None

    # Create async callback for WebSocket updates
    async def ws_callback(doc_id: str, stage: str, progress: float, metadata: dict):
        """Async callback to send WebSocket updates."""
        message = metadata.get("message", f"Processing: {stage}")
        await manager.broadcast_status_update(
            doc_id,
            "processing",
            progress=progress,
            metadata={
                "stage": stage,
                "message": message,
                **metadata
            }
        )

    if ProgressCallback and doc.file_type == "pdf":
        progress_callback = ProgressCallback(document_id, ws_callback)

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
                custom_prompt=custom_prompt,
                progress_callback=progress_callback,
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

        # Broadcast completion status via WebSocket
        await manager.broadcast_status_update(
            document_id,
            "completed",
            progress=100.0,
            metadata={"duration_ms": duration_ms, "is_reparse": True}
        )

        return TreeParseResponse(
            success=True,
            message=f"Successfully re-parsed document: {doc.filename}",
            tree=api_tree,
            stats=stats,
        )

    except Exception as e:
        traceback.print_exc()
        db.update_document_status(document_id, "failed", error_message=str(e))

        # Broadcast failed status via WebSocket
        await manager.broadcast_status_update(
            document_id,
            "failed",
            error_message=str(e)
        )

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


class UpdateNodeTitleRequest(BaseModel):
    """Model for updating a node's title."""
    new_title: str


@router.patch("/{document_id}/nodes/{node_id}/title")
async def update_node_title(
    document_id: str,
    node_id: str,
    request: UpdateNodeTitleRequest
):
    """
    Update the title of a specific node in the document tree.

    This endpoint allows editing of node titles in the parsed tree structure.
    The updated tree is saved back to the storage.

    - **document_id**: Document ID
    - **node_id**: Node ID to update
    - **new_title**: New title for the node

    Returns:
        The updated tree structure
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

    # Load current tree data
    tree_data = await storage.load_parse_result(document_id)
    if tree_data is None:
        raise HTTPException(
            status_code=404,
            detail="Tree data file not found"
        )

    # Helper function to recursively find and update the node
    def update_node_recursive(node: Dict[str, Any], target_id: str, new_title: str) -> bool:
        """
        Recursively search and update the node with target_id.
        Returns True if node was found and updated.
        """
        if node.get("id") == target_id:
            node["title"] = new_title
            return True
        
        # Search in children
        if "children" in node and isinstance(node["children"], list):
            for child in node["children"]:
                if update_node_recursive(child, target_id, new_title):
                    return True
        
        return False

    # Update the node in the tree
    node_found = False
    if isinstance(tree_data, dict):
        # Single root node
        node_found = update_node_recursive(tree_data, node_id, request.new_title)
    elif isinstance(tree_data, list):
        # Multiple root nodes
        for root_node in tree_data:
            if update_node_recursive(root_node, node_id, request.new_title):
                node_found = True
                break

    if not node_found:
        raise HTTPException(
            status_code=404,
            detail=f"Node not found: {node_id}"
        )

    # Save the updated tree back to storage
    try:
        # Get parse result to find tree path
        parse_result = db.get_parse_result(document_id)
        if parse_result is None:
            raise HTTPException(
                status_code=404,
                detail="Parse result not found"
            )

        # Save updated tree (reuse existing paths)
        tree_path, _ = storage.save_parse_result(
            document_id=document_id,
            tree_data=tree_data,
            stats_data=None,  # Don't update stats
        )

        return {
            "success": True,
            "message": f"Node title updated successfully",
            "document_id": document_id,
            "node_id": node_id,
            "new_title": request.new_title,
            "tree": tree_data
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save updated tree: {str(e)}"
        )


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


@router.get("/{document_id}/pages")
async def get_document_pages(
    document_id: str,
    page_start: int = Query(..., ge=1, description="Starting page number (1-based)"),
    page_end: int = Query(..., ge=1, description="Ending page number (1-based, inclusive)")
):
    """
    Get text content from specific pages of a PDF document.

    This endpoint is used by the chat service to dynamically load
    page content instead of storing it in the tree structure.

    - **document_id**: Document ID
    - **page_start**: Starting page number (1-based)
    - **page_end**: Ending page number (1-based, inclusive)

    Returns:
        List of pages with their text content
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

    # Only PDF documents support page extraction
    if doc.file_type != "pdf":
        raise HTTPException(
            status_code=400,
            detail="Page content extraction is only supported for PDF documents"
        )

    # Check if file exists
    if not storage.file_exists(doc.file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Uploaded file not found: {doc.file_path}"
        )

    # Get absolute file path
    file_path = str(storage.get_upload_path(doc.file_path))

    # Extract pages
    try:
        pages = storage.get_pdf_pages(file_path, page_start, page_end)
        return {
            "document_id": document_id,
            "page_start": page_start,
            "page_end": page_end,
            "pages": [{"page_num": p[0], "text": p[1]} for p in pages]
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract pages: {str(e)}"
        )


# =============================================================================
# Conversation History Endpoints
# =============================================================================

class ConversationMessage(BaseModel):
    """Model for a conversation message."""
    id: str
    document_id: str
    role: str  # 'user' or 'assistant'
    content: str
    created_at: str
    sources: Optional[str] = None  # JSON string
    debug_path: Optional[str] = None  # JSON string


class ConversationHistory(BaseModel):
    """Model for conversation history response."""
    document_id: str
    messages: List[ConversationMessage]
    count: int


class SaveConversationRequest(BaseModel):
    """Model for saving a conversation message."""
    role: str  # 'user' or 'assistant'
    content: str
    sources: Optional[List[Dict[str, Any]]] = None
    debug_path: Optional[List[str]] = None


@router.get("/{document_id}/conversations", response_model=ConversationHistory)
async def get_conversation_history(
    document_id: str,
    limit: int = Query(100, description="Maximum number of messages", ge=1, le=1000)
):
    """
    Get conversation history for a document.

    Returns all chat messages associated with the document,
    ordered by creation time (oldest first).

    - **document_id**: Document ID
    - **limit**: Maximum number of messages to return (default: 100)
    """
    db = get_db()

    # Verify document exists
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Get conversation history
    messages = db.get_conversation_history(document_id, limit=limit)

    return ConversationHistory(
        document_id=document_id,
        messages=[
            ConversationMessage(
                id=m.id,
                document_id=m.document_id,
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat() if m.created_at else "",
                sources=m.sources,
                debug_path=m.debug_path,
            )
            for m in messages
        ],
        count=len(messages),
    )


@router.post("/{document_id}/conversations")
async def save_conversation_message(
    document_id: str,
    request: SaveConversationRequest
):
    """
    Save a conversation message for a document.

    This endpoint is called after each user message or AI response
    to maintain conversation history.

    - **document_id**: Document ID
    - **role**: Message role ('user' or 'assistant')
    - **content**: Message content
    - **sources**: Optional source information (for assistant messages)
    - **debug_path**: Optional debug path for highlighting (for assistant messages)
    """
    import uuid
    import json

    db = get_db()

    # Verify document exists
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Validate role
    if request.role not in ("user", "assistant"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role: {request.role}. Use 'user' or 'assistant'."
        )

    # Generate message ID
    message_id = str(uuid.uuid4())

    # Save message
    db.save_conversation_message(
        message_id=message_id,
        document_id=document_id,
        role=request.role,
        content=request.content,
        sources=request.sources,
        debug_path=request.debug_path,
    )

    return {
        "id": message_id,
        "document_id": document_id,
        "role": request.role,
        "created": True
    }


@router.delete("/{document_id}/conversations")
async def delete_conversation_history(document_id: str):
    """
    Delete all conversation history for a document.

    Use this endpoint to clear the chat history for a document.

    **This action cannot be undone.**
    """
    db = get_db()

    # Verify document exists
    doc = db.get_document(document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    # Delete conversation history
    count = db.delete_conversation_history(document_id)

    return {
        "document_id": document_id,
        "deleted": count,
        "message": f"Deleted {count} message(s)"
    }


@router.post("/{document_id}/categorize")
async def categorize_document(
    document_id: str,
    force: bool = False
):
    """
    Analyze document using LLM to determine category and tags.
    Uses only the first page for analysis.

    Query Parameters:
    - force: Re-categorize even if already has category (default: false)
    """
    from api.database import get_db

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

    # Check if already categorized (unless force=True)
    if doc.category and not force:
        import json
        return {
            "document_id": document_id,
            "category": doc.category,
            "tags": json.loads(doc.tags) if doc.tags else [],
            "message": "Already categorized"
        }

    # Check if file exists
    if not storage.file_exists(doc.file_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {doc.file_path}"
        )

    # Get absolute file path
    file_path = str(storage.get_upload_path(doc.file_path))

    # Extract first page content
    try:
        if doc.file_type == "pdf":
            pages = storage.get_pdf_pages(file_path, 1, 1)  # Get page 1 only
            first_page_text = pages[0][1] if pages else ""
        elif doc.file_type == "markdown":
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                first_page_text = content[:3000]  # First ~3000 chars
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {doc.file_type}"
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract first page: {str(e)}"
        )

    # Truncate first page if too long
    first_page_text = first_page_text[:4000]

    # Build categorization prompt
    categorization_prompt = f"""请分析这份文档并确定其分类和标签。

文档名称: {doc.filename}

文档首页内容:
{first_page_text}

请返回JSON格式的分析结果:
{{
    "category": "简短的分类名称（2-6个汉字）",
    "tags": ["标签1", "标签2", "标签3"],
    "confidence": 0.95,
    "reasoning": "分类依据的简要说明"
}}

分类示例:
- 教育类文档: "教育招标" 或 "学术采购", tags: ["教育", "大学", "招标"]
- 政府类文档: "政府采购" 或 "政府公告", tags: ["政府", "采购", "公告"]
- 企业类文档: "企业招标" 或 "商业采购", tags: ["企业", "商业", "采购"]
- 如果无法确定分类: "其他", tags: []

只返回JSON，不要有其他文字。"""

    # Call LLM
    try:
        import json

        response = await llm.chat(categorization_prompt)

        # Parse JSON response
        if "```" in response:
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]

        result = json.loads(response.strip())
        category = result.get("category", "").strip()
        tags = result.get("tags", [])
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "")

        # Validate category
        if not category:
            category = "其他"
        if not isinstance(tags, list):
            tags = []

    except json.JSONDecodeError as e:
        # Fallback if JSON parsing fails
        category = "其他"
        tags = []
        confidence = 0.0
        reasoning = f"JSON解析失败: {str(e)}"
    except Exception as e:
        # Fallback if LLM fails
        category = "其他"
        tags = []
        confidence = 0.0
        reasoning = f"LLM调用失败: {str(e)}"

    # Update document in database
    db.update_document_category_tags(document_id, category=category, tags=tags)

    return {
        "document_id": document_id,
        "category": category,
        "tags": tags,
        "confidence": confidence,
        "reasoning": reasoning,
        "provider": llm.provider,
        "model": llm.model
    }


@router.post("/{document_id}/audit")
async def audit_document_tree(
    document_id: str,
    mode: str = "progressive",  # "progressive" or "standard"
    confidence_threshold: float = 0.7
):
    """
    Run tree quality audit on a document.
    
    This endpoint triggers the TreeAuditorV2 to analyze and optimize
    the document's tree structure. The audit identifies issues like:
    - Redundant nodes
    - Incorrect formatting
    - Missing structure elements
    - Page number errors
    
    Args:
        document_id: Document ID
        mode: Audit mode - "progressive" (5-round, recommended) or "standard" (1-round)
        confidence_threshold: Threshold for applying suggestions (0.0-1.0)
    
    Returns:
        Audit report with suggestions and optimized tree
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
    
    # Check parse status
    if doc.parse_status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Document not parsed yet. Current status: {doc.parse_status}"
        )
    
    # Check if file exists (for PDF verification)
    file_path = None
    if doc.file_type == "pdf" and storage.file_exists(doc.file_path):
        file_path = str(storage.get_upload_path(doc.file_path))
    
    # Load tree data
    tree_data = await storage.load_parse_result(document_id)
    if tree_data is None:
        raise HTTPException(
            status_code=404,
            detail="Tree data file not found"
        )
    
    # Convert tree to PageIndex format if needed
    from api.services import ParseService
    page_index_tree = ParseService.convert_api_to_page_index_format(tree_data)
    
    try:
        # Create LLM client for auditor
        from pageindex_v2.core.llm_client import LLMClient
        from pageindex_v2.phases.tree_auditor_v2 import TreeAuditorV2
        
        audit_llm = LLMClient(
            provider=llm.provider,
            model=llm.model,
            api_key=llm.api_key,
            debug=False
        )
        
        # Create auditor with progress callback
        async def progress_callback(phase, phase_number, total_phases, message, progress, metadata):
            """Send progress updates via WebSocket"""
            await manager.broadcast_audit_progress(
                document_id=document_id,
                phase=phase,
                phase_number=phase_number,
                total_phases=total_phases,
                message=message,
                progress=progress,
                metadata=metadata
            )
        
        auditor = TreeAuditorV2(
            llm=audit_llm,
            pdf_path=file_path,
            mode=mode,
            debug=True,
            progress_callback=progress_callback
        )
        
        # Run audit
        print(f"\n[AUDIT] Starting tree audit for document: {document_id}")
        print(f"[AUDIT] Mode: {mode}, Confidence threshold: {confidence_threshold}")
        
        optimized_tree, audit_report = await auditor.audit_and_optimize(
            tree=page_index_tree,
            confidence_threshold=confidence_threshold
        )
        
        # Convert optimized tree back to API format
        api_tree = ParseService.convert_page_index_to_api_format(optimized_tree)
        
        # Save the audit report
        audit_path = storage.save_audit_report(document_id, audit_report)
        print(f"[AUDIT] Report saved: {audit_path}")
        
        # Get summary
        summary = audit_report.get("summary", {})
        
        # Extract suggestions for frontend
        advice_phase = audit_report.get("phases", {}).get("advice_generation", {})
        advice_list = advice_phase.get("advice", [])
        
        # Generate audit ID
        audit_id = document_id + "_audit_" + str(int(time.time()))
        
        # Create audit report in database
        db.create_audit_report(
            audit_id=audit_id,
            doc_id=document_id,
            document_type=audit_report.get("phases", {}).get("classification", {}).get("type", "Unknown"),
            quality_score=int(summary.get("quality_score", 0)),
            total_suggestions=len(advice_list),
        )
        
        # Format and save suggestions to database
        import uuid
        suggestions = []
        for idx, advice in enumerate(advice_list):
            # Generate unique suggestion ID if not present
            suggestion_id = advice.get("advice_id") or f"sugg_{document_id}_{idx}_{uuid.uuid4().hex[:8]}"
            
            # Prepare suggestion data
            # For ADD actions, extract parent_id and insert_position from advice
            node_info = advice.get("node_info", {})
            if advice.get("action") == "ADD":
                # Build node_info from ADD-specific fields
                if "parent_id" in advice:
                    node_info["parent_id"] = advice["parent_id"]
                if "insert_position" in advice:
                    node_info["insert_position"] = advice["insert_position"]
                if "after_node_id" in advice:
                    node_info["after_node_id"] = advice["after_node_id"]
                if "before_node_id" in advice:
                    node_info["before_node_id"] = advice["before_node_id"]
                if "suggested_level" in advice:
                    node_info["suggested_level"] = advice["suggested_level"]
                if "suggested_pages" in advice:
                    node_info["suggested_pages"] = advice["suggested_pages"]
            
            suggestion_data = {
                "suggestion_id": suggestion_id,
                "action": advice.get("action", ""),
                "node_id": advice.get("node_id", ""),
                "confidence": advice.get("confidence", "medium"),
                "reason": advice.get("reason", ""),
                "current_title": advice.get("current_title", ""),
                "suggested_title": advice.get("new_title") or advice.get("suggested_format") or advice.get("suggested_title", ""),
                "status": "pending",
                "node_info": node_info,
            }
            
            # Save to database
            db.create_audit_suggestion(
                suggestion_id=suggestion_id,
                audit_id=audit_id,
                doc_id=document_id,
                action=suggestion_data["action"],
                node_id=suggestion_data["node_id"],
                confidence=suggestion_data["confidence"],
                reason=suggestion_data["reason"],
                current_title=suggestion_data["current_title"],
                suggested_title=suggestion_data["suggested_title"],
                node_info=suggestion_data["node_info"],
            )
            
            suggestions.append(suggestion_data)
        
        print(f"[AUDIT] Saved {len(suggestions)} suggestions to database")
        
        return {
            "success": True,
            "document_id": document_id,
            "mode": mode,
            "audit_id": audit_id,
            "quality_score": summary.get("quality_score", 0),
            "summary": {
                "original_nodes": summary.get("original_nodes", 0),
                "optimized_nodes": summary.get("optimized_nodes", 0),
                "total_suggestions": len(suggestions),
                "changes_applied": summary.get("changes_applied", {}),
            },
            "suggestions": suggestions,
            "message": f"Audit completed. Found {len(suggestions)} suggestions."
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Audit failed: {str(e)}"
        )

