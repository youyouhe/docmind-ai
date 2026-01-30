"""
Pydantic data models for PageIndex API requests and responses.
"""

from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field


# =============================================================================
# Health Check Models
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Service status (healthy/unhealthy)")
    version: str = Field(..., description="API version")
    provider: str = Field(..., description="Current LLM provider")
    model: str = Field(..., description="Current model name")
    available_providers: List[str] = Field(..., description="List of available LLM providers")


# =============================================================================
# API Info Models
# =============================================================================

class EndpointInfo(BaseModel):
    """API endpoint information."""

    path: str = Field(..., description="Endpoint path")
    method: str = Field(..., description="HTTP method")
    description: str = Field(..., description="Endpoint description")


class APIInfo(BaseModel):
    """API information response."""

    name: str = Field(..., description="API name")
    version: str = Field(..., description="API version")
    description: str = Field(..., description="API description")
    endpoints: List[EndpointInfo] = Field(..., description="Available endpoints")


# =============================================================================
# Tree Node Models
# =============================================================================

class TreeNode(BaseModel):
    """Tree node model representing a section in the document."""

    id: str = Field(..., description="Unique node identifier")
    title: str = Field(..., description="Section title")
    level: int = Field(..., description="Nesting level (root=0)")
    content: Optional[str] = Field(None, description="Full text content of the section")
    summary: Optional[str] = Field(None, description="LLM-generated section summary")
    page_start: Optional[int] = Field(None, description="PDF starting page (1-based)")
    page_end: Optional[int] = Field(None, description="PDF ending page (1-based)")
    line_start: Optional[int] = Field(None, description="Markdown starting line (1-based)")
    children: List["TreeNode"] = Field(default_factory=list, description="Child sections")

    class Config:
        # Enable forward references for recursive model
        json_schema_extra = {
            "example": {
                "id": "0000",
                "title": "Chapter 1: Introduction",
                "level": 0,
                "content": "Full text content...",
                "summary": "Chapter summary...",
                "page_start": 1,
                "page_end": 10,
                "children": []
            }
        }


# =============================================================================
# Tree Statistics Models
# =============================================================================

class TreeStats(BaseModel):
    """Tree statistics model."""

    total_nodes: int = Field(..., description="Total number of nodes in the tree")
    max_depth: int = Field(..., description="Maximum nesting depth")
    total_characters: int = Field(..., description="Total character count")
    total_tokens: int = Field(..., description="Estimated token count")
    has_summaries: bool = Field(..., description="Whether nodes have summaries")
    has_content: bool = Field(..., description="Whether nodes have full content")


# =============================================================================
# Parse Response Models
# =============================================================================

class TreeParseResponse(BaseModel):
    """Response model for document parsing operations."""

    success: bool = Field(..., description="Whether parsing was successful")
    message: str = Field(..., description="Status message")
    tree: Optional[TreeNode] = Field(None, description="Parsed tree structure")
    stats: Optional[TreeStats] = Field(None, description="Tree statistics")


# =============================================================================
# Chat Request Models
# =============================================================================

class ChatMessage(BaseModel):
    """Single message in conversation history."""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")

    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "What is the main topic?"
            }
        }


class ChatRequest(BaseModel):
    """Request model for chat/Q&A operations."""

    question: str = Field(..., description="User question to answer", min_length=1)
    tree: TreeNode = Field(..., description="Document tree to search")
    history: Optional[List[ChatMessage]] = Field(
        default_factory=list,
        description="Conversation history (list of previous messages)"
    )
    document_id: Optional[str] = Field(
        default=None,
        description="Document ID for loading PDF page content dynamically"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "Can you explain more about that?",
                "tree": {
                    "id": "root",
                    "title": "Document",
                    "level": 0,
                    "children": []
                },
                "history": [
                    {"role": "user", "content": "What is the main topic?"},
                    {"role": "assistant", "content": "The main topic is..."}
                ]
            }
        }


# =============================================================================
# Chat Response Models
# =============================================================================

class SourceNode(BaseModel):
    """Source node model for chat responses."""

    id: str = Field(..., description="Node ID")
    title: str = Field(..., description="Node title")
    relevance: float = Field(..., description="Relevance score (0-1)")


