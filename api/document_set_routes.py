"""Document set management routes for cross-document operations."""

import uuid
import json
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.database import get_db, DatabaseManager
from api.models import (
    DocumentSet,
    DocumentSetListResponse,
    CreateDocumentSetRequest,
    UpdateDocumentSetRequest,
    AddDocumentToSetRequest,
    SetPrimaryDocumentRequest,
    DocumentSetQueryRequest,
    DocumentSetQueryResponse,
    QueryResultNode,
    MergedTreeResponse,
    MergedTreeNode,
    DocumentComparisonRequest,
    DocumentComparisonResponse,
    DocumentComparisonSection,
)
from api.storage import StorageService
from api.services import LLMProvider, ChatService

logger = logging.getLogger("pageindex.api.document_sets")

router = APIRouter(prefix="/api/document-sets", tags=["document-sets"])


def get_storage() -> StorageService:
    """Get the storage service instance."""
    return StorageService()


# =============================================================================
# Document Set CRUD Endpoints
# =============================================================================

@router.post("/", response_model=DocumentSet, status_code=201)
async def create_document_set(request: CreateDocumentSetRequest):
    """
    Create a new document set.

    - **name**: Document set name (required)
    - **description**: Optional description
    - **project_id**: Optional associated project ID
    - **primary_doc_id**: Primary document ID (the tender document)
    - **auxiliary_docs**: List of auxiliary documents to add
    """
    db = get_db()

    set_id = str(uuid.uuid4())
    doc_set = db.create_document_set(
        set_id=set_id,
        name=request.name,
        description=request.description,
        project_id=request.project_id,
    )

    logger.info(f"Created document set {set_id}")

    # Handle both camelCase and snake_case field names
    primary_doc_id = request.primary_doc_id or request.primaryDocId
    auxiliary_docs = request.auxiliary_docs or request.auxiliaryDocs

    # Add primary document if provided
    if primary_doc_id:
        try:
            # Get document name from database
            from api.database import DatabaseManager
            db_manager = DatabaseManager()
            doc_info = db_manager.get_document(primary_doc_id)
            # Use title, then filename, then fallback
            doc_name = None
            if doc_info:
                doc_name = doc_info.title or doc_info.filename or None
            if not doc_name:
                doc_name = 'Unknown Document'
            
            doc_set = db.add_document_to_set(
                set_id=set_id,
                document_id=primary_doc_id,
                name=doc_name,
            )
            # Set as primary
            if doc_set:
                items = doc_set.get('items', [])
                if items:
                    items[0]['is_primary'] = True
                    db.update_document_set(set_id, items_json=json.dumps(items))
                    doc_set['items'] = items
        except Exception as e:
            logger.warning(f"Failed to add primary document {primary_doc_id}: {e}")

    # Add auxiliary documents if provided
    if auxiliary_docs:
        for aux_doc in auxiliary_docs:
            try:
                # Handle both camelCase and snake_case
                doc_id = aux_doc.get('doc_id') or aux_doc.get('docId')
                if doc_id:
                    doc_name = aux_doc.get('name') or aux_doc.get('docName', 'Unknown Document')
                    doc_set = db.add_document_to_set(
                        set_id=set_id,
                        document_id=doc_id,
                        name=doc_name,
                    )
            except Exception as e:
                logger.warning(f"Failed to add auxiliary document: {e}")

    # Reload the document set to get updated items
    doc_set = db.get_document_set(set_id)
    
    return DocumentSet(**doc_set)


@router.get("/", response_model=DocumentSetListResponse)
async def list_document_sets(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    limit: int = Query(100, description="Maximum results", ge=1, le=1000),
    offset: int = Query(0, description="Offset for pagination", ge=0),
):
    """
    List all document sets with optional filtering.

    - **project_id**: Optional filter by associated project
    - **limit**: Maximum number of results (default: 100)
    - **offset**: Offset for pagination (default: 0)
    """
    db = get_db()

    sets = db.list_document_sets(project_id=project_id, limit=limit, offset=offset)

    return DocumentSetListResponse(
        items=[DocumentSet(**s) for s in sets],
        count=len(sets),
    )


@router.get("/{set_id}", response_model=DocumentSet)
async def get_document_set(set_id: str):
    """
    Get a document set by ID.

    Includes all documents in the set with their metadata.
    """
    db = get_db()

    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    return DocumentSet(**doc_set)


