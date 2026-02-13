"""
PageIndex FastAPI Main Application

A vectorless, reasoning-based RAG system API that builds hierarchical
tree structures from long documents (PDFs and Markdown) and uses
LLM reasoning for human-like document retrieval.
"""

import os
import tempfile
import traceback
import logging
from typing import Optional, Literal
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pageindex.api")

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Load .env from the same directory as this script
    env_path = Path(__file__).resolve().parent.parent / ".env"
    logger.info(f"Loading .env from: {env_path}")
    logger.info(f".env exists: {env_path.exists()}")
    loaded = load_dotenv(env_path)
    logger.info(f"load_dotenv returned: {loaded}")
    if loaded:
        import os
        # Check the API key for the configured provider
        provider = os.getenv("LLM_PROVIDER", "deepseek")
        model = os.getenv("LLM_MODEL", "")
        key_env = f"{provider.upper()}_API_KEY"
        api_key = os.getenv(key_env, "")
        key_preview = api_key[:8] + "***" if api_key else "NOT FOUND"
        model_info = f", LLM_MODEL={model}" if model else ""
        logger.info(f"LLM_PROVIDER={provider}, {key_env}: {key_preview}{model_info}")
    else:
        logger.warning(f"No .env file loaded from {env_path}")
except ImportError:
    # python-dotenv not available, will use system environment variables
    logger.warning("python-dotenv not available, using system environment variables")

from api.models import (
    HealthResponse,
    APIInfo,
    EndpointInfo,
    TreeParseResponse,
    TreeStats,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
)
from api.services import (
    LLMProvider,
    ParseService,
    ChatService,
)
from api.database import init_database, get_db
from api.storage import StorageService
from api.document_routes import router as document_router, initialize_services
from api.audit_routes import router as audit_router
from api.timeline_routes import router as timeline_router
from api.ocr_routes import router as ocr_router
from api.document_set_routes import router as document_set_router

# Initialize global storage service
storage_service = StorageService()
from api.websocket_routes import router as websocket_router

# Import bid writing extension
try:
    from bid import bid_router
    BID_EXTENSION_AVAILABLE = True
except ImportError:
    BID_EXTENSION_AVAILABLE = False


# =============================================================================
# Configuration
# =============================================================================

# Get configuration from environment
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_API_KEY = os.getenv(f"{LLM_PROVIDER.upper()}_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", None)

# Debug logging
logger.info(f"Config: LLM_PROVIDER={LLM_PROVIDER}, LLM_MODEL={repr(LLM_MODEL)}")

# Create LLM provider instance
try:
    llm_provider = LLMProvider(provider=LLM_PROVIDER, api_key=LLM_API_KEY, model=LLM_MODEL)
    logger.info(f"LLMProvider initialized: provider={llm_provider.provider}, model={llm_provider.model}")
except ValueError as e:
    # If provider initialization fails, we'll handle it in endpoints
    llm_provider = None
    provider_error = str(e)


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="PageIndex API",
    description="Vectorless, reasoning-based RAG system for document analysis",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# =============================================================================
# Startup Event
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database and services on startup."""
    # Initialize database
    init_database()

    # Initialize document routes with services
    if llm_provider is not None:
        initialize_services(llm_provider, storage_service)


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown."""
    logger.info("Shutting down server...")
    # Close any open connections or release resources here
    # This ensures clean exit when Ctrl+C is pressed

# =============================================================================
# Request Debugging Middleware
# =============================================================================

class RequestDebugMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log request details for debugging.
    """

    async def dispatch(self, request: Request, call_next):
        # Simplified logging - only essential info
        path = request.url.path
        # Skip logging for health checks and频繁的轮询
        if path not in ['/health', '/api/health']:
            method = request.method
            # For POST requests, show简要信息
            if method == 'POST' and 'upload' in path:
                logger.info(f"{method} {path} (file upload)")
            elif method == 'GET' and '/api/documents/' in path:
                # 只显示文档ID，不显示完整URL
                parts = path.split('/')
                if len(parts) > 3:
                    doc_id = parts[3][:8] + '...'  # 只显示前8个字符
                    logger.info(f"{method} /api/documents/{doc_id}")
                else:
                    logger.info(f"{method} {path}")
            else:
                logger.info(f"{method} {path}")

        # Process request
        response = await call_next(request)

        return response


# CORS middleware
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _allowed_origins.split(",") if o.strip()] if _allowed_origins else ["*"]
logger.info(f"CORS allowed origins: {_cors_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request debugging middleware (add after CORS)
app.add_middleware(RequestDebugMiddleware)

# Include document management router
app.include_router(document_router)

# Include audit management router
app.include_router(audit_router)

# Include WebSocket router for real-time status updates
app.include_router(websocket_router)

# Include timeline management router
app.include_router(timeline_router)

# Include OCR extraction router
app.include_router(ocr_router)

# Include document set management router
app.include_router(document_set_router)

# Include bid writing extension (if available)
if BID_EXTENSION_AVAILABLE:
    app.include_router(bid_router)


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.status_code,
            "message": exc.detail,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": str(exc),
        },
    )


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/", response_model=APIInfo)
async def root() -> APIInfo:
    """
    Get API information and available endpoints.

    Returns the API name, version, description, and list of available endpoints.
    """
    return APIInfo(
        name="PageIndex API",
        version="0.2.0",
        description="Vectorless, reasoning-based RAG system for document analysis and bid writing",
        endpoints=[
            EndpointInfo(path="/health", method="GET", description="Health check"),
            EndpointInfo(path="/api/parse/markdown", method="POST", description="Parse Markdown document"),
            EndpointInfo(path="/api/parse/pdf", method="POST", description="Parse PDF document"),
            EndpointInfo(path="/api/chat", method="POST", description="Q&A with document"),
            EndpointInfo(path="/api/documents/upload", method="POST", description="Upload new document"),
            EndpointInfo(path="/api/documents/", method="GET", description="List all documents"),
            EndpointInfo(path="/api/documents/{id}", method="GET", description="Get document details"),
            EndpointInfo(path="/api/documents/{id}", method="DELETE", description="Delete document"),
            EndpointInfo(path="/api/documents/{id}/parse", method="POST", description="Re-parse document"),
            EndpointInfo(path="/api/documents/{id}/download", method="GET", description="Download original file"),
            EndpointInfo(path="/api/documents/{id}/tree", method="GET", description="Get parsed tree structure"),
            EndpointInfo(path="/api/documents/{id}/audit", method="GET", description="Get audit report with suggestions"),
            EndpointInfo(path="/api/documents/{id}/audit/suggestions/{sid}/review", method="POST", description="Review suggestion"),
            EndpointInfo(path="/api/documents/{id}/audit/apply", method="POST", description="Apply accepted suggestions"),
            EndpointInfo(path="/api/documents/{id}/audit/rollback", method="POST", description="Rollback to backup"),
        ] + ([
            EndpointInfo(path="/api/bid/projects", method="POST", description="Create bid writing project"),
            EndpointInfo(path="/api/bid/projects", method="GET", description="List all bid projects"),
            EndpointInfo(path="/api/bid/projects/{id}", method="GET", description="Get bid project details"),
            EndpointInfo(path="/api/bid/projects/{id}", method="PUT", description="Update bid project"),
            EndpointInfo(path="/api/bid/projects/{id}", method="DELETE", description="Delete bid project"),
            EndpointInfo(path="/api/bid/projects/{id}/sections/{sid}/auto-save", method="POST", description="Auto-save section"),
            EndpointInfo(path="/api/bid/content/generate", method="POST", description="AI generate bid content"),
            EndpointInfo(path="/api/bid/content/rewrite", method="POST", description="AI rewrite text"),
        ] if BID_EXTENSION_AVAILABLE else []),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Health check endpoint.

    Returns service status, version, current provider/model, and available providers.
    Returns unhealthy if no API key is configured for the current provider.
    """
    logger.info(f"/health called: llm_provider.model={llm_provider.model if llm_provider else None}")

    if llm_provider is None:
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider initialization failed: {provider_error}"
        )

    # Verify that the provider's API key is actually configured
    if not llm_provider.api_key:
        return HealthResponse(
            status="unhealthy",
            version="0.2.0",
            provider=llm_provider.provider,
            model=llm_provider.model,
            available_providers=LLMProvider.SUPPORTED_PROVIDERS,
        )

    return HealthResponse(
        status="healthy",
        version="0.2.0",
        provider=llm_provider.provider,
        model=llm_provider.model,
        available_providers=LLMProvider.SUPPORTED_PROVIDERS,
    )


