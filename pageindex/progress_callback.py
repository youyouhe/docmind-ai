"""
Progress callback infrastructure for real-time WebSocket updates.

Provides a thread-safe mechanism for reporting progress during document parsing
from background threads to the main async event loop.
"""

import asyncio
import threading
from typing import Optional, Callable, Any, Dict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ProgressCallback:
    """
    Thread-safe progress callback for document processing.

    This class allows background threads (running document parsing)
    to safely report progress to the main async event loop which
    handles WebSocket broadcasts.

    Usage:
        # In async context (document_routes.py)
        callback = ProgressCallback(document_id="abc", on_update=async_function)

        # Pass to parsing function
        result = await ParseService.parse_pdf(..., progress_callback=callback)

        # In parsing function (any thread)
        callback.report(stage="toc_processing", progress=30, message="Finding TOC...")
    """

    def __init__(
        self,
        document_id: str,
        on_update: Optional[Callable[[str, str, float, Dict[str, Any]], None]] = None
    ):
        """
        Initialize progress callback.

        Args:
            document_id: Document ID for progress updates
            on_update: Async callback function that will receive updates.
                      Signature: (document_id, stage, progress, metadata) -> None
        """
        self.document_id = document_id
        self._on_update = on_update

        # Thread-safe queue for progress updates
        self._queue = []
        self._lock = threading.Lock()

        # Track if callback is enabled
        self._enabled = True

    def disable(self):
        """Disable further callback invocations."""
        with self._lock:
            self._enabled = False

    def is_enabled(self) -> bool:
        """Check if callback is enabled."""
        with self._lock:
            return self._enabled

    def report(
        self,
        stage: str,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Report progress update (thread-safe, can be called from any thread).

        Args:
            stage: Processing stage identifier (e.g., "tree_building", "toc_processing")
            progress: Progress percentage (0-100), or None for status-only update
            message: Human-readable status message
            metadata: Additional metadata (llm_calls, tokens, etc.)
        """
        if not self.is_enabled():
            return

        # Build metadata dict
        meta = metadata or {}
        if message:
            meta["message"] = message

        # Queue the update
        with self._lock:
            self._queue.append((stage, progress, meta))

    def get_pending_updates(self) -> list:
        """
        Get and clear pending updates (called from main async loop).

        Returns:
            List of (stage, progress, metadata) tuples
        """
        with self._lock:
            updates = self._queue
            self._queue = []
            return updates

    async def process_updates(self):
        """
        Process all pending updates via the async callback.

        This should be called periodically from the main async event loop
        to send queued updates via WebSocket.
        """
        if self._on_update is None:
            return

        updates = self.get_pending_updates()
        for stage, progress, metadata in updates:
            try:
                await self._on_update(
                    self.document_id,
                    stage,
                    progress if progress is not None else 0.0,
                    metadata
                )
            except Exception as e:
                # Log but don't raise - we don't want to interrupt parsing
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error in progress callback: {e}")


# Global callback registry for accessing from page_index.py
_callback_registry: Dict[str, ProgressCallback] = {}
_registry_lock = threading.Lock()


def register_callback(document_id: str, callback: ProgressCallback):
    """Register a progress callback for a document."""
    with _registry_lock:
        _callback_registry[document_id] = callback


def unregister_callback(document_id: str):
    """Unregister a progress callback."""
    with _registry_lock:
        _callback_registry.pop(document_id, None)


def get_callback(document_id: str) -> Optional[ProgressCallback]:
    """Get the registered callback for a document."""
    with _registry_lock:
        return _callback_registry.get(document_id)


def report_progress(
    document_id: str,
    stage: str,
    progress: Optional[float] = None,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Report progress for a document (convenience function).

    This can be called from anywhere in the parsing code to report progress.

    Args:
        document_id: Document ID
        stage: Processing stage identifier
        progress: Progress percentage (0-100)
        message: Human-readable status message
        metadata: Additional metadata
    """
    callback = get_callback(document_id)
    if callback and callback.is_enabled():
        callback.report(stage, progress, message, metadata)


# Convenience decorators/context managers for common stages

# Global document_id for progress callbacks (used by page_index.py)
_current_document_id = None
_document_id_lock = threading.Lock()


def set_document_id(document_id: str):
    """
    Set the current document ID for progress callbacks.

    This is called at the start of document parsing to associate
    all progress reports with a specific document.
    """
    global _current_document_id
    with _document_id_lock:
        _current_document_id = document_id


def get_document_id() -> Optional[str]:
    """
    Get the current document ID for progress callbacks.

    Returns the document ID that was set via set_document_id(),
    or None if no document is being processed.
    """
    with _document_id_lock:
        return _current_document_id


class StageProgress:
    """Context manager for reporting stage progress."""

    def __init__(
        self,
        document_id: str,
        stage_name: str,
        progress_start: float,
        progress_end: float,
        message: Optional[str] = None
    ):
        self.document_id = document_id
        self.stage_name = stage_name
        self.progress_start = progress_start
        self.progress_end = progress_end
        self.message = message

    def __enter__(self):
        report_progress(
            self.document_id,
            self.stage_name,
            self.progress_start,
            self.message or f"Starting {self.stage_name}..."
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        report_progress(
            self.document_id,
            self.stage_name,
            self.progress_end,
            f"Completed {self.stage_name}"
        )
        return False


class LLMProgressTracker:
    """Track and report LLM call progress during a stage."""

    def __init__(
        self,
        document_id: str,
        stage: str,
        total_calls: int,
        progress_start: float,
        progress_end: float
    ):
        self.document_id = document_id
        self.stage = stage
        self.total_calls = total_calls
        self.progress_start = progress_start
        self.progress_end = progress_end
        self.completed_calls = 0

    def report_call(self, input_tokens: int = 0, output_tokens: int = 0, time: float = 0):
        """Report a completed LLM call."""
        self.completed_calls += 1
        progress = self.progress_start + (
            (self.progress_end - self.progress_start) *
            (self.completed_calls / self.total_calls)
        )

        report_progress(
            self.document_id,
            self.stage,
            progress,
            metadata={
                "llm_call": f"{self.completed_calls}/{self.total_calls}",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "time": time
            }
        )
