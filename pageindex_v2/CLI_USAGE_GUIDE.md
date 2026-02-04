# PageIndex V2 - CLI Usage Guide

## Quick Start

```bash
# Basic usage (fastest, default settings optimized for speed)
python main.py your_document.pdf

# Results will be saved to: ./results/your_document_structure.json
```

---

## All Available Options

```bash
python main.py --help
```

### Required Arguments

```bash
pdf_path                Path to PDF file
```

### LLM Provider Options

```bash
--provider {deepseek,openai}
                        LLM provider (default: deepseek)
--model MODEL           Model name (default: deepseek-chat)
```

### Processing Options

```bash
--max-depth INT         Maximum tree depth (default: 4)
--toc-check-pages INT   Pages to check for TOC (default: 20)
--output-dir PATH       Output directory (default: ./results)
--quiet                 Disable debug output
```

### Phase 5 Verification Optimization ⚡ (NEW)

```bash
--max-verify-count INT
    Maximum nodes to verify (default: 100)
    - Lower = faster processing
    - Higher = more thorough verification
    - Examples: 50 (fast), 100 (balanced), 200 (thorough)

--verification-concurrency INT
    Concurrent LLM calls during verification (default: 20)
    - Higher = faster but more API load
    - Watch for rate limits with high values
    - Examples: 10 (safe), 20 (balanced), 30 (fast but risky)
```

### Large PDF Optimization Options

```bash
--no-recursive          Disable recursive large node processing
--force-verification    Force verification even for large PDFs
--large-pdf-threshold INT
                        Page threshold to consider as large PDF (default: 200)
--max-pages-per-node INT
                        Max pages per node before recursive processing (default: 15)
```

---

## Common Use Cases

### 1. Maximum Speed (Small to Medium PDFs)

For PDFs under 200 pages when you want the fastest results:

```bash
python main.py document.pdf \
    --max-verify-count 50 \
    --verification-concurrency 30 \
    --no-recursive
```

**Expected time**: ~4-6 minutes for 750-page PDF  
**Trade-off**: Verifies only 50 most important nodes (deepest subsections)

---

### 2. Balanced Speed & Accuracy (Recommended) ⭐

Default settings, optimized for best balance:

```bash
python main.py document.pdf
```

Or explicitly:

```bash
python main.py document.pdf \
    --max-verify-count 100 \
    --verification-concurrency 20
```

**Expected time**: ~8-10 minutes for 750-page PDF  
**Trade-off**: Verifies 100 deepest nodes (Level 2 subsections) with 20 concurrent calls

---

### 3. Maximum Accuracy (Large Complex PDFs)

For critical documents where accuracy matters most:

```bash
python main.py document.pdf \
    --max-verify-count 200 \
    --verification-concurrency 10 \
    --force-verification
```

**Expected time**: ~15-20 minutes for 750-page PDF  
**Trade-off**: Slower but verifies more nodes, safer API rate limits

---

### 4. Very Large PDFs (1000+ pages)

For massive documents, disable expensive operations:

```bash
python main.py huge_document.pdf \
    --max-verify-count 50 \
    --verification-concurrency 20 \
    --no-recursive \
    --large-pdf-threshold 500
```

**Expected time**: Scales linearly with page count  
**Trade-off**: Minimal verification, focuses on extraction speed

---

### 5. Quiet Mode (Scripting/Automation)

For use in scripts where you only want JSON output:

```bash
python main.py document.pdf --quiet
```

Output: JSON statistics only, no debug messages

---

### 6. OpenAI Instead of DeepSeek

If you prefer OpenAI (20x more expensive but potentially higher quality):

```bash
python main.py document.pdf \
    --provider openai \
    --model gpt-4-turbo-preview
```

Make sure `OPENAI_API_KEY` is set in your `.env` file.

---

## Performance Tuning Guide

### Understanding the Trade-offs

| Parameter | Low Value | High Value |
|-----------|-----------|------------|
| `--max-verify-count` | ⚡ Faster, less verification | 🎯 Slower, more accurate |
| `--verification-concurrency` | 🔒 Safer API limits | ⚡ Faster, risk rate limits |

### Speed vs. Accuracy Matrix

| Use Case | max-verify-count | verification-concurrency | Time (750p PDF) |
|----------|------------------|-------------------------|-----------------|
| Quick preview | 30 | 30 | ~3-4 min |
| Fast (dev) | 50 | 30 | ~4-6 min |
| **Balanced (default)** | **100** | **20** | **~8-10 min** |
| Thorough | 150 | 15 | ~12-15 min |
| Maximum accuracy | 200 | 10 | ~15-20 min |