@app.get("/api/provider-health")
async def provider_health(provider: str = None) -> dict:
    """
    Provider health check endpoint.

    Returns health status for a specific provider or all providers.
    Used by frontend to check which providers are configured and available.
    """
    from pageindex.utils import PROVIDER_CONFIG
    import os

    # Handle "google" as an alias for "gemini"
    provider_alias_map = {
        "google": "gemini",
    }

    # Get the actual model from environment or current provider
    def get_actual_model(target_provider: str) -> str:
        # If this is the current active provider, use its model
        if llm_provider and llm_provider.provider == target_provider:
            return llm_provider.model

        # Check LLM_MODEL environment variable
        llm_model = os.getenv("LLM_MODEL", "")
        if llm_model:
            # For openrouter: any model with "/" uses openrouter
            if target_provider == "openrouter" and "/" in llm_model:
                return llm_model
            # For other providers: check if model name contains provider name
            if target_provider in llm_model.lower():
                return llm_model

        # Fall back to default model from config
        return PROVIDER_CONFIG[target_provider]["default_model"]

    if provider:
        # Normalize provider name using alias map
        provider = provider_alias_map.get(provider, provider)

        # Check specific provider
        if provider not in PROVIDER_CONFIG:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown provider: {provider}. Use one of: {list(PROVIDER_CONFIG.keys())}"
            )

        config = PROVIDER_CONFIG[provider]
        api_key = os.getenv(config["api_key_env"])
        is_configured = bool(api_key)

        return {
            "provider": provider,
            "configured": is_configured,
            "default_model": get_actual_model(provider),
            "base_url": config["base_url"],
        }
    else:
        # Return all providers
        providers_info = {}
        for prov_name, prov_config in PROVIDER_CONFIG.items():
            api_key = os.getenv(prov_config["api_key_env"])
            providers_info[prov_name] = {
                "configured": bool(api_key),
                "default_model": get_actual_model(prov_name),
                "base_url": prov_config["base_url"],
            }

        return providers_info


@app.get("/api/performance/stats")
async def get_performance_stats():
    """
    Get performance statistics from the last document parsing.

    Returns detailed metrics about LLM calls, timing, and resource usage.
    Note: Stats are reset after each parsing operation.
    """
    from pageindex.performance_monitor import get_monitor

    monitor = get_monitor()
    summary = monitor.get_summary()

    # Add formatted output for readability
    summary["formatted"] = {
        "total_duration": f"{summary['total_duration_seconds']:.2f}s",
        "llm_duration": f"{summary['llm_total_duration']:.2f}s",
        "total_calls": summary['total_llm_calls'],
        "input_tokens": f"{summary['total_input_tokens']:,}",
        "output_tokens": f"{summary['total_output_tokens']:,}"
    }

    return summary


@app.post("/api/parse/markdown", response_model=TreeParseResponse)
async def parse_markdown(
    file: UploadFile = File(..., description="Markdown file to parse"),
    model: Optional[str] = Form(default=None, description="LLM model to use (defaults to provider's default model)"),
    if_add_node_summary: bool = Form(default=True, description="Add node summaries"),
    if_add_node_text: bool = Form(default=True, description="Add full text content"),
) -> TreeParseResponse:
    """
    Parse a Markdown document into a hierarchical tree structure.

    The document is parsed using header levels (#, ##, ###) to determine
    the hierarchy. Optionally generates summaries using LLM.

    **NOTE**: This is a one-shot parsing endpoint that does NOT persist
    the document or results to the database. Use /api/documents/upload
    for persistent document storage.

    - **file**: Markdown file to parse (required)
    - **model**: LLM model for summary generation (default: gpt-4o-2024-11-20)
    - **if_add_node_summary**: Whether to add LLM-generated summaries (default: true)
    - **if_add_node_text**: Whether to include full text content (default: true)
    """
    logger.info(f"=== parse_markdown called (one-shot, non-persistent) ===")
    logger.info(f"File: {file.filename}, Model: {model}")

    if llm_provider is None:
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider not available: {provider_error}"
        )

    # Validate file type
    if not file.filename.lower().endswith((".md", ".markdown")):
        raise HTTPException(
            status_code=400,
            detail="File must be a Markdown file (.md or .markdown)"
        )

    # Save uploaded file to temporary location
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".md") as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        logger.info(f"Saved to temp file: {temp_file_path}, size: {len(content)} bytes")

        # Parse the markdown file
        page_index_tree = await ParseService.parse_markdown(
            file_path=temp_file_path,
            model=model if model is not None else llm_provider.model,
            if_add_node_summary=if_add_node_summary,
            if_add_node_text=if_add_node_text,
            llm_provider=llm_provider,
        )

        # Convert to API format (use original filename as root title)
        import os as _os
        md_doc_title = _os.path.splitext(file.filename)[0] if file.filename else None
        api_tree = ParseService.convert_page_index_to_api_format(page_index_tree, doc_title=md_doc_title)

        # Calculate statistics
        stats_dict = ParseService.calculate_tree_stats(api_tree)
        stats = TreeStats(**stats_dict)

        logger.info(f"Parse successful. Nodes: {stats.total_nodes}, Depth: {stats.max_depth}")
        logger.info("=== parse_markdown completed (not saved to database) ===")

        return TreeParseResponse(
            success=True,
            message=f"Successfully parsed Markdown file: {file.filename}",
            tree=api_tree,
            stats=stats,
        )

    except Exception as e:
        logger.error(f"Parse failed: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse Markdown file: {str(e)}"
        )
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file.name):
            try:
                os.unlink(temp_file.name)
                logger.info(f"Cleaned up temp file: {temp_file.name}")
            except Exception:
                pass


