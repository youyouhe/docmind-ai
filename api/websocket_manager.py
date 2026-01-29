"""
WebSocket Connection Manager for real-time document status updates.

Manages WebSocket connections for document parsing status notifications.
Supports multiple concurrent document subscriptions per connection.
"""

from typing import Dict, Set, Optional
from fastapi import WebSocket
import logging
import json

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for document status updates.

    Architecture:
    - active_connections: All connected WebSocket clients
    - document_subscribers: Maps document_id -> set of connection IDs
    - connection_documents: Maps connection_id -> set of document IDs being tracked

    This allows:
    1. Broadcasting status updates to specific document subscribers
    2. Managing multiple document subscriptions per connection
    3. Proper cleanup when connections close
    """

    def __init__(self):
        # connection_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}

        # document_id -> set of connection_ids subscribed to this document
        self.document_subscribers: Dict[str, Set[str]] = {}

        # connection_id -> set of document_ids this connection is tracking
        self.connection_documents: Dict[str, Set[str]] = {}

        # Counter for generating unique connection IDs
        self._connection_counter = 0

    def _generate_connection_id(self) -> str:
        """Generate a unique connection ID."""
        self._connection_counter += 1
        return f"conn_{self._connection_counter}"

    async def connect(self, websocket: WebSocket, document_id: str) -> str:
        """
        Accept a new WebSocket connection and subscribe to document updates.

        Args:
            websocket: The WebSocket connection
            document_id: The document ID to subscribe to

        Returns:
            The unique connection ID assigned to this connection
        """
        await websocket.accept()

        connection_id = self._generate_connection_id()
        self.active_connections[connection_id] = websocket

        # Subscribe this connection to the document
        if document_id not in self.document_subscribers:
            self.document_subscribers[document_id] = set()
        self.document_subscribers[document_id].add(connection_id)

        # Track which documents this connection is subscribed to
        if connection_id not in self.connection_documents:
            self.connection_documents[connection_id] = set()
        self.connection_documents[connection_id].add(document_id)

        logger.info(
            f"WebSocket connected: {connection_id} subscribed to document: {document_id}"
        )

        # Send connection confirmation message
        await self._send_to_connection(
            connection_id,
            {
                "type": "connected",
                "document_id": document_id,
                "message": f"Successfully subscribed to document {document_id}",
            }
        )

        return connection_id

    async def disconnect(self, connection_id: str):
        """
        Disconnect a WebSocket connection and clean up subscriptions.

        Args:
            connection_id: The connection ID to disconnect
        """
        if connection_id not in self.active_connections:
            logger.warning(f"Connection {connection_id} not found in active connections")
            return

        # Remove this connection from all document subscriptions
        if connection_id in self.connection_documents:
            for document_id in self.connection_documents[connection_id]:
                if document_id in self.document_subscribers:
                    self.document_subscribers[document_id].discard(connection_id)
                    # Clean up empty subscriber sets
                    if not self.document_subscribers[document_id]:
                        del self.document_subscribers[document_id]

            del self.connection_documents[connection_id]

        # Remove the active connection
        del self.active_connections[connection_id]

        logger.info(f"WebSocket disconnected: {connection_id}")

    async def subscribe_to_document(
        self,
        connection_id: str,
        document_id: str
    ):
        """
        Subscribe an existing connection to additional documents.

        Args:
            connection_id: The existing connection ID
            document_id: The document ID to subscribe to
        """
        if connection_id not in self.active_connections:
            logger.warning(
                f"Cannot subscribe connection {connection_id}: connection not found"
            )
            return

        # Add document subscription
        if document_id not in self.document_subscribers:
            self.document_subscribers[document_id] = set()
        self.document_subscribers[document_id].add(connection_id)

        # Track subscription for this connection
        self.connection_documents[connection_id].add(document_id)

        logger.info(
            f"Connection {connection_id} subscribed to additional document: {document_id}"
        )

        # Send subscription confirmation
        await self._send_to_connection(
            connection_id,
            {
                "type": "subscribed",
                "document_id": document_id,
                "message": f"Subscribed to document {document_id}",
            }
        )

    async def unsubscribe_from_document(
        self,
        connection_id: str,
        document_id: str
    ):
        """
        Unsubscribe a connection from a specific document.

        Args:
            connection_id: The connection ID
            document_id: The document ID to unsubscribe from
        """
        if connection_id not in self.connection_documents:
            return

        if document_id in self.connection_documents[connection_id]:
            self.connection_documents[connection_id].discard(document_id)

        if document_id in self.document_subscribers:
            self.document_subscribers[document_id].discard(connection_id)
            if not self.document_subscribers[document_id]:
                del self.document_subscribers[document_id]

        logger.info(
            f"Connection {connection_id} unsubscribed from document: {document_id}"
        )

    async def broadcast_status_update(
        self,
        document_id: str,
        status: str,
        error_message: Optional[str] = None,
        progress: Optional[float] = None,
        metadata: Optional[dict] = None
    ):
        """
        Broadcast a status update to all subscribers of a document.

        Args:
            document_id: The document ID
            status: The new status (pending, processing, completed, failed)
            error_message: Optional error message for failed status
            progress: Optional progress percentage (0-100)
            metadata: Optional additional metadata
        """
        if document_id not in self.document_subscribers:
            logger.debug(
                f"No subscribers for document {document_id}, skipping broadcast"
            )
            return

        message = {
            "type": "status_update",
            "document_id": document_id,
            "status": status,
        }

        if error_message:
            message["error_message"] = error_message

        if progress is not None:
            message["progress"] = progress

        if metadata:
            message["metadata"] = metadata

        # Create a set of connections to notify (copy to avoid modification during iteration)
        subscribers = self.document_subscribers[document_id].copy()

        logger.info(
            f"Broadcasting status {status} for document {document_id} "
            f"to {len(subscribers)} subscriber(s)"
        )

        failed_connections = set()
        for connection_id in subscribers:
            success = await self._send_to_connection(connection_id, message)
            if not success:
                failed_connections.add(connection_id)

        # Clean up failed connections
        for connection_id in failed_connections:
            logger.warning(f"Removing failed connection: {connection_id}")
            await self.disconnect(connection_id)

    async def send_heartbeat(self, connection_id: str):
        """
        Send a ping heartbeat to a specific connection.

        Args:
            connection_id: The connection ID to ping
        """
        await self._send_to_connection(connection_id, "ping")

    async def handle_pong(self, connection_id: str):
        """
        Handle a pong response from a connection.

        Args:
            connection_id: The connection ID that sent pong
        """
        logger.debug(f"Received pong from connection: {connection_id}")
        # Connection is alive, no additional action needed

    async def _send_to_connection(
        self,
        connection_id: str,
        message: dict | str
    ) -> bool:
        """
        Send a message to a specific connection.

        Args:
            connection_id: The connection ID
            message: The message to send (dict for JSON, or "ping" string)

        Returns:
            True if sent successfully, False otherwise
        """
        if connection_id not in self.active_connections:
            logger.warning(f"Connection {connection_id} not found")
            return False

        websocket = self.active_connections[connection_id]

        try:
            if isinstance(message, str):
                # Send raw string (for ping/pong)
                await websocket.send_text(message)
            else:
                # Send JSON message
                await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error(
                f"Error sending to connection {connection_id}: {e}"
            )
            return False

    def get_connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self.active_connections)

    def get_subscriber_count(self, document_id: str) -> int:
        """Get the number of subscribers for a specific document."""
        return len(self.document_subscribers.get(document_id, set()))

    def get_stats(self) -> dict:
        """Get connection manager statistics."""
        return {
            "active_connections": len(self.active_connections),
            "tracked_documents": len(self.document_subscribers),
            "total_subscriptions": sum(
                len(subs) for subs in self.document_subscribers.values()
            ),
        }


# Global connection manager instance
manager = ConnectionManager()