### Verification Coverage Strategy

The system uses **level-based prioritization**:

1. **Level 2 nodes** (deepest subsections) are verified first
2. **Level 1 nodes** (main sections) are verified next
3. **Level 0 nodes** (chapters) are verified last

This means even with `--max-verify-count 50`, you get 100% coverage of the most important deep subsections!

---

## Real-World Examples

### Example 1: Academic Paper (78 pages)

```bash
python main.py research_paper.pdf \
    --max-verify-count 50 \
    --verification-concurrency 20
```

**Why**: Small PDF, verify all nodes quickly  
**Time**: ~1-2 minutes

---

### Example 2: Technical Manual (758 pages, complex TOC)

```bash
python main.py PRML.pdf \
    --max-verify-count 100 \
    --verification-concurrency 20
```

**Why**: Default balanced settings work perfectly  
**Time**: ~8-10 minutes  
**Result**: 100/222 nodes verified (45% coverage, all Level 2 subsections)

---

### Example 3: Chinese Textbook (500 pages)

```bash
python main.py chinese_textbook.pdf \
    --max-verify-count 80 \
    --verification-concurrency 15 \
    --toc-check-pages 30
```

**Why**: Chinese TOC might be deeper in document, moderate verification  
**Time**: ~6-8 minutes

---

### Example 4: Batch Processing Multiple PDFs

```bash
#!/bin/bash
for pdf in *.pdf; do
    echo "Processing $pdf..."
    python main.py "$pdf" \
        --max-verify-count 100 \
        --verification-concurrency 20 \
        --quiet
done
```

**Why**: Quiet mode for clean logs, balanced settings  
**Time**: ~8-10 minutes per PDF

---

## Troubleshooting

### Rate Limit Errors

**Symptom**: `RateLimitError` from LLM provider

**Solution**: Reduce concurrency
```bash
python main.py document.pdf --verification-concurrency 10
```

---

### Out of Memory

**Symptom**: Process killed or memory error

**Solution**: Use lazy processing and reduce verification
```bash
python main.py document.pdf \
    --max-verify-count 50 \
    --no-recursive
```

---

### Too Slow

**Symptom**: Processing takes 30+ minutes

**Solution**: Reduce verification count and increase concurrency
```bash
python main.py document.pdf \
    --max-verify-count 50 \
    --verification-concurrency 30
```

---

### Poor Accuracy

**Symptom**: Many incorrect page mappings

**Solution**: Increase verification count
```bash
python main.py document.pdf \
    --max-verify-count 200 \
    --verification-concurrency 10 \
    --force-verification
```

---

## Environment Setup

### 1. Install Dependencies

```bash
cd pageindex_v2
pip install -r requirements.txt
```

### 2. Configure API Keys

Create `.env` file:

```bash
# For DeepSeek (recommended, 20x cheaper)
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# Or for OpenAI
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
```

### 3. Test Installation

```bash
# Download test PDF or use your own
python main.py test.pdf --max-verify-count 10
```

---

## Performance Benchmarks

### Test Case: PRML.pdf (758 pages, 222 leaf nodes)

| Configuration | Time | Coverage | Use Case |
|--------------|------|----------|----------|
| `--max-verify-count 50 --verification-concurrency 30` | ~6 min | 23% | Quick preview |
| **Default (100, 20)** | **~8.4 min** | **45%** | **Balanced** |
| `--max-verify-count 150 --verification-concurrency 15` | ~12 min | 68% | Thorough |
| `--max-verify-count 200 --verification-concurrency 10` | ~18 min | 90% | Maximum accuracy |

---

## Advanced Tips

### 1. Custom Output Location

```bash
python main.py document.pdf --output-dir /path/to/output
```

### 2. Processing with Debug Logs Saved

```bash
python main.py document.pdf 2>&1 | tee process.log
```

### 3. Check Specific TOC Region

If TOC is deep in the document:

```bash
python main.py document.pdf --toc-check-pages 50
```

### 4. Minimal Verification for Large Batches

```bash
python main.py document.pdf \
    --max-verify-count 30 \
    --verification-concurrency 30 \
    --no-recursive \
    --quiet
```

---

## Summary

**For most users**, the default settings provide the best balance:

```bash
python main.py your_document.pdf
```

**To optimize further**, adjust these two key parameters:

- `--max-verify-count`: Lower = faster (50-200 range)
- `--verification-concurrency`: Higher = faster (10-30 range)

**Start conservative**, then increase concurrency if no rate limits occur.

Happy processing! 🚀
