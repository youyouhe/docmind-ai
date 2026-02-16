FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/huggingface

# Install Python 3.12 and system dependencies required by PyMuPDF
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common \
        curl && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        libgl1-mesa-glx \
        libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Set python3.12 as default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Install pip
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python

WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py ocr_engine.py __init__.py ./

# Create non-root user
RUN groupadd -r ocr && useradd -r -g ocr -d /app ocr && \
    mkdir -p /data/huggingface && \
    chown -R ocr:ocr /app /data

USER ocr

ENV OCR_MODEL=deepseek-ai/DeepSeek-OCR-2 \
    OCR_PORT=8010 \
    OCR_BASE_SIZE=1024 \
    OCR_IMAGE_SIZE=768

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=300s \
    CMD curl -f http://localhost:8010/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
