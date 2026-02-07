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
    title: str = Field(..., description="Section title (original, for search/indexing)")
    level: int = Field(..., description="Nesting level (root=0)")
    content: Optional[str] = Field(None, description="Full text content of the section")
    summary: Optional[str] = Field(None, description="LLM-generated section summary")
    display_title: Optional[str] = Field(None, description="Cleaned title for UI display")
    is_noise: Optional[bool] = Field(None, description="Whether this is an invalid entry (header/footer/metadata)")
    page_start: Optional[int] = Field(None, description="PDF starting page (1-based)")
    page_end: Optional[int] = Field(None, description="PDF ending page (1-based)")
    line_start: Optional[int] = Field(None, description="Markdown starting line (1-based)")
    children: List["TreeNode"] = Field(default_factory=list, description="Child sections")

    class Config:
        # Enable forward references for recursive model
        json_schema_extra = {
            "example": {
                "id": "1",
                "title": "1 / 前言",
                "level": 1,
                "display_title": "前言",
                "is_noise": False,
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


# =============================================================================
# Audit Models
# =============================================================================

class SuggestionInfo(BaseModel):
    """Model for a single audit suggestion."""
    
    suggestion_id: str = Field(..., description="Unique suggestion ID")
    action: str = Field(..., description="Action type: DELETE, ADD, MODIFY_FORMAT, MODIFY_PAGE")
    node_id: Optional[str] = Field(None, description="Target node ID (null for ADD actions)")
    status: str = Field(..., description="Status: pending, accepted, rejected, applied")
    confidence: Optional[str] = Field(None, description="Confidence level: high, medium, low")
    reason: Optional[str] = Field(None, description="Explanation for the suggestion")
    current_title: Optional[str] = Field(None, description="Current title (for MODIFY actions)")
    suggested_title: Optional[str] = Field(None, description="Suggested title (for MODIFY/ADD actions)")
    node_info: Optional[Dict[str, Any]] = Field(None, description="Additional context (siblings, parent, etc.)")
    user_action: Optional[str] = Field(None, description="User action: accept or reject")
    user_comment: Optional[str] = Field(None, description="Optional user comment")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO 8601)")
    reviewed_at: Optional[str] = Field(None, description="Review timestamp (ISO 8601)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "suggestion_id": "sugg_001",
                "action": "MODIFY_FORMAT",
                "node_id": "0014",
                "status": "pending",
                "confidence": "high",
                "reason": "同级标题格式不一致，需统一为（X）格式",
                "current_title": "1、评审前准备",
                "suggested_title": "（七）评审前准备",
                "node_info": {"siblings_count": 9, "siblings_format_distribution": {"（X）": 6, "X、": 3}},
                "user_action": None,
                "user_comment": None
            }
        }


class ConflictInfo(BaseModel):
    """Model for conflicting suggestions."""
    
    node_id: str = Field(..., description="Node ID with conflicts")
    conflicting_suggestions: List[str] = Field(..., description="List of conflicting suggestion IDs")
    recommendation: Optional[str] = Field(None, description="Recommended resolution")


class AuditSummary(BaseModel):
    """Summary statistics for audit report."""
    
    total_nodes: int = Field(..., description="Total nodes in tree")
    suggestions_by_action: Dict[str, int] = Field(..., description="Count by action type")
    suggestions_by_confidence: Dict[str, int] = Field(..., description="Count by confidence level")
    estimated_improvements: Optional[str] = Field(None, description="Expected improvements description")