@app.post("/api/parse/pdf", response_model=TreeParseResponse)
async def parse_pdf(
    file: UploadFile = File(..., description="PDF file to parse"),
    model: Optional[str] = Form(default=None, description="LLM model to use (defaults to provider's default model)"),
    toc_check_pages: int = Form(default=20, description="Number of pages to check for TOC", ge=1, le=100),
    max_pages_per_node: int = Form(default=10, description="Maximum pages per node", ge=1, le=100),
    max_tokens_per_node: int = Form(default=20000, description="Maximum tokens per node", ge=1000, le=100000),
    if_add_node_summary: bool = Form(default=True, description="Add node summaries"),
    if_add_node_id: bool = Form(default=True, description="Add node IDs"),
    if_add_node_text: bool = Form(default=False, description="Add full text content"),
) -> TreeParseResponse:
    """
    Parse a PDF document into a hierarchical tree structure.

    The document is parsed using LLM-based structure detection:
    - TOC detection and extraction
    - Hierarchical section identification
    - Optional summary generation

    - **file**: PDF file to parse (required)
    - **model**: LLM model for parsing and summaries (defaults to provider's configured model)
    - **toc_check_pages**: Pages to scan for table of contents (default: 20)
    - **max_pages_per_node**: Maximum pages per tree node (default: 10)
    - **max_tokens_per_node**: Maximum tokens per tree node (default: 20000)
    - **if_add_node_summary**: Add LLM-generated summaries (default: true)
    - **if_add_node_id**: Add sequential node IDs (default: true)
    - **if_add_node_text**: Include full text content (default: false)

    Note: PDF parsing can be time-consuming for large documents.
    """
    if llm_provider is None:
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider not available: {provider_error}"
        )

    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="File must be a PDF file (.pdf)"
        )

    # Save uploaded file to temporary location
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pdf") as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        # Parse the PDF file
        page_index_tree = await ParseService.parse_pdf(
            file_path=temp_file_path,
            model=model if model is not None else llm_provider.model,
            toc_check_pages=toc_check_pages,
            max_pages_per_node=max_pages_per_node,
            max_tokens_per_node=max_tokens_per_node,
            if_add_node_summary=if_add_node_summary,
            if_add_node_id=if_add_node_id,
            if_add_node_text=if_add_node_text,
            llm_provider=llm_provider,
        )

        # Convert to API format (use original filename as root title)
        import os as _os
        pdf_doc_title = _os.path.splitext(file.filename)[0] if file.filename else None
        api_tree = ParseService.convert_page_index_to_api_format(page_index_tree, doc_title=pdf_doc_title)

        # Calculate statistics
        stats_dict = ParseService.calculate_tree_stats(api_tree)
        stats = TreeStats(**stats_dict)

        return TreeParseResponse(
            success=True,
            message=f"Successfully parsed PDF file: {file.filename}",
            tree=api_tree,
            stats=stats,
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse PDF file: {str(e)}"
        )
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file.name):
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Answer a question based on a document tree.

    Uses LLM reasoning to:
    1. Search the document tree for relevant sections
    2. Generate an answer based on the found content
    3. Return sources and debug information

    - **question**: User's question to answer (required)
    - **tree**: Document tree structure from parse endpoint (required)
    - **history**: Optional conversation history for follow-up questions
    - **document_id**: Optional document ID for loading PDF page content dynamically
    """
    if llm_provider is None:
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider not available: {provider_error}"
        )

    try:
        # Get PDF file path if document_id is provided
        pdf_file_path = None
        if request.document_id:
            db = get_db()
            doc = db.get_document(request.document_id)

            if doc and doc.file_type == "pdf":
                pdf_file_path = str(storage_service.get_upload_path(doc.file_path))

        # Create chat service with PDF access
        chat_service = ChatService(llm_provider, pdf_file_path=pdf_file_path, storage_service=storage_service)

        # Convert Pydantic models to dict for internal processing
        tree_dict = request.tree.model_dump()

        # Convert history to dict format
        history_dict = [msg.model_dump() for msg in (request.history or [])]

        # Answer the question
        result = await chat_service.answer_question(
            question=request.question,
            tree=tree_dict,
            history=history_dict,
            max_source_nodes=8,
            document_id=request.document_id,
        )

        return ChatResponse(**result)

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat request: {str(e)}"
        )


# =============================================================================
# Run Application
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.index:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
