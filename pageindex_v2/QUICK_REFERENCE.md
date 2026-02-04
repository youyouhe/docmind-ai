# PageIndex V2 - Quick Reference Card

## 🚀 Common Commands

### Default (Recommended for most users)
```bash
python main.py document.pdf
```
Time: ~8 minutes for 750-page PDF | Coverage: 45% (100 deepest nodes)

---

### Fast Mode
```bash
python main.py document.pdf --max-verify-count 50 --verification-concurrency 30
```
Time: ~6 minutes for 750-page PDF | Coverage: 23% (50 deepest nodes)

---

### Thorough Mode
```bash
python main.py document.pdf --max-verify-count 200 --verification-concurrency 10
```
Time: ~15 minutes for 750-page PDF | Coverage: 90% (200 nodes)

---

### Quiet Mode (for scripts)
```bash
python main.py document.pdf --quiet
```
Same speed as default | JSON output only

---

## ⚙️ Key Parameters

| Parameter | Default | Description | Impact |
|-----------|---------|-------------|--------|
| `--max-verify-count` | 100 | Nodes to verify | Lower = faster ⚡ |
| `--verification-concurrency` | 20 | Parallel LLM calls | Higher = faster ⚡ |
| `--provider` | deepseek | LLM provider | deepseek = 20x cheaper 💰 |
| `--max-depth` | 4 | Tree depth limit | Higher = more detail 📊 |
| `--quiet` | false | Disable debug logs | Use for automation 🤖 |

---

## 🎯 Use Cases

### Academic Papers (< 100 pages)
```bash
python main.py paper.pdf --max-verify-count 50
```

### Technical Manuals (200-1000 pages)
```bash
python main.py manual.pdf  # Use defaults
```

### Massive Books (1000+ pages)
```bash
python main.py book.pdf --max-verify-count 50 --no-recursive
```

### Batch Processing
```bash
for pdf in *.pdf; do
    python main.py "$pdf" --quiet
done
```

---

## 📊 Performance Matrix

| PDF Size | max-verify-count | Time Estimate |
|----------|------------------|---------------|
| < 100 pages | 50 | 1-2 min |
| 100-500 pages | 100 | 5-10 min |
| 500-1000 pages | 100-150 | 10-15 min |
| 1000+ pages | 50-100 | 15-30 min |

---

## 🔧 Troubleshooting

### Rate Limit Error
**Fix**: Reduce concurrency
```bash
python main.py document.pdf --verification-concurrency 10
```

### Too Slow
**Fix**: Reduce verification count
```bash
python main.py document.pdf --max-verify-count 50
```

### Out of Memory
**Fix**: Use lazy processing
```bash
python main.py document.pdf --no-recursive --max-verify-count 50
```

---

## 📖 Documentation

- **Full CLI Guide**: [CLI_USAGE_GUIDE.md](./CLI_USAGE_GUIDE.md)
- **Optimization Report**: [FINAL_OPTIMIZATION_REPORT.md](./FINAL_OPTIMIZATION_REPORT.md)
- **Main README**: [README.md](./README.md)

---

## 💡 Pro Tips

1. **Start with defaults** - they're optimized for most use cases
2. **Increase concurrency carefully** - watch for rate limits
3. **Use quiet mode for automation** - cleaner logs
4. **Lower verification count for speed** - still covers deepest nodes
5. **DeepSeek is 20x cheaper than OpenAI** - use it unless quality issues

---

## 🎓 Understanding Verification

The system uses **level-based prioritization**:

```
Priority 1: Level 2 nodes (deepest subsections) ← Most important
Priority 2: Level 1 nodes (main sections)
Priority 3: Level 0 nodes (chapters)
```

With `--max-verify-count 100`, you get:
- ✅ 100% coverage of Level 2 (deepest subsections)
- ✅ Partial coverage of Level 1
- ❌ Minimal coverage of Level 0 (chapters are usually obvious)

This is why even 50 nodes gives great results!

---

## 🔍 Quick Help
```bash
python main.py --help
```
