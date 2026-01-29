#!/bin/bash
# PageIndex API Server Stop Script
# This script loads environment variables from .env before stopping the server

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment variables from .env if it exists
if [[ -f ".env" ]]; then
    echo "Loading environment variables from .env..."
    set -a  # Automatically export all variables
    source .env
    set +a
    echo "Environment variables loaded."
else
    echo "Warning: .env file not found!"
fi

# Set default port
PORT="${PORT:-8003}"

# Find and kill the process running on the port
echo "Stopping PageIndex API server on port ${PORT}..."

# Find process IDs listening on the port (could be multiple)
PIDS=$(lsof -ti :"${PORT}" 2>/dev/null)

if [[ -n "$PIDS" ]]; then
    echo "Killing processes: $PIDS"
    xargs kill <<< "$PIDS"
    echo "Server stopped"
else
    echo "No server found running on port ${PORT}"
fi
