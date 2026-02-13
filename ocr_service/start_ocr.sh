#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export OCR_MODEL="${OCR_MODEL:-deepseek-ai/DeepSeek-OCR-2}"
export OCR_PORT="${OCR_PORT:-8010}"
export OCR_BASE_SIZE="${OCR_BASE_SIZE:-1024}"
export OCR_IMAGE_SIZE="${OCR_IMAGE_SIZE:-768}"

echo "============================================"
echo "  DeepSeek-OCR-2 Service"
echo "============================================"
echo "  Model:      ${OCR_MODEL}"
echo "  Port:       ${OCR_PORT}"
echo "  Base Size:  ${OCR_BASE_SIZE}"
echo "  Image Size: ${OCR_IMAGE_SIZE}"
echo "============================================"

exec python -m uvicorn main:app --host 0.0.0.0 --port "${OCR_PORT}"
