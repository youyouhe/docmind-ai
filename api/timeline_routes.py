"""Timeline management routes for project date tracking."""

import uuid
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException

from api.database import get_db
from api.models import (
    TimelineEntryCreate,
    TimelineEntryUpdate,
    TimelineEntryResponse,
    TimelineListResponse,
    TimelineMilestone,
)

logger = logging.getLogger("pageindex.api.timeline")

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


def compute_status(start_date_str: Optional[str], end_date_str: Optional[str]) -> str:
    """Compute timeline status based on dates relative to today."""
    today = date.today()

    if not end_date_str:
        return "active"

    try:
        end = date.fromisoformat(end_date_str)
    except ValueError:
        return "active"

    if end < today:
        return "expired"

    if end <= today + timedelta(days=30):
        return "expiring_soon"

    if start_date_str:
        try:
            start = date.fromisoformat(start_date_str)
            if start > today:
                return "future"
        except ValueError:
            pass

    return "active"


def _entry_to_response(entry: dict) -> TimelineEntryResponse:
    """Convert a raw entry dict to a TimelineEntryResponse with computed status."""
    status = compute_status(entry.get("start_date"), entry.get("end_date"))
    milestones = [
        TimelineMilestone(**m) for m in (entry.get("milestones") or [])
    ]
    return TimelineEntryResponse(
        id=entry["id"],
        document_id=entry["document_id"],
        project_name=entry["project_name"],
        start_date=entry.get("start_date"),
        end_date=entry.get("end_date"),
        milestones=milestones,
        budget=entry.get("budget"),
        budget_unit=entry.get("budget_unit", "万元"),
        notes=entry.get("notes"),
        status=status,
        created_at=entry["created_at"],
        updated_at=entry["updated_at"],
    )


@router.get("/", response_model=TimelineListResponse)
async def list_timeline_entries(
    document_id: Optional[str] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
):
    """List all timeline entries, optionally filtered by document_id and budget range."""
    db = get_db()
    entries = db.get_timeline_entries(document_id)

    items = []
    expiring = 0
    expired = 0
    for e in entries:
        # Apply budget filter (normalize to 万元 for comparison)
        entry_budget = e.get("budget")
        if entry_budget is not None:
            entry_unit = e.get("budget_unit", "万元")
            # Normalize to 万元
            if entry_unit == "元":
                normalized_budget = entry_budget / 10000
            elif entry_unit == "亿元":
                normalized_budget = entry_budget * 10000
            else:
                # Assume 万元
                normalized_budget = entry_budget
        else:
            normalized_budget = None
        if budget_min is not None and (normalized_budget is None or normalized_budget < budget_min):
            continue
        if budget_max is not None and (normalized_budget is None or normalized_budget > budget_max):
            continue

        resp = _entry_to_response(e)
        if resp.status == "expiring_soon":
            expiring += 1
        if resp.status == "expired":
            expired += 1
        items.append(resp)

    return TimelineListResponse(
        items=items,
        count=len(items),
        expiring_count=expiring,
        expired_count=expired,
    )


@router.post("/", response_model=TimelineEntryResponse, status_code=201)
async def create_timeline_entry(req: TimelineEntryCreate):
    """Create a new timeline entry."""
    db = get_db()

    # Verify document exists
    doc = db.get_document(req.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    entry_id = str(uuid.uuid4())
    entry = db.create_timeline_entry(
        entry_id=entry_id,
        document_id=req.document_id,
        project_name=req.project_name,
        start_date=req.start_date,
        end_date=req.end_date,
        milestones=[m.model_dump() for m in req.milestones],
        budget=req.budget,
        budget_unit=req.budget_unit,
        notes=req.notes,
    )

    logger.info(f"Created timeline entry {entry_id} for document {req.document_id}")
    return _entry_to_response(entry)


@router.get("/{entry_id}", response_model=TimelineEntryResponse)
async def get_timeline_entry(entry_id: str):
    """Get a single timeline entry by ID."""
    db = get_db()
    entry = db.get_timeline_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Timeline entry not found")
    return _entry_to_response(entry)


@router.patch("/{entry_id}", response_model=TimelineEntryResponse)
async def update_timeline_entry(entry_id: str, req: TimelineEntryUpdate):
    """Update an existing timeline entry."""
    db = get_db()
    updates = req.model_dump(exclude_unset=True)

    if "milestones" in updates and updates["milestones"] is not None:
        updates["milestones"] = [
            m.model_dump() if hasattr(m, "model_dump") else m
            for m in updates["milestones"]
        ]

    entry = db.update_timeline_entry(entry_id, **updates)
    if not entry:
        raise HTTPException(status_code=404, detail="Timeline entry not found")

    logger.info(f"Updated timeline entry {entry_id}")
    return _entry_to_response(entry)


@router.delete("/{entry_id}")
async def delete_timeline_entry(entry_id: str):
    """Delete a timeline entry."""
    db = get_db()
    deleted = db.delete_timeline_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Timeline entry not found")

    logger.info(f"Deleted timeline entry {entry_id}")
    return {"id": entry_id, "deleted": True}
