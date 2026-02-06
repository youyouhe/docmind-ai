# DocMind-AI Backend for BidSmart

[![Based on PageIndex](https://img.shields.io/badge/Based%20on-PageIndex-blue)](https://github.com/VectifyAI/PageIndex)
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-0.1+-orange.svg)](https://www.langchain.com/)

This is the **backend service** for [BidSmart](https://github.com/youyouhe/BidSmart), an intelligent document structure auditing system for tender/bidding documents. It's built on top of the [PageIndex](https://github.com/VectifyAI/PageIndex) framework with extensive customizations for document structure analysis and AI-powered auditing.

## Overview

DocMind-AI extends PageIndex's hierarchical tree indexing capabilities with:
- **Document Structure Auditing**: AI-powered analysis of document hierarchy, numbering, and formatting
- **Progressive Audit System**: 5-phase audit workflow with real-time progress tracking
- **Backup & Recovery**: Automatic backup creation before applying structural changes
- **RESTful API**: FastAPI-based endpoints for document management and audit operations
- **WebSocket Support**: Real-time progress updates during parsing and auditing

---

## Key Features

### 🎯 Document Structure Auditing
- **TreeAuditorV2**: Advanced 5-phase progressive audit system
  - Phase 1: Numbering system analysis
  - Phase 2: Format consistency check
  - Phase 3: Logical hierarchy validation
  - Phase 4: Completeness evaluation
  - Phase 5: Overall recommendations
- **Confidence Scoring**: High/Medium/Low confidence levels for each suggestion
- **Action Types**: DELETE, ADD, MODIFY_FORMAT, MODIFY_PAGE operations
- **node_info Extraction**: Proper handling of ADD suggestions with parent_id and insert_position

### 🔄 Backup & Recovery System
- **Automatic Backups**: Creates backup before applying structural changes
- **Backup Metadata**: Stores operation type, change summary, and timestamps
- **One-Click Restore**: Restore document to any previous state
- **Safety Protection**: Creates safety backup before restoration

### 🚀 API Endpoints

#### Document Management
- `POST /api/documents/upload` - Upload and parse PDF document
- `GET /api/documents` - List all documents
- `GET /api/documents/{doc_id}` - Get document details with tree structure
- `DELETE /api/documents/{doc_id}` - Delete document and associated data

#### Audit Operations
- `POST /api/documents/{doc_id}/audit` - Start audit process with progress tracking
- `GET /api/documents/{doc_id}/audit/suggestions` - Get all audit suggestions
- `POST /api/documents/{doc_id}/audit/suggestions/{suggestion_id}/review` - Accept/reject suggestion
- `POST /api/documents/{doc_id}/audit/suggestions/batch-review` - Batch operations by confidence/action
- `POST /api/documents/{doc_id}/audit/suggestions/apply` - Apply accepted suggestions with backup

#### Backup Management
- `GET /api/documents/{doc_id}/audit/backups` - List all backups for document
- `POST /api/documents/{doc_id}/audit/backups/{backup_id}/restore` - Restore from backup

#### WebSocket
- `WS /ws` - Real-time updates for parsing and audit progress

### 📊 Database Schema

Built on SQLAlchemy with the following models:
- **Document**: Document metadata and tree structure
- **AuditSuggestion**: AI-generated suggestions with confidence and reasoning
- **AuditBackup**: Backup snapshots with metadata and change summaries

---

## Installation

### Prerequisites
- Python 3.8+
- OpenAI API key or Azure OpenAI credentials

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file:
```bash
cp .env.example .env
```

3. Configure environment variables:
```env
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key
OPENAI_BASE_URL=https://api.openai.com/v1

# Or Azure OpenAI Configuration
AZURE_OPENAI_API_KEY=your_azure_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
AZURE_OPENAI_API_VERSION=2024-02-01

# Database
DATABASE_URL=sqlite:///./data/bidsmart.db

# Storage paths
UPLOAD_DIR=./data/uploads
PARSED_DIR=./data/parsed
```

4. Run the server:
```bash
python -m uvicorn api.index:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

### API Documentation

Once running, access interactive API documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Architecture

```
docmind-ai/
├── api/
│   ├── index.py              # FastAPI app entry point
│   ├── document_routes.py    # Document CRUD + parsing endpoints
│   ├── audit_routes.py       # Audit and backup endpoints
│   ├── database.py           # SQLAlchemy models and queries
│   ├── websocket_manager.py  # WebSocket connection management
│   ├── models.py             # Pydantic models for request/response
│   ├── services.py           # Business logic services
│   └── storage.py            # File storage utilities
│
├── pageindex_v2/
│   ├── phases/
│   │   ├── tree_builder.py       # PDF parsing and tree construction
│   │   ├── tree_auditor_v2.py    # 5-phase progressive audit system
│   │   ├── advice_executor.py    # Apply suggestions to tree structure
│   │   ├── document_classifier.py # Document type classification
│   │   └── pdf_verifier.py       # PDF validation
│   ├── core/
│   │   └── llm_client.py         # LLM interaction wrapper
│   ├── utils/
│   │   └── title_normalizer.py   # Title normalization utilities
│   └── main.py                   # PageIndex pipeline orchestrator
│
└── data/
    ├── uploads/              # Uploaded PDF files
    ├── parsed/               # Generated tree structures
    └── bidsmart.db           # SQLite database
```

---

## Key Customizations from PageIndex

This fork extends the original [PageIndex](https://github.com/VectifyAI/PageIndex) framework with:

### 1. Document Structure Auditing (`tree_auditor_v2.py`)
- **Progressive Audit System**: 5-phase workflow with incremental analysis
- **Real-time Progress**: WebSocket broadcasting for each audit phase
- **Confidence Scoring**: High/Medium/Low classification for suggestions
- **Action Types**: DELETE, ADD, MODIFY_FORMAT, MODIFY_PAGE operations
- **Reasoning-based Suggestions**: AI-generated explanations for each recommendation

### 2. Suggestion Execution (`advice_executor.py`)
- **Safe Application**: Apply structural changes with validation
- **node_info Handling**: Proper extraction of parent_id and insert_position for ADD operations
- **Batch Operations**: Accept/reject multiple suggestions by confidence or action type
- **Tree Reconstruction**: Rebuild document tree after applying changes

### 3. Backup Management (`audit_routes.py`, `database.py`)
- **Automatic Backups**: Create backup before any structural changes
- **Backup Metadata**: Track operation type, change count, and timestamps
- **Restore Functionality**: One-click restoration to any previous state
- **Safety Protection**: Creates safety backup before restoration

### 4. API Layer (`document_routes.py`, `audit_routes.py`)
- **RESTful Endpoints**: Comprehensive API for document and audit operations
- **WebSocket Support**: Real-time progress updates during long-running operations
- **Batch Operations**: Bulk accept/reject by confidence level or action type
- **Error Handling**: Proper error responses with detailed messages

### 5. node_info Fix (`document_routes.py` lines 1509-1537)
- **Problem**: ADD suggestions were saved with `node_info: null`
- **Solution**: Extract top-level `parent_id`, `insert_position`, etc., and assemble into `node_info` object
- **Impact**: Proper display of ADD suggestions in frontend tree view

---

## Usage Examples

### 1. Upload and Parse Document

```python
import requests

# Upload PDF
with open('document.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/api/documents/upload',
        files={'file': f}
    )

doc_id = response.json()['id']
print(f"Document ID: {doc_id}")
```

### 2. Run Audit

```python
# Start audit
response = requests.post(
    f'http://localhost:8000/api/documents/{doc_id}/audit'
)

# Get suggestions
suggestions = requests.get(
    f'http://localhost:8000/api/documents/{doc_id}/audit/suggestions'
).json()

for suggestion in suggestions:
    print(f"{suggestion['action']}: {suggestion['reason']}")
```

### 3. Batch Operations

```python
# Batch accept high confidence suggestions
requests.post(
    f'http://localhost:8000/api/documents/{doc_id}/audit/suggestions/batch-review',
    json={
        'filter_confidence': 'high',
        'decision': 'accept'
    }
)

# Apply accepted suggestions
requests.post(
    f'http://localhost:8000/api/documents/{doc_id}/audit/suggestions/apply'
)
```

### 4. Backup & Restore

```python
# List backups
backups = requests.get(
    f'http://localhost:8000/api/documents/{doc_id}/audit/backups'
).json()

# Restore from backup
backup_id = backups[0]['id']
requests.post(
    f'http://localhost:8000/api/documents/{doc_id}/audit/backups/{backup_id}/restore'
)
```

---

## WebSocket Progress Tracking

Connect to WebSocket for real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  
  if (message.type === 'audit_progress') {
    console.log(`Phase ${message.phase_number}/5: ${message.message}`);
    console.log(`Progress: ${message.progress}%`);
  }
};
```

---

## Development

### Run Tests
```bash
pytest tests/
```

### Code Style
```bash
# Format code
black api/ pageindex_v2/

# Lint
flake8 api/ pageindex_v2/
```

---

## Acknowledgments

This project is built on top of the excellent [PageIndex](https://github.com/VectifyAI/PageIndex) framework by [Vectify AI](https://vectify.ai). PageIndex provides the foundational tree indexing and reasoning-based retrieval capabilities.

**Key PageIndex Features We Use:**
- Hierarchical tree structure generation from PDFs
- LLM-based document understanding
- Tree search and navigation
- No vector DB, no chunking approach

**Our Extensions:**
- Document structure auditing system
- Progressive multi-phase audit workflow
- Backup and recovery system
- RESTful API and WebSocket support
- Batch operations and filtering

For more information about PageIndex:
- [PageIndex Framework Introduction](https://pageindex.ai/blog/pageindex-intro)
- [PageIndex Documentation](https://docs.pageindex.ai)
- [PageIndex GitHub](https://github.com/VectifyAI/PageIndex)

---

# 🌲 PageIndex Tree Structure
PageIndex can transform lengthy PDF documents into a semantic **tree structure**, similar to a _"table of contents"_ but optimized for use with Large Language Models (LLMs). It's ideal for: financial reports, regulatory filings, academic textbooks, legal or technical manuals, and any document that exceeds LLM context limits.

Below is an example PageIndex tree structure. Also see more example [documents](https://github.com/VectifyAI/PageIndex/tree/main/tests/pdfs) and generated [tree structures](https://github.com/VectifyAI/PageIndex/tree/main/tests/results).

```jsonc
...
{
  "title": "Financial Stability",
  "node_id": "0006",
  "start_index": 21,
  "end_index": 22,
  "summary": "The Federal Reserve ...",
  "nodes": [
    {
      "title": "Monitoring Financial Vulnerabilities",
      "node_id": "0007",
      "start_index": 22,
      "end_index": 28,
      "summary": "The Federal Reserve's monitoring ..."
    },
    {
      "title": "Domestic and International Cooperation and Coordination",
      "node_id": "0008",
      "start_index": 28,
      "end_index": 31,
      "summary": "In 2023, the Federal Reserve collaborated ..."
    }
  ]
}
...
```

You can generate the PageIndex tree structure with this open-source repo, or use our [API](https://docs.pageindex.ai/quickstart) 

---

# ⚙️ Package Usage

You can follow these steps to generate a PageIndex tree from a PDF document.

### 1. Install dependencies

```bash
pip3 install --upgrade -r requirements.txt
```

### 2. Set your OpenAI API key

Create a `.env` file in the root directory and add your API key:

```bash
CHATGPT_API_KEY=your_openai_key_here
```

### 3. Run PageIndex on your PDF

```bash
python3 run_pageindex.py --pdf_path /path/to/your/document.pdf
```

<details>
<summary><strong>Optional parameters</strong></summary>
<br>
You can customize the processing with additional optional arguments:

```
--model                 OpenAI model to use (default: gpt-4o-2024-11-20)
--toc-check-pages       Pages to check for table of contents (default: 20)
--max-pages-per-node    Max pages per node (default: 10)
--max-tokens-per-node   Max tokens per node (default: 20000)
--if-add-node-id        Add node ID (yes/no, default: yes)
--if-add-node-summary   Add node summary (yes/no, default: yes)
--if-add-doc-description Add doc description (yes/no, default: yes)
```
</details>

<details>
<summary><strong>Markdown support</strong></summary>
<br>
We also provide markdown support for PageIndex. You can use the `-md_path` flag to generate a tree structure for a markdown file.

```bash
python3 run_pageindex.py --md_path /path/to/your/document.md
```

> Note: in this function, we use "#" to determine node heading and their levels. For example, "##" is level 2, "###" is level 3, etc. Make sure your markdown file is formatted correctly. If your Markdown file was converted from a PDF or HTML, we don't recommend using this function, since most existing conversion tools cannot preserve the original hierarchy. Instead, use our [PageIndex OCR](https://pageindex.ai/blog/ocr), which is designed to preserve the original hierarchy, to convert the PDF to a markdown file and then use this function.
</details>

<!-- 
# ☁️ Improved Tree Generation with PageIndex OCR

This repo is designed for generating PageIndex tree structure for simple PDFs, but many real-world use cases involve complex PDFs that are hard to parse by classic Python tools. However, extracting high-quality text from PDF documents remains a non-trivial challenge. Most OCR tools only extract page-level content, losing the broader document context and hierarchy.

To address this, we introduced PageIndex OCR — the first long-context OCR model designed to preserve the global structure of documents. PageIndex OCR significantly outperforms other leading OCR tools, such as those from Mistral and Contextual AI, in recognizing true hierarchy and semantic relationships across document pages.

- Experience next-level OCR quality with PageIndex OCR at our [Dashboard](https://dash.pageindex.ai/).
- Integrate PageIndex OCR seamlessly into your stack via our [API](https://docs.pageindex.ai/quickstart).

<p align="center">
  <img src="https://github.com/user-attachments/assets/eb35d8ae-865c-4e60-a33b-ebbd00c41732" width="80%">
</p>
-->

---

# 📈 Case Study: PageIndex Leads Finance QA Benchmark

[Mafin 2.5](https://vectify.ai/mafin) is a reasoning-based RAG system for financial document analysis, powered by **PageIndex**. It achieved a state-of-the-art [**98.7% accuracy**](https://vectify.ai/blog/Mafin2.5) on the [FinanceBench](https://arxiv.org/abs/2311.11944) benchmark, significantly outperforming traditional vector-based RAG systems.

PageIndex's hierarchical indexing and reasoning-driven retrieval enable precise navigation and extraction of relevant context from complex financial reports, such as SEC filings and earnings disclosures.

Explore the full [benchmark results](https://github.com/VectifyAI/Mafin2.5-FinanceBench) and our [blog post](https://vectify.ai/blog/Mafin2.5) for detailed comparisons and performance metrics.

<div align="center">
  <a href="https://github.com/VectifyAI/Mafin2.5-FinanceBench">
    <img src="https://github.com/user-attachments/assets/571aa074-d803-43c7-80c4-a04254b782a3" width="70%">
  </a>
</div>

---

# 🧭 Resources

* 🧪 [Cookbooks](https://docs.pageindex.ai/cookbook/vectorless-rag-pageindex): hands-on, runnable examples and advanced use cases.
* 📖 [Tutorials](https://docs.pageindex.ai/doc-search): practical guides and strategies, including *Document Search* and *Tree Search*.
* 📝 [Blog](https://pageindex.ai/blog): technical articles, research insights, and product updates.
* 🔌 [MCP setup](https://pageindex.ai/mcp#quick-setup) & [API docs](https://docs.pageindex.ai/quickstart): integration details and configuration options.

---

## License

This project inherits the license from the original [PageIndex](https://github.com/VectifyAI/PageIndex) project.

---

## Links

- **Main Project**: [BidSmart](https://github.com/youyouhe/BidSmart)
- **Original Framework**: [PageIndex by Vectify AI](https://github.com/VectifyAI/PageIndex)
- **Backend Repository**: [docmind-ai](https://github.com/youyouhe/docmind-ai)

---

© 2025 Based on [PageIndex](https://github.com/VectifyAI/PageIndex) by [Vectify AI](https://vectify.ai)
