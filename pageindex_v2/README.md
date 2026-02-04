# PageIndex V2 - Enhanced Document Structure Extraction

Enhanced version of PageIndex with 5 key improvements:

## 🚀 Key Features

### 1. DeepSeek Support
- Cost-effective alternative to OpenAI (20x cheaper)
- Native JSON mode support
- Async API calls with retry mechanism

### 2. Chinese Document Optimization
- TOC detection for Chinese documents (目录, 第一章, etc.)
- Section numbering: 1.1, 第一章, 第一节
- Mixed Chinese-English support

### 3. 4-Level Hierarchy Constraint
- Prevents infinite nesting
- Automatic merge of deep nodes
- Professional book-like structure

### 4. Table Structure Preservation
- pdfplumber for table detection
- Markdown format output
- Table context in index

### 5. Detailed Debug Output
- Phase-by-phase progress
- LLM request/response logging
- Verification statistics

## 📦 Installation

```bash
cd pageindex_v2
pip install -r requirements.txt
```

## ⚙️ Configuration

Create `.env` file:
```bash
# DeepSeek (recommended)
DEEPSEEK_API_KEY=sk-your-key-here

# Or OpenAI
OPENAI_API_KEY=sk-your-key-here
```

## 🎯 Usage

```bash
# Basic usage with DeepSeek (default, optimized settings)
python main.py your_document.pdf

# Fast processing (50 nodes, ~6 minutes for 750-page PDF)
python main.py your_document.pdf \
    --max-verify-count 50 \
    --verification-concurrency 30

# Thorough processing (200 nodes, ~15 minutes for 750-page PDF)
python main.py your_document.pdf \
    --max-verify-count 200 \
    --verification-concurrency 10

# Quiet mode (for scripting)
python main.py your_document.pdf --quiet
```

**📖 For detailed CLI options and performance tuning, see [CLI_USAGE_GUIDE.md](./CLI_USAGE_GUIDE.md)**

## 📁 Project Structure

```
pageindex_v2/
├── core/
│   ├── llm_client.py       # Multi-provider LLM support
│   └── pdf_parser.py       # PDF extraction with tables
├── phases/
│   ├── toc_detector.py     # TOC page detection
│   ├── toc_extractor.py    # Structure extraction
│   ├── page_mapper.py      # Physical page mapping
│   ├── verifier.py         # Dual verification
│   └── tree_builder.py     # 4-level tree building
├── utils/
│   └── helpers.py          # JSON, tree operations
├── main.py                 # Main orchestrator
└── requirements.txt
```

## 🔄 Processing Pipeline

```
PDF Input
  ↓
Phase 1: PDF Parser (tables preserved)
  ↓
Phase 2: TOC Detector (Chinese support)
  ↓
Phase 3: TOC Extractor (structure codes)
  ↓
Phase 4: Page Mapper (<physical_index_X>)
  ↓
Phase 5: Verifier (dual validation)
  ↓
Phase 6: Tree Builder (4-level limit)
  ↓
JSON Tree Output
```

## 📊 Output Format

```json
{
  "source_file": "document.pdf",
  "total_pages": 15,
  "statistics": {
    "root_nodes": 3,
    "total_nodes": 12,
    "max_depth": 3
  },
  "verification_accuracy": 0.92,
  "structure": [
    {
      "title": "第一章",
      "start_index": 1,
      "end_index": 5,
      "node_id": "0000",
      "nodes": [
        {
          "title": "1.1 节",
          "start_index": 2,
          "end_index": 4,
          "node_id": "0001"
        }
      ]
    }
  ]
}
```

## 🔧 Module Details

### Core Modules

**LLM Client** (`core/llm_client.py`)
- Multi-provider: DeepSeek, OpenAI
- Async with semaphore control
- Debug logging
- JSON mode support

**PDF Parser** (`core/pdf_parser.py`)
- pdfplumber for tables
- PyMuPDF fallback
- <physical_index_X> tags
- Chinese token estimation

### Phase Modules

**TOC Detector** (`phases/toc_detector.py`)
- 20-page TOC search
- Chinese/English patterns
- Page number detection

**TOC Extractor** (`phases/toc_extractor.py`)
- Structure code assignment (1, 1.1, 1.1.1)
- Chinese section recognition
- Large TOC chunking

**Page Mapper** (`phases/page_mapper.py`)
- <physical_index_X> matching
- Offset correction
- Fallback strategies

**Verifier** (`phases/verifier.py`)
- Dual validation:
  1. Title existence on page
  2. Title at page start
- Concurrent checking
- Auto-fix incorrect items

**Tree Builder** (`phases/tree_builder.py`)
- 4-level depth constraint
- End index calculation
- Node ID assignment
- Preface auto-detection

## 🆚 Comparison with Original PageIndex

| Feature | PageIndex | PageIndex V2 |
|---------|-----------|--------------|
| LLM | OpenAI only | DeepSeek + OpenAI |
| Chinese | Limited | Full support |
| Depth | Unlimited | 4-level limit |
| Tables | Not preserved | Markdown format |
| Debug | Basic | Detailed per-phase |
| Async | asyncio | asyncio + semaphore |
| **Speed** | **Not optimized** | **⚡ 5x faster (40min → 8min)** |

## ⚡ Performance

**Latest Optimization (Feb 2026)**: Phase 5 verification optimized from 40 minutes to 6.7 minutes (6x speedup)

### Benchmark: PRML.pdf (758 pages, 222 leaf nodes)

| Mode | Time | Coverage | Command |
|------|------|----------|---------|
| Fast | ~6 min | 23% (50 nodes) | `--max-verify-count 50 --verification-concurrency 30` |
| **Balanced** | **~8.4 min** | **45% (100 nodes)** | Default settings ⭐ |
| Thorough | ~15 min | 90% (200 nodes) | `--max-verify-count 200 --verification-concurrency 10` |

**Key Optimizations**:
1. Lazy parsing - only parse TOC-referenced pages (96.3% parsing time saved)
2. Level-based verification - verify deepest nodes first (100% Level 2 coverage)
3. Configurable concurrency - 20 parallel LLM calls by default
4. Smart sampling - skip redundant position checks

See [FINAL_OPTIMIZATION_REPORT.md](./FINAL_OPTIMIZATION_REPORT.md) for details.

## 📝 License

MIT License - Enhanced version based on PageIndex concepts.
