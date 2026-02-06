"""
API routes for document structure audit operations.

Provides endpoints for:
- Getting audit reports with suggestions
- Reviewing suggestions (accept/reject)
- Applying accepted suggestions to the tree
- Rolling back changes
"""

import os
import json
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from .database import get_db
from .models import (
    AuditReportResponse,
    SuggestionInfo,
    SuggestionReviewRequest,
    SuggestionReviewResponse,
    BatchReviewRequest,
    BatchReviewResponse,
    ApplyRequest,
    ApplyResponse,
    RollbackRequest,
    RollbackResponse,
    AuditHistoryResponse,
    AuditHistoryItem,
    ConflictInfo,
    AuditSummary,
)


router = APIRouter(tags=["audit"])


def get_data_dir() -> Path:
    """Get the data directory path."""
    db = get_db()
    return db.data_dir


def load_audit_report_from_file(doc_id: str) -> Optional[Dict[str, Any]]:
    """Load audit report JSON from filesystem."""
    data_dir = get_data_dir()
    audit_path = data_dir / "parsed" / f"{doc_id}_audit_report.json"
    
    if not audit_path.exists():
        return None
    
    with open(audit_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_tree_from_file(doc_id: str) -> Optional[Dict[str, Any]]:
    """Load tree JSON from filesystem."""
    data_dir = get_data_dir()
    tree_path = data_dir / "parsed" / f"{doc_id}_tree.json"
    
    if not tree_path.exists():
        return None
    
    with open(tree_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tree_to_file(doc_id: str, tree_data: Dict[str, Any]) -> None:
    """Save tree JSON to filesystem."""
    data_dir = get_data_dir()
    tree_path = data_dir / "parsed" / f"{doc_id}_tree.json"
    
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(tree_data, f, ensure_ascii=False, indent=2)


def detect_conflicts(suggestions: List[SuggestionInfo]) -> List[ConflictInfo]:
    """Detect conflicting suggestions on the same node."""
    node_suggestions: Dict[str, List[SuggestionInfo]] = {}
    
    for sugg in suggestions:
        if sugg.node_id and sugg.status == "pending":
            if sugg.node_id not in node_suggestions:
                node_suggestions[sugg.node_id] = []
            node_suggestions[sugg.node_id].append(sugg)
    
    conflicts = []
    for node_id, node_suggs in node_suggestions.items():
        if len(node_suggs) > 1:
            # Check if there are conflicting actions (DELETE vs MODIFY)
            actions = [s.action for s in node_suggs]
            if "DELETE" in actions and any(a.startswith("MODIFY") for a in actions):
                conflict_desc = [f"{s.suggestion_id} ({s.action})" for s in node_suggs]
                conflicts.append(ConflictInfo(
                    node_id=node_id,
                    conflicting_suggestions=conflict_desc,
                    recommendation="建议优先执行DELETE操作，忽略MODIFY操作"
                ))
    
    return conflicts


@router.get("/api/documents/{doc_id}/audit", response_model=AuditReportResponse)
async def get_audit_report(
    doc_id: str,
    action: Optional[str] = Query(None, description="Filter by action type (DELETE, ADD, MODIFY_FORMAT, MODIFY_PAGE)"),
    status: Optional[str] = Query(None, description="Filter by status (pending, accepted, rejected, applied)"),
    confidence: Optional[str] = Query(None, description="Filter by confidence (high, medium, low)"),
):
    """
    Get audit report with suggestions for a document.
    
    Args:
        doc_id: Document ID
        action: Optional filter by action type
        status: Optional filter by status
        confidence: Optional filter by confidence level
    
    Returns:
        Complete audit report with filtered suggestions
    """
    db = get_db()
    
    # Get document info
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Get audit report from database
    audit_report = db.get_audit_report(doc_id)
    if not audit_report:
        raise HTTPException(status_code=404, detail="No audit report found for this document")
    
    # Load audit report details from filesystem
    audit_data = load_audit_report_from_file(doc_id)
    if not audit_data:
        raise HTTPException(status_code=404, detail="Audit report file not found")
    
    # Get suggestions from database with filters
    suggestions_db = db.get_suggestions(
        audit_id=audit_report.audit_id,
        action=action,
        status=status,
        confidence=confidence,
    )
    
    # Convert to response model
    suggestions = [SuggestionInfo(**s.to_dict()) for s in suggestions_db]
    
    # Detect conflicts
    conflicts = detect_conflicts(suggestions)
    
    # Build summary
    suggestions_by_action = {}
    suggestions_by_confidence = {}
    for s in suggestions:
        suggestions_by_action[s.action] = suggestions_by_action.get(s.action, 0) + 1
        if s.confidence:
            suggestions_by_confidence[s.confidence] = suggestions_by_confidence.get(s.confidence, 0) + 1
    
    summary = AuditSummary(
        total_nodes=audit_data.get("summary", {}).get("total_nodes", 0),
        suggestions_by_action=suggestions_by_action,
        suggestions_by_confidence=suggestions_by_confidence,
        estimated_improvements=audit_data.get("summary", {}).get("estimated_improvements"),
    )
    
    return AuditReportResponse(
        audit_id=audit_report.audit_id,
        doc_id=audit_report.doc_id,
        doc_name=doc.filename,
        document_type=audit_report.document_type,
        quality_score=audit_report.quality_score,
        status=audit_report.status,
        summary=summary,
        suggestions=suggestions,
        conflicts=conflicts,
        created_at=audit_report.created_at.isoformat() if audit_report.created_at else None,
        applied_at=audit_report.applied_at.isoformat() if audit_report.applied_at else None,
    )


@router.get("/api/documents/{doc_id}/audit/suggestions/{suggestion_id}", response_model=SuggestionInfo)
async def get_suggestion_detail(doc_id: str, suggestion_id: str):
    """
    Get detailed information for a specific suggestion.
    
    Args:
        doc_id: Document ID
        suggestion_id: Suggestion ID
    
    Returns:
        Detailed suggestion information
    """
    db = get_db()
    
    suggestion = db.get_suggestion(suggestion_id)
    if not suggestion or suggestion.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    return SuggestionInfo(**suggestion.to_dict())


@router.post("/api/documents/{doc_id}/audit/suggestions/{suggestion_id}/review", response_model=SuggestionReviewResponse)
async def review_suggestion(
    doc_id: str,
    suggestion_id: str,
    body: SuggestionReviewRequest,
):
    """
    Accept or reject a suggestion.
    
    Args:
        doc_id: Document ID
        suggestion_id: Suggestion ID
        body: Review request with action (accept/reject) and optional comment
    
    Returns:
        Review response with updated status
    """
    db = get_db()
    
    # Validate action
    if body.action not in ["accept", "reject"]:
        raise HTTPException(status_code=400, detail="Action must be 'accept' or 'reject'")
    
    # Get suggestion
    suggestion = db.get_suggestion(suggestion_id)
    if not suggestion or suggestion.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    
    # Update review status
    success = db.update_suggestion_review(
        suggestion_id=suggestion_id,
        user_action=body.action,
        user_comment=body.comment,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update suggestion")
    
    new_status = "accepted" if body.action == "accept" else "rejected"
    
    return SuggestionReviewResponse(
        suggestion_id=suggestion_id,
        status=new_status,
        message=f"建议已{new_status}",
    )


@router.post("/api/documents/{doc_id}/audit/suggestions/batch-review", response_model=BatchReviewResponse)
async def batch_review_suggestions(
    doc_id: str,
    body: BatchReviewRequest,
):
    """
    Batch accept or reject suggestions.
    
    Args:
        doc_id: Document ID
        body: Batch review request with filters or specific IDs
    
    Returns:
        Batch review response with count of updated suggestions
    """
    db = get_db()
    
    # Validate action
    if body.action not in ["accept", "reject"]:
        raise HTTPException(status_code=400, detail="Action must be 'accept' or 'reject'")
    
    # Get audit report
    audit_report = db.get_audit_report(doc_id)
    if not audit_report:
        raise HTTPException(status_code=404, detail="No audit report found")
    
    # Get suggestions to update
    if body.suggestion_ids:
        # Use specific IDs
        suggestion_ids = body.suggestion_ids
    elif body.filters:
        # Use filters
        suggestions = db.get_suggestions(
            audit_id=audit_report.audit_id,
            action=body.filters.get("action"),
            status=body.filters.get("status", "pending"),
            confidence=body.filters.get("confidence"),
        )
        suggestion_ids = [s.suggestion_id for s in suggestions]
    else:
        raise HTTPException(status_code=400, detail="Must provide either suggestion_ids or filters")
    
    # Update all suggestions
    updated_count = 0
    for suggestion_id in suggestion_ids:
        success = db.update_suggestion_review(
            suggestion_id=suggestion_id,
            user_action=body.action,
            user_comment=body.comment,
        )
        if success:
            updated_count += 1
    
    return BatchReviewResponse(
        updated_count=updated_count,
        suggestion_ids=suggestion_ids,
        message=f"已批量{body.action} {updated_count} 个建议",
    )


@router.post("/api/documents/{doc_id}/audit/apply", response_model=ApplyResponse)
async def apply_suggestions(
    doc_id: str,
    body: ApplyRequest,
):
    """
    Apply accepted suggestions to the tree.
    
    This will:
    1. Create a backup snapshot
    2. Apply DELETE, MODIFY_FORMAT, MODIFY_PAGE, and ADD operations
    3. Save the updated tree
    4. Mark suggestions as applied
    
    Args:
        doc_id: Document ID
        body: Apply request (null suggestion_ids = all accepted)
    
    Returns:
        Apply response with backup ID for rollback
    """
    db = get_db()
    
    # Get audit report
    audit_report = db.get_audit_report(doc_id)
    if not audit_report:
        raise HTTPException(status_code=404, detail="No audit report found")
    
    # Get suggestions to apply
    if body.suggestion_ids:
        suggestions_to_apply = [db.get_suggestion(sid) for sid in body.suggestion_ids]
        suggestions_to_apply = [s for s in suggestions_to_apply if s and s.status == "accepted"]
    else:
        # Apply all accepted suggestions
        suggestions_to_apply = db.get_suggestions(
            audit_id=audit_report.audit_id,
            status="accepted",
        )
    
    if not suggestions_to_apply:
        raise HTTPException(status_code=400, detail="No accepted suggestions to apply")
    
    # Load current tree
    tree_data = load_tree_from_file(doc_id)
    if not tree_data:
        raise HTTPException(status_code=404, detail="Tree file not found")
    
    # Create backup
    backup_id = f"backup_{uuid.uuid4().hex[:8]}"
    data_dir = get_data_dir()
    backup_path = f"parsed/{doc_id}_audit_backup_{backup_id}.json"
    full_backup_path = data_dir / backup_path
    
    with open(full_backup_path, "w", encoding="utf-8") as f:
        json.dump(tree_data, f, ensure_ascii=False, indent=2)
    
    db.create_audit_backup(
        backup_id=backup_id,
        doc_id=doc_id,
        audit_id=audit_report.audit_id,
        backup_path=backup_path,
    )
    
    # Apply suggestions
    warnings = []
    applied_count = 0
    
    # Build node lookup and parent lookup
    def build_lookups(node, parent=None):
        """Build node_id -> node and node_id -> parent mappings"""
        node_lookup[node["id"]] = node
        if parent:
            parent_lookup[node["id"]] = parent
        for child in node.get("children", []):
            build_lookups(child, node)
    
    node_lookup = {}
    parent_lookup = {}
    build_lookups(tree_data)
    
    # Tree operation functions
    def delete_node(node_id):
        """Delete a node from the tree"""
        if node_id not in parent_lookup:
            # This is the root node - cannot delete
            return False
        
        parent = parent_lookup[node_id]
        if "children" not in parent:
            return False
        
        # Remove the node from parent's children
        original_count = len(parent["children"])
        parent["children"] = [c for c in parent["children"] if c["id"] != node_id]
        
        return len(parent["children"]) < original_count
    
    def modify_node_title(node_id, new_title):
        """Modify a node's title"""
        if node_id not in node_lookup:
            return False
        
        node = node_lookup[node_id]
        node["title"] = new_title
        return True
    
    def modify_node_pages(node_id, page_range_str):
        """Modify a node's page range"""
        if node_id not in node_lookup:
            return False
        
        node = node_lookup[node_id]
        
        try:
            # Parse page range: "1-5" or "10"
            if "-" in page_range_str:
                page_start, page_end = page_range_str.split("-", 1)
                node["page_start"] = int(page_start.strip())
                node["page_end"] = int(page_end.strip())
            else:
                page = int(page_range_str.strip())
                node["page_start"] = page
                node["page_end"] = page
            return True
        except (ValueError, AttributeError):
            return False
    
    def add_node(parent_id, new_node_data, position=None):
        """Add a new node to the tree"""
        if parent_id not in node_lookup:
            return False
        
        parent = node_lookup[parent_id]
        
        # Ensure children list exists
        if "children" not in parent:
            parent["children"] = []
        
        # Add node at specified position or at the end
        if position is not None and 0 <= position <= len(parent["children"]):
            parent["children"].insert(position, new_node_data)
        else:
            parent["children"].append(new_node_data)
        
        # Update lookups
        build_lookups(new_node_data, parent)
        
        return True
    
    # Sort suggestions by priority: DELETE first, then MODIFY, then ADD
    action_priority = {"DELETE": 1, "MODIFY_FORMAT": 2, "MODIFY_PAGE": 3, "ADD": 4}
    sorted_suggestions = sorted(suggestions_to_apply, key=lambda s: action_priority.get(s.action, 5))
    
    for suggestion in sorted_suggestions:
        try:
            if suggestion.action == "DELETE":
                if delete_node(suggestion.node_id):
                    applied_count += 1
                else:
                    warnings.append(f"无法删除节点 {suggestion.node_id}")
            
            elif suggestion.action == "MODIFY_FORMAT":
                if suggestion.suggested_title and modify_node_title(suggestion.node_id, suggestion.suggested_title):
                    applied_count += 1
                else:
                    warnings.append(f"无法修改节点 {suggestion.node_id} 的标题")
            
            elif suggestion.action == "MODIFY_PAGE":
                if suggestion.suggested_title and modify_node_pages(suggestion.node_id, suggestion.suggested_title):
                    applied_count += 1
                else:
                    warnings.append(f"无法修改节点 {suggestion.node_id} 的页码")
            
            elif suggestion.action == "ADD":
                # Extract node info from suggestion
                node_info = suggestion.node_info if suggestion.node_info else {}
                parent_id = node_info.get("parent_id")
                position = node_info.get("position")
                
                if not parent_id:
                    warnings.append(f"ADD建议缺少parent_id: {suggestion.suggestion_id}")
                    continue
                
                # Build new node data
                new_node = {
                    "id": suggestion.node_id or f"new_{uuid.uuid4().hex[:8]}",
                    "title": suggestion.suggested_title or "新节点",
                    "children": []
                }
                
                # Add page info if available
                if "page_start" in node_info:
                    new_node["page_start"] = node_info["page_start"]
                if "page_end" in node_info:
                    new_node["page_end"] = node_info["page_end"]
                
                if add_node(parent_id, new_node, position):
                    applied_count += 1
                else:
                    warnings.append(f"无法添加节点到父节点 {parent_id}")
        
        except Exception as e:
            warnings.append(f"应用建议 {suggestion.suggestion_id} 时出错: {str(e)}")
    
    # Save updated tree
    save_tree_to_file(doc_id, tree_data)
    
    # Mark suggestions as applied
    suggestion_ids_applied = [s.suggestion_id for s in sorted_suggestions]
    db.update_suggestions_status(suggestion_ids_applied, "applied")
    
    # Update audit report status
    db.update_audit_report_status(
        audit_id=audit_report.audit_id,
        status="applied",
        backup_id=backup_id,
    )
    
    return ApplyResponse(
        success=True,
        applied_count=applied_count,
        backup_id=backup_id,
        message=f"已成功应用 {applied_count} 个建议",
        warnings=warnings if warnings else None,
    )


@router.post("/api/documents/{doc_id}/audit/rollback", response_model=RollbackResponse)
async def rollback_audit(
    doc_id: str,
    body: RollbackRequest,
):
    """
    Rollback to a previous backup snapshot.
    
    Args:
        doc_id: Document ID
        body: Rollback request with backup ID
    
    Returns:
        Rollback response with status
    """
    db = get_db()
    
    # Get backup
    backup = db.get_audit_backup(body.backup_id)
    if not backup or backup.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Load backup data
    data_dir = get_data_dir()
    backup_path = data_dir / backup.backup_path
    
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")
    
    with open(backup_path, "r", encoding="utf-8") as f:
        backup_tree = json.load(f)
    
    # Restore tree
    save_tree_to_file(doc_id, backup_tree)
    
    # Update audit report status
    db.update_audit_report_status(
        audit_id=backup.audit_id,
        status="rolled_back",
    )
    
    return RollbackResponse(
        success=True,
        message=f"已成功回滚至备份 {body.backup_id}",
    )


@router.get("/api/documents/{doc_id}/audit/history", response_model=AuditHistoryResponse)
async def get_audit_history(doc_id: str):
    """
    Get audit history for a document.
    
    Args:
        doc_id: Document ID
    
    Returns:
        List of audit reports for this document
    """
    db = get_db()
    
    # Get document
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Note: Current implementation only stores latest audit
    # For full history, we'd need to modify database to keep all audit records
    audit_report = db.get_audit_report(doc_id)
    
    audits = []
    if audit_report:
        audits.append(AuditHistoryItem(
            audit_id=audit_report.audit_id,
            status=audit_report.status,
            total_suggestions=audit_report.total_suggestions,
            created_at=audit_report.created_at.isoformat() if audit_report.created_at else "",
            applied_at=audit_report.applied_at.isoformat() if audit_report.applied_at else None,
        ))
    
    return AuditHistoryResponse(
        doc_id=doc_id,
        audits=audits,
    )


@router.get("/api/documents/{doc_id}/audit/backups")
async def get_audit_backups(doc_id: str):
    """
    Get all audit backups for a document.
    
    Args:
        doc_id: Document ID
    
    Returns:
        List of backup snapshots with metadata
    """
    db = get_db()
    
    # Get document
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Get all backups for this document
    backups = db.get_backups_by_document(doc_id)
    
    # Format response
    backup_list = []
    for backup in backups:
        backup_dict = backup.to_dict()
        
        # Load backup file to get metadata
        backup_file_path = get_data_dir() / backup.backup_path
        if backup_file_path.exists():
            try:
                with open(backup_file_path, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
                    
                # Add tree statistics
                def count_nodes(node):
                    count = 1
                    if 'children' in node and node['children']:
                        for child in node['children']:
                            count += count_nodes(child)
                    return count
                
                backup_dict['node_count'] = count_nodes(backup_data)
            except Exception as e:
                backup_dict['node_count'] = None
                backup_dict['error'] = str(e)
        
        backup_list.append(backup_dict)
    
    return {
        "doc_id": doc_id,
        "backups": backup_list,
        "total": len(backup_list),
    }


@router.post("/api/documents/{doc_id}/audit/backups/{backup_id}/restore")
async def restore_from_backup(doc_id: str, backup_id: str):
    """
    Restore document tree from a specific backup (undo operation).
    
    Args:
        doc_id: Document ID
        backup_id: Backup ID to restore from
    
    Returns:
        Success message and restored tree info
    """
    db = get_db()
    
    # Get document
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Get backup
    backup = db.get_audit_backup(backup_id)
    if not backup or backup.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Load backup tree
    backup_file_path = get_data_dir() / backup.backup_path
    if not backup_file_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")
    
    try:
        with open(backup_file_path, 'r', encoding='utf-8') as f:
            backup_tree = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load backup: {str(e)}")
    
    # Create a new backup of current state before restoring
    current_tree = load_tree_from_file(doc_id)
    if current_tree:
        new_backup_id = str(uuid.uuid4())[:8]
        new_backup_path = f"parsed/{doc_id}_audit_backup_before_restore_{new_backup_id}.json"
        new_backup_file = get_data_dir() / new_backup_path
        
        with open(new_backup_file, 'w', encoding='utf-8') as f:
            json.dump(current_tree, f, ensure_ascii=False, indent=2)
        
        # Save backup record
        audit_report = db.get_audit_report(doc_id)
        if audit_report:
            db.create_audit_backup(
                backup_id=new_backup_id,
                doc_id=doc_id,
                audit_id=audit_report.audit_id,
                backup_path=new_backup_path,
            )
    
    # Restore the backup tree
    save_tree_to_file(doc_id, backup_tree)
    
    # Count nodes
    def count_nodes(node):
        count = 1
        if 'children' in node and node['children']:
            for child in node['children']:
                count += count_nodes(child)
        return count
    
    node_count = count_nodes(backup_tree)
    
    return {
        "success": True,
        "message": f"成功从备份 {backup_id} 恢复",
        "backup_id": backup_id,
        "restored_at": datetime.utcnow().isoformat(),
        "node_count": node_count,
        "new_backup_id": new_backup_id if current_tree else None,
    }
