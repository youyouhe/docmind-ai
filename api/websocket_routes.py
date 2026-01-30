"""
WebSocket routes for real-time document status updates.

Provides WebSocket endpoint for clients to subscribe to document parsing status.
"""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
import asyncio

from api.websocket_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/documents/{document_id}")
async def websocket_document_status(
    websocket: WebSocket,
    document_id: str,
    # Optional: allow client to specify auto-disconnect timeout (default 5 minutes)
    timeout: Optional[int] = Query(default=300, ge=30, le=3600)
):
    """
    WebSocket endpoint for document status updates.

    URL: ws://host/ws/documents/{document_id}?timeout=300

    Message Format:
    - Client sends: "ping" (heartbeat) or can send JSON for future extensions
    - Server sends: JSON with type field

    Server Messages:
    {
        "type": "connected",
        "document_id": "uuid",
        "message": "Successfully subscribed..."
    }

    {
        "type": "status_update",
        "document_id": "uuid",
        "status": "processing|completed|failed",
        "progress": 50.0,  // optional
        "error_message": "...",  // only if status=failed
        "metadata": {}  // optional additional data
    }

    Args:
        websocket: The WebSocket connection
        document_id: The document ID to subscribe to
        timeout: Auto-disconnect timeout in seconds (default 300, max 3600)
    """
    connection_id = None

    try:
        # Accept connection and subscribe to document
        connection_id = await manager.connect(websocket, document_id)

        logger.info(
            f"WebSocket connection established: {connection_id} -> {document_id}"
        )

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(websocket, connection_id)
        )

        # Message handling loop
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_text()

                # Handle ping/pong for heartbeat
                if data.lower() == "ping":
                    await websocket.send_text("pong")
                    logger.debug(f"Sent pong to {connection_id}")
                elif data.lower() == "pong":
                    # Client responding to our ping
                    await manager.handle_pong(connection_id)
                else:
                    # Future: could handle JSON commands from client
                    # For now, just log it
                    logger.debug(
                        f"Received message from {connection_id}: {data}"
                    )

            except WebSocketDisconnect:
                logger.info(f"Client {connection_id} disconnected normally")
                break
            except Exception as e:
                logger.error(
                    f"Error receiving from {connection_id}: {e}"
                )
                break

    except Exception as e:
        logger.error(f"WebSocket error for {document_id}: {e}")

    finally:
        # Clean up
        if connection_id:
            await manager.disconnect(connection_id)
            logger.info(
                f"Cleaned up connection {connection_id} for document {document_id}"
            )


async def heartbeat_loop(websocket: WebSocket, connection_id: str):
    """
    Send periodic ping messages to keep connection alive.

    Args:
        websocket: The WebSocket connection
        connection_id: Unique connection identifier
    """
    try:
        while True:
            await asyncio.sleep(30)  # Ping every 30 seconds
            await manager.send_heartbeat(connection_id)
    except asyncio.CancelledError:
        logger.debug(f"Heartbeat task cancelled for {connection_id}")
    except Exception as e:
        logger.error(f"Heartbeat error for {connection_id}: {e}")


@router.get("/stats")
async def get_websocket_stats():
    """
    Get WebSocket connection statistics.

    Returns information about active connections and subscriptions.
    """
    return manager.get_stats()