class AuditReportResponse(BaseModel):
    """Response model for audit report."""
    
    audit_id: str = Field(..., description="Unique audit ID")
    doc_id: str = Field(..., description="Document ID")
    doc_name: Optional[str] = Field(None, description="Document filename")
    document_type: Optional[str] = Field(None, description="Document type (e.g., 招标文件)")
    quality_score: Optional[int] = Field(None, description="Overall quality score (0-100)")
    status: str = Field(..., description="Audit status: pending, applied, rolled_back")
    summary: Optional[AuditSummary] = Field(None, description="Summary statistics")
    suggestions: List[SuggestionInfo] = Field(default_factory=list, description="List of all suggestions")
    conflicts: List[ConflictInfo] = Field(default_factory=list, description="Conflicting suggestions")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO 8601)")
    applied_at: Optional[str] = Field(None, description="Applied timestamp (ISO 8601)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "audit_id": "audit_001",
                "doc_id": "577f7448-4b73-4478-9ee7-c1c9df9963b8",
                "doc_name": "台州第一技师学院车铣复合机床采购.pdf",
                "document_type": "招标文件",
                "quality_score": 85,
                "status": "pending",
                "summary": {
                    "total_nodes": 45,
                    "suggestions_by_action": {"DELETE": 2, "MODIFY_FORMAT": 8, "ADD": 1},
                    "suggestions_by_confidence": {"high": 7, "medium": 3, "low": 1}
                },
                "suggestions": [],
                "conflicts": []
            }
        }


class SuggestionReviewRequest(BaseModel):
    """Request model for reviewing a suggestion."""
    
    action: str = Field(..., description="User action: accept or reject")
    comment: Optional[str] = Field(None, description="Optional user comment")
    
    class Config:
        json_schema_extra = {
            "example": {
                "action": "accept",
                "comment": "这个修改建议很合理"
            }
        }


class SuggestionReviewResponse(BaseModel):
    """Response model for suggestion review."""
    
    suggestion_id: str = Field(..., description="Reviewed suggestion ID")
    status: str = Field(..., description="New status: accepted or rejected")
    message: str = Field(..., description="Status message")


class BatchReviewRequest(BaseModel):
    """Request model for batch reviewing suggestions."""
    
    action: str = Field(..., description="Batch action: accept or reject")
    suggestion_ids: Optional[List[str]] = Field(None, description="Specific suggestion IDs (if not using filters)")
    filters: Optional[Dict[str, str]] = Field(None, description="Filters: action, confidence, etc.")
    comment: Optional[str] = Field(None, description="Optional comment for all")
    
    class Config:
        json_schema_extra = {
            "example": {
                "action": "accept",
                "filters": {"confidence": "high"},
                "comment": "批量接受所有高置信度建议"
            }
        }


class BatchReviewResponse(BaseModel):
    """Response model for batch review."""
    
    updated_count: int = Field(..., description="Number of suggestions updated")
    suggestion_ids: List[str] = Field(..., description="List of updated suggestion IDs")
    message: str = Field(..., description="Status message")


class ApplyRequest(BaseModel):
    """Request model for applying suggestions."""
    
    suggestion_ids: Optional[List[str]] = Field(None, description="Specific suggestions to apply (null = all accepted)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "suggestion_ids": None
            }
        }


class ApplyResponse(BaseModel):
    """Response model for applying suggestions."""
    
    success: bool = Field(..., description="Whether apply was successful")
    applied_count: int = Field(..., description="Number of suggestions applied")
    backup_id: str = Field(..., description="Backup ID for rollback")
    message: str = Field(..., description="Status message")
    warnings: Optional[List[str]] = Field(None, description="Any warnings during apply")


class RollbackRequest(BaseModel):
    """Request model for rollback."""
    
    backup_id: str = Field(..., description="Backup ID to restore")
    
    class Config:
        json_schema_extra = {
            "example": {
                "backup_id": "backup_001"
            }
        }


class RollbackResponse(BaseModel):
    """Response model for rollback."""
    
    success: bool = Field(..., description="Whether rollback was successful")
    message: str = Field(..., description="Status message")


class AuditHistoryItem(BaseModel):
    """Single item in audit history."""
    
    audit_id: str = Field(..., description="Audit ID")
    status: str = Field(..., description="Audit status")
    total_suggestions: int = Field(..., description="Total suggestions")
    created_at: str = Field(..., description="Creation timestamp")
    applied_at: Optional[str] = Field(None, description="Applied timestamp")


class AuditHistoryResponse(BaseModel):
    """Response model for audit history."""
    
    doc_id: str = Field(..., description="Document ID")
    audits: List[AuditHistoryItem] = Field(..., description="List of audits")