@router.put("/{set_id}", response_model=DocumentSet)
async def update_document_set(set_id: str, request: UpdateDocumentSetRequest):
    """
    Update a document set.

    - **name**: Optional new name
    - **description**: Optional new description
    """
    db = get_db()

    # Check if set exists
    existing = db.get_document_set(set_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    # Build updates
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return DocumentSet(**existing)

    doc_set = db.update_document_set(
        set_id=set_id,
        name=updates.get("name"),
        description=updates.get("description"),
    )

    logger.info(f"Updated document set {set_id}")
    return DocumentSet(**doc_set)


@router.delete("/{set_id}")
async def delete_document_set(set_id: str):
    """
    Delete a document set.

    **Note**: This only deletes the set metadata. Documents themselves are not deleted.
    """
    db = get_db()

    deleted = db.delete_document_set(set_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    logger.info(f"Deleted document set {set_id}")
    return {"id": set_id, "deleted": True}


# =============================================================================
# Document Management within Sets
# =============================================================================

@router.post("/{set_id}/items", response_model=DocumentSet)
async def add_document_to_set(set_id: str, request: AddDocumentToSetRequest):
    """
    Add a document to a set.

    - **document_id**: Document ID to add (required)
    - **name**: Optional custom display name (defaults to filename)
    """
    db = get_db()
    storage = get_storage()

    # Check if set exists
    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    # Check if document exists
    doc = db.get_document(request.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {request.document_id}")

    # Use custom name or default to filename
    name = request.name or doc.filename

    try:
        updated_set = db.add_document_to_set(
            set_id=set_id,
            document_id=request.document_id,
            name=name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"Added document {request.document_id} to set {set_id}")
    return DocumentSet(**updated_set)


@router.delete("/{set_id}/items/{document_id}", response_model=DocumentSet)
async def remove_document_from_set(set_id: str, document_id: str):
    """
    Remove a document from a set.

    **Note**: This only removes the document from the set. The document itself is not deleted.
    """
    db = get_db()

    # Check if set exists
    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    try:
        updated_set = db.remove_document_from_set(
            set_id=set_id,
            document_id=document_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"Removed document {document_id} from set {set_id}")
    return DocumentSet(**updated_set)


@router.put("/{set_id}/primary", response_model=DocumentSet)
async def set_primary_document(set_id: str, request: SetPrimaryDocumentRequest):
    """
    Set a document as the primary document in a set.

    The primary document is typically the reference document for comparisons.

    - **document_id**: Document ID to set as primary (required)
    """
    db = get_db()

    # Check if set exists
    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    try:
        updated_set = db.set_primary_document(
            set_id=set_id,
            document_id=request.document_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"Set document {request.document_id} as primary in set {set_id}")
    return DocumentSet(**updated_set)


# =============================================================================
# Query and Analysis Endpoints
# =============================================================================

@router.post("/{set_id}/query", response_model=DocumentSetQueryResponse)
async def query_document_set(set_id: str, request: DocumentSetQueryRequest):
    """
    Query across all documents in a set.

    Searches for relevant content across all documents and returns aggregated results.

    - **query**: Search query text (required)
    - **include_summaries**: Whether to include node summaries in search (default: true)
    - **max_results**: Maximum results per document (default: 10)
    """
    db = get_db()
    storage = get_storage()

    # Check if set exists
    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    items = doc_set.get("items", [])
    if not items:
        return DocumentSetQueryResponse(
            query=request.query,
            results=[],
            total_results=0,
            documents_searched=0,
        )

    results = []

    # Search each document in the set
    for item in items:
        doc_id = item.get("document_id")
        doc_name = item.get("name", "Unknown")

        # Get document tree
        try:
            tree_data = await storage.load_parse_result(doc_id)
            if not tree_data:
                continue

            # Simple search in tree nodes
            doc_results = _search_tree(
                tree=tree_data,
                query=request.query,
                document_id=doc_id,
                document_name=doc_name,
                include_summaries=request.include_summaries,
                max_results=request.max_results,
            )
            results.extend(doc_results)

        except Exception as e:
            logger.warning(f"Failed to search document {doc_id}: {e}")
            continue

    # Sort by relevance (descending)
    results.sort(key=lambda x: x.relevance, reverse=True)

    return DocumentSetQueryResponse(
        query=request.query,
        results=results,
        total_results=len(results),
        documents_searched=len(items),
    )


# =============================================================================
# Document Set Chat Endpoint (LLM-powered)
# =============================================================================

class DocumentSetChatRequest(BaseModel):
    """Request model for document set chat."""
    question: str = Field(..., description="User's question to answer")
    history: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="Conversation history")


class DocumentSetChatResponse(BaseModel):
    """Response model for document set chat."""
    answer: str
    sources: List[Dict[str, Any]]
    debug: Optional[Dict[str, Any]] = None


@router.post("/{set_id}/chat", response_model=DocumentSetChatResponse)
async def chat_document_set(set_id: str, request: DocumentSetChatRequest):
    """
    Chat with all documents in a set using LLM.

    Uses LLM reasoning to:
    1. Search relevant sections across all documents
    2. Generate an answer based on the found content
    3. Return sources and debug information
    """
    from api.index import llm_provider, storage_service as global_storage_service
    
    if llm_provider is None:
        raise HTTPException(status_code=503, detail="LLM provider not available")

    db = get_db()
    storage = get_storage()

    # Check if set exists
    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    items = doc_set.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="Document set has no documents")

    # Build merged tree from all documents
    merged_tree = {"id": "merged-root", "title": "Merged Documents", "children": []}
    
    # Get PDF paths for each document
    pdf_paths = {}
    for item in items:
        doc_id = item.get("document_id")
        try:
            doc_info = db.get_document(doc_id)
            if doc_info and doc_info.file_type == "pdf":
                pdf_paths[doc_id] = str(global_storage_service.get_upload_path(doc_info.file_path))
        except Exception as e:
            logger.warning(f"Failed to get PDF path for {doc_id}: {e}")

    # Load trees from all documents
    def add_doc_id_to_nodes(node: dict, doc_id: str):
        """Recursively add document_id to each node."""
        node["document_id"] = doc_id
        for child in node.get("children", []):
            add_doc_id_to_nodes(child, doc_id)

    for item in items:
        doc_id = item.get("document_id")
        doc_name = item.get("name", "Unknown")
        
        try:
            tree_data = await storage.load_parse_result(doc_id)
            if tree_data:
                # Add document prefix to tree and add document_id to all nodes
                doc_tree = {
                    "id": f"doc-{doc_id}",
                    "title": f"[{doc_name}]",
                    "document_id": doc_id,
                    "children": tree_data.get("children", []),
                }
                # Add document_id to all children
                for child in doc_tree.get("children", []):
                    add_doc_id_to_nodes(child, doc_id)
                merged_tree["children"].append(doc_tree)
        except Exception as e:
            logger.warning(f"Failed to load tree for {doc_id}: {e}")

    # Create chat service with all document PDFs
    chat_service = ChatService(llm_provider, pdf_file_path=None, storage_service=global_storage_service)
    if pdf_paths:
        chat_service.set_pdf_paths(pdf_paths)

    # Convert history
    history_dict = request.history or []

    # Answer the question
    try:
        result = await chat_service.answer_question(
            question=request.question,
            tree=merged_tree,
            history=history_dict,
            max_source_nodes=8,
            document_id=None,
        )
        
        return DocumentSetChatResponse(
            answer=result.get("answer", ""),
            sources=result.get("sources", []),
            debug=result.get("debug"),
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process chat request: {str(e)}")


def _search_tree(
    tree: Any,
    query: str,
    document_id: str,
    document_name: str,
    include_summaries: bool,
    max_results: int,
) -> List[QueryResultNode]:
    """Recursively search tree nodes for query matches."""
    results = []
    query_lower = query.lower()

    def search_node(node: Dict[str, Any]):
        if len(results) >= max_results:
            return

        title = node.get("title", "")
        summary = node.get("summary", "") if include_summaries else ""

        # Simple relevance scoring
        relevance = 0.0
        if query_lower in title.lower():
            relevance += 0.8
        if include_summaries and query_lower in summary.lower():
            relevance += 0.4

        if relevance > 0:
            results.append(QueryResultNode(
                document_id=document_id,
                document_name=document_name,
                node_id=node.get("id", ""),
                node_title=title,
                node_summary=summary if include_summaries else None,
                relevance=relevance,
                ps=node.get("ps"),
                pe=node.get("pe"),
            ))

        # Search children
        for child in node.get("children", []):
            search_node(child)

    # Handle both single root and multiple roots
    if isinstance(tree, dict):
        search_node(tree)
    elif isinstance(tree, list):
        for root in tree:
            search_node(root)

    return results


@router.get("/{set_id}/merge", response_model=MergedTreeResponse)
async def get_merged_tree(set_id: str):
    """
    Get a merged tree structure of all documents in a set.

    Combines trees from all documents into a single structure with document prefixes.
    """
    db = get_db()
    storage = get_storage()

    # Check if set exists
    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    items = doc_set.get("items", [])
    if not items:
        return MergedTreeResponse(
            set_id=set_id,
            documents=[],
            tree=[],
            total_nodes=0,
        )

    merged_nodes = []
    documents = []
    total_nodes = 0

    for item in items:
        doc_id = item.get("document_id")
        doc_name = item.get("name", "Unknown")
        is_primary = item.get("is_primary", False)

        documents.append({
            "document_id": doc_id,
            "name": doc_name,
            "is_primary": is_primary,
        })

        # Load document tree
        try:
            tree_data = await storage.load_parse_result(doc_id)
            if not tree_data:
                continue

            # Merge tree nodes
            doc_nodes = _merge_tree_nodes(
                tree=tree_data,
                document_id=doc_id,
                document_name=doc_name,
            )
            merged_nodes.extend(doc_nodes)
            total_nodes += _count_nodes(tree_data)

        except Exception as e:
            logger.warning(f"Failed to load tree for document {doc_id}: {e}")
            continue

    return MergedTreeResponse(
        set_id=set_id,
        documents=documents,
        tree=merged_nodes,
        total_nodes=total_nodes,
    )


def _merge_tree_nodes(
    tree: Any,
    document_id: str,
    document_name: str,
) -> List[MergedTreeNode]:
    """Convert tree to merged nodes with document prefixes."""

    def convert_node(node: Dict[str, Any]) -> MergedTreeNode:
        children = [
            convert_node(child)
            for child in node.get("children", [])
        ]

        return MergedTreeNode(
            id=f"{document_id}:{node.get('id', '')}",
            title=node.get("title", ""),
            document_id=document_id,
            document_name=document_name,
            summary=node.get("summary"),
            ps=node.get("ps"),
            pe=node.get("pe"),
            children=children,
        )

    if isinstance(tree, dict):
        return [convert_node(tree)]
    elif isinstance(tree, list):
        return [convert_node(node) for node in tree]
    return []


def _count_nodes(tree: Any) -> int:
    """Count total nodes in a tree."""
    def count_recursive(node: Dict[str, Any]) -> int:
        return 1 + sum(count_recursive(child) for child in node.get("children", []))

    if isinstance(tree, dict):
        return count_recursive(tree)
    elif isinstance(tree, list):
        return sum(count_recursive(node) for node in tree)
    return 0


@router.post("/{set_id}/compare", response_model=DocumentComparisonResponse)
async def compare_documents(set_id: str, request: DocumentComparisonRequest):
    """
    Compare two documents in a set.

    Analyzes similarities and differences between two documents.

    - **doc1_id**: First document ID (required)
    - **doc2_id**: Second document ID (required)
    - **focus_areas**: Optional focus areas for comparison
    """
    db = get_db()
    storage = get_storage()

    # Check if set exists
    doc_set = db.get_document_set(set_id)
    if not doc_set:
        raise HTTPException(status_code=404, detail=f"Document set not found: {set_id}")

    items = doc_set.get("items", [])
    item_ids = {item.get("document_id"): item for item in items}

    # Verify both documents are in the set
    if request.doc1_id not in item_ids:
        raise HTTPException(status_code=404, detail=f"Document {request.doc1_id} not found in set")
    if request.doc2_id not in item_ids:
        raise HTTPException(status_code=404, detail=f"Document {request.doc2_id} not found in set")

    doc1_name = item_ids[request.doc1_id].get("name", "Unknown")
    doc2_name = item_ids[request.doc2_id].get("name", "Unknown")

    # Load both document trees
    try:
        tree1 = await storage.load_parse_result(request.doc1_id)
        tree2 = await storage.load_parse_result(request.doc2_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load document trees: {e}")

    if not tree1 or not tree2:
        raise HTTPException(status_code=400, detail="One or both documents have not been parsed yet")

    # Perform comparison
    sections = _compare_trees(tree1, tree2, request.focus_areas or [])

    # Calculate overall similarity
    similarities = [s.similarity for s in sections if s.similarity is not None]
    overall_similarity = sum(similarities) / len(similarities) if similarities else None

    # Generate summary
    summary = _generate_comparison_summary(
        doc1_name=doc1_name,
        doc2_name=doc2_name,
        sections=sections,
        overall_similarity=overall_similarity,
    )

    return DocumentComparisonResponse(
        set_id=set_id,
        doc1_id=request.doc1_id,
        doc2_id=request.doc2_id,
        doc1_name=doc1_name,
        doc2_name=doc2_name,
        overall_similarity=overall_similarity,
        sections=sections,
        summary=summary,
    )


def _compare_trees(
    tree1: Any,
    tree2: Any,
    focus_areas: List[str],
) -> List[DocumentComparisonSection]:
    """Compare two document trees and identify comparable sections."""
    sections = []

    # Flatten trees to node lists
    nodes1 = _flatten_tree(tree1)
    nodes2 = _flatten_tree(tree2)

    # Find comparable sections by title similarity
    for node1 in nodes1:
        title1 = node1.get("title", "")

        # Find best match in tree2
        best_match = None
        best_similarity = 0.0

        for node2 in nodes2:
            title2 = node2.get("title", "")
            similarity = _calculate_title_similarity(title1, title2)

            if similarity > best_similarity and similarity > 0.5:  # Threshold
                best_similarity = similarity
                best_match = node2

        if best_match:
            differences = _find_differences(node1, best_match)

            sections.append(DocumentComparisonSection(
                section_id=f"{node1.get('id')}_{best_match.get('id')}",
                title=title1,
                doc1_node_id=node1.get("id"),
                doc2_node_id=best_match.get("id"),
                doc1_summary=node1.get("summary"),
                doc2_summary=best_match.get("summary"),
                similarity=best_similarity,
                differences=differences if differences else None,
            ))

    return sections


def _flatten_tree(tree: Any) -> List[Dict[str, Any]]:
    """Flatten a tree structure to a list of nodes."""
    nodes = []

    def collect_nodes(node: Dict[str, Any]):
        nodes.append(node)
        for child in node.get("children", []):
            collect_nodes(child)

    if isinstance(tree, dict):
        collect_nodes(tree)
    elif isinstance(tree, list):
        for root in tree:
            collect_nodes(root)

    return nodes


def _calculate_title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity between two titles (simple implementation)."""
    # Normalize titles
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()

    if t1 == t2:
        return 1.0

    # Check for common keywords
    words1 = set(t1.split())
    words2 = set(t2.split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union)


def _find_differences(node1: Dict[str, Any], node2: Dict[str, Any]) -> List[str]:
    """Find differences between two nodes."""
    differences = []

    # Compare summaries
    summary1 = node1.get("summary", "") or ""
    summary2 = node2.get("summary", "") or ""

    if summary1 != summary2:
        if len(summary1) > len(summary2):
            differences.append("文档1的摘要更详细")
        elif len(summary2) > len(summary1):
            differences.append("文档2的摘要更详细")
        else:
            differences.append("摘要内容不同")

    # Compare page ranges
    ps1, pe1 = node1.get("ps"), node1.get("pe")
    ps2, pe2 = node2.get("ps"), node2.get("pe")

    if ps1 is not None and ps2 is not None:
        page_diff = abs(ps1 - ps2)
        if page_diff > 5:
            differences.append(f"起始页码差异较大: {ps1} vs {ps2}")

    return differences


def _generate_comparison_summary(
    doc1_name: str,
    doc2_name: str,
    sections: List[DocumentComparisonSection],
    overall_similarity: Optional[float],
) -> str:
    """Generate a human-readable comparison summary."""
    if not sections:
        return f"未找到{doc1_name}和{doc2_name}之间的可比较章节。"

    summary_parts = [f"对比分析了 {len(sections)} 个章节："]

    # High similarity sections
    high_sim = [s for s in sections if s.similarity and s.similarity > 0.8]
    if high_sim:
        summary_parts.append(f"- {len(high_sim)} 个章节高度相似")

    # Medium similarity sections
    med_sim = [s for s in sections if s.similarity and 0.5 <= s.similarity <= 0.8]
    if med_sim:
        summary_parts.append(f"- {len(med_sim)} 个章节中度相似")

    # Low similarity sections
    low_sim = [s for s in sections if s.similarity and s.similarity < 0.5]
    if low_sim:
        summary_parts.append(f"- {len(low_sim)} 个章节差异较大")

    if overall_similarity is not None:
        sim_pct = overall_similarity * 100
        summary_parts.append(f"\n总体相似度: {sim_pct:.1f}%")

    return "\n".join(summary_parts)