class ChatResponse(BaseModel):
    """Response model for chat/Q&A operations."""

    answer: str = Field(..., description="Generated answer")
    sources: List[SourceNode] = Field(default_factory=list, description="Relevant source nodes")
    debug_path: List[str] = Field(default_factory=list, description="Debug search path")
    provider: str = Field(..., description="LLM provider used")
    model: str = Field(..., description="Model used for generation")

    class Config:
        json_schema_extra = {
            "example": {
                "answer": "Based on the document, chapter 3 discusses...",
                "sources": [
                    {"id": "0003", "title": "Chapter 3: Main Topic", "relevance": 0.95}
                ],
                "debug_path": ["0000", "0002", "0003"],
                "provider": "deepseek",
                "model": "deepseek-chat"
            }
        }


# =============================================================================
# Error Response Models
# =============================================================================

class ErrorDetail(BaseModel):
    """Error detail model."""

    field: Optional[str] = Field(None, description="Field that caused the error")
    message: str = Field(..., description="Error message")


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str = Field(..., description="Error type/code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[List[ErrorDetail]] = Field(None, description="Additional error details")


# =============================================================================
# Document Management Models
# =============================================================================

class DocumentUploadResponse(BaseModel):
    """Response model for document upload."""

    id: str = Field(..., description="Document ID (UUID)")
    filename: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="File type (pdf or markdown)")
    file_size_bytes: int = Field(..., description="File size in bytes")
    parse_status: str = Field(..., description="Initial parse status")
    message: str = Field(..., description="Status message")


class DocumentItem(BaseModel):
    """Single document item in list."""

    id: str = Field(..., description="Document ID")
    filename: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="File type (pdf or markdown)")
    file_size_bytes: int = Field(..., description="File size in bytes")
    title: Optional[str] = Field(None, description="Document title")
    description: Optional[str] = Field(None, description="Document description")
    parse_status: str = Field(..., description="Parse status")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: str = Field(..., description="Last update timestamp (ISO 8601)")
    category: Optional[str] = Field(None, description="Document category")
    tags: Optional[List[str]] = Field(None, description="Document tags")


class DocumentListResponse(BaseModel):
    """Response model for document list."""

    items: List[DocumentItem] = Field(..., description="List of documents")
    count: int = Field(..., description="Number of documents in this page")
    limit: int = Field(..., description="Maximum items per page")
    offset: int = Field(..., description="Pagination offset")


class ParseResultInfo(BaseModel):
    """Parse result information."""

    id: str = Field(..., description="Parse result ID")
    document_id: str = Field(..., description="Associated document ID")
    model_used: str = Field(..., description="Model used for parsing")
    parsed_at: str = Field(..., description="Parse timestamp (ISO 8601)")
    parse_duration_ms: Optional[int] = Field(None, description="Parse duration in milliseconds")

    class Config:
        protected_namespaces = ()


class DocumentDetail(BaseModel):
    """Detailed document information."""

    id: str = Field(..., description="Document ID")
    filename: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="File type (pdf or markdown)")
    file_size_bytes: int = Field(..., description="File size in bytes")
    title: Optional[str] = Field(None, description="Document title")
    description: Optional[str] = Field(None, description="Document description")
    parse_status: str = Field(..., description="Parse status")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: str = Field(..., description="Last update timestamp (ISO 8601)")
    parse_result: Optional[ParseResultInfo] = Field(None, description="Parse result info if available")
    performance: Optional[Dict[str, Any]] = Field(None, description="Performance statistics from latest parse")
    category: Optional[str] = Field(None, description="Document category")
    tags: Optional[List[str]] = Field(None, description="Document tags")


class DocumentDeleteResponse(BaseModel):
    """Response model for document deletion."""

    id: str = Field(..., description="Deleted document ID")
    deleted: bool = Field(..., description="Whether deletion was successful")
    files_deleted: dict = Field(..., description="File deletion status details")


# =============================================================================
# Document Categorization Models
# =============================================================================

class DocumentCategorizationResponse(BaseModel):
    """Response model for document categorization."""

    document_id: str = Field(..., description="Document ID")
    category: str = Field(..., description="Document category")
    tags: List[str] = Field(default_factory=list, description="Suggested tags")
    confidence: float = Field(..., description="Classification confidence (0-1)")
    reasoning: str = Field(..., description="LLM reasoning for classification")
    provider: str = Field(..., description="LLM provider used")
    model: str = Field(..., description="Model used")
    message: Optional[str] = Field(None, description="Optional message")
