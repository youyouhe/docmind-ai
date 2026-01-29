#!/bin/bash
# PageIndex API Server Startup Script
# This script loads environment variables from .env before starting the server

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Function to mask sensitive values
mask_value() {
    local value="$1"
    if [[ -z "$value" ]]; then
        echo "(not set)"
    elif [[ ${#value} -le 8 ]]; then
        echo "***"
    else
        echo "${value:0:8}***"
    fi
}

# Load environment variables from .env if it exists
if [[ -f ".env" ]]; then
    echo "Loading environment variables from .env..."
    set -a  # Automatically export all variables
    source .env
    set +a
    echo "Environment variables loaded."
    echo ""
    echo "=== Environment Variables ==="
    echo "LLM_PROVIDER=${LLM_PROVIDER:-deepseek}"
    echo "LLM_MODEL=${LLM_MODEL:-}"
    echo "PORT=${PORT:-8003}"
    echo "PAGEINDEX_DB_PATH=${PAGEINDEX_DB_PATH:-data/documents.db}"
    echo ""
    echo "API Keys:"
    echo "  DEEPSEEK_API_KEY=$(mask_value "$DEEPSEEK_API_KEY")"
    echo "  OPENAI_API_KEY=$(mask_value "$OPENAI_API_KEY")"
    echo "  GEMINI_API_KEY=$(mask_value "$GEMINI_API_KEY")"
    echo "  OPENROUTER_API_KEY=$(mask_value "$OPENROUTER_API_KEY")"
    echo "  ZHIPU_API_KEY=$(mask_value "$ZHIPU_API_KEY")"
    echo "============================="
    echo ""
else
    echo "Warning: .env file not found!"
fi

# Check required environment variables
if [[ -z "$DEEPSEEK_API_KEY" ]] && [[ -z "$OPENAI_API_KEY" ]] && [[ -z "$GEMINI_API_KEY" ]] && [[ -z "$OPENROUTER_API_KEY" ]] && [[ -z "$ZHIPU_API_KEY" ]]; then
    echo "Error: No API key found. Please set DEEPSEEK_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, or ZHIPU_API_KEY in .env"
    exit 1
fi

# Start the server
echo "Starting PageIndex API server..."

# Set default port
export PORT="${PORT:-8003}"

# Start uvicorn with environment variables
exec python -m uvicorn api.index:app --host 0.0.0.0 --port "${PORT}" --reload
