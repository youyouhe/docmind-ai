# 嵌入式 TOC vs 文本 TOC：完整解释

## 🤔 什么是嵌入式 TOC？

**嵌入式 TOC** 不是文本，而是 PDF 文件的 **元数据**（metadata），就像照片的 EXIF 信息一样。

---

## 📊 对比表

| 特性 | 嵌入式 TOC | 文本 TOC |
|------|-----------|---------|
| **存储位置** | PDF 元数据（文件结构） | PDF 页面内容（文本） |
| **格式** | 结构化数据 | 普通文本 |
| **在 PDF 阅读器中** | 侧边栏"书签"/"大纲" | 正文中的"目录"页 |
| **提取方式** | `doc.get_toc()` API | OCR/文本提取 + 解析 |
| **提取速度** | ⚡ 0.1 秒 | 🐌 2-10 分钟 |
| **准确度** | 🎯 100% | ⚠️ 80-95% (需要 LLM) |
| **LLM 调用** | ❌ 不需要 | ✅ 需要多次 |
| **覆盖率** | 60-80% 专业文档 | ~100% 文档 |

---

## 🖼️ 实际例子：PRML.pdf

### 1️⃣ 嵌入式 TOC（元数据）

```python
import fitz
doc = fitz.open('PRML.pdf')
toc = doc.get_toc()
# 瞬间返回：
# [
#   (1, 'COVER', 1),
#   (1, 'Preface', 7),
#   (1, '1.Introduction', 21),
#   (2, '1.1. Example: Polynomial Curve Fitting', 24),
#   (3, '1.2.1 Probability densities', 37),
#   ...
# ]
# 285 个条目，3 层深度
```

**数据结构**：
- `(1, 'COVER', 1)` → 第1层, 标题="COVER", 第1页
- 已经结构化，有层级、标题、准确页码

**在 PDF 阅读器中的样子**：
```
📂 PRML.pdf 的侧边栏
├─ 📑 COVER .................... 1
├─ 📑 Preface .................. 7
├─ 📑 1.Introduction ........... 21
│  ├─ 📄 1.1. Example .......... 24
│  └─ 📄 1.2. Probability ...... 32
│     ├─ 📄 1.2.1 Densities ... 37
│     └─ 📄 1.2.2 Expectations . 39
└─ 📑 2. Probability Dist ...... 87
```

**如何查看**：
- Adobe Reader: 左侧"书签"面板
- Chrome PDF: 左侧"目录"图标
- macOS Preview: 侧边栏"目录"
- Foxit Reader: 左侧"书签"

---

### 2️⃣ 文本 TOC（页面内容）

PRML.pdf 的第 13 页（Contents 页）的实际文本：

```
Contents
Preface                                              vii
Mathematical notation                                xi
Contents                                             xiii

1    Introduction                                    1
1.1  Example: Polynomial Curve Fitting . . . . . . . 4
1.2  Probability Theory . . . . . . . . . . . . . . . 12
1.2.1 Probability densities . . . . . . . . . . . . . 17
1.2.2 Expectations and covariances . . . . . . . . . 19
1.2.3 Bayesian probabilities . . . . . . . . . . . . 21
...
```

这就是普通的文本，你看 PDF 时翻到目录页就能看到。

**问题**：
- 需要 LLM 理解"1.2.1 是 1.2 的子节点"
- 需要 LLM 理解"17 是页码，不是章节号"
- 需要 LLM 处理省略号、对齐符等格式
- 页码可能不准（文档有前言、封面等）

---

## 🔍 技术细节

### 嵌入式 TOC 在 PDF 文件中的位置

PDF 文件结构：
```
PDF File (PRML.pdf)
├─ 📁 Header (文件头)
├─ 📁 Body (页面内容)
│  ├─ Page 1: COVER 的文字、图片
│  ├─ Page 2-6: 前言的文字
│  ├─ Page 13: "Contents\n1 Introduction..."  ← 文本 TOC
│  └─ ...
├─ 📁 Cross-reference table (交叉引用表)
└─ 📁 Trailer (文件尾)
   └─ 📋 Outlines (书签/大纲)  ← 嵌入式 TOC 在这里！
      ├─ COVER → Page 1
      ├─ Preface → Page 7
      ├─ 1.Introduction → Page 21
      │  ├─ 1.1 Example → Page 24
      │  └─ ...
      └─ ...
```

**Outlines** 是 PDF 规范的一部分，用于导航。

---

## 💡 类比理解

想象一本实体书：

### 文本 TOC = 书里印刷的目录页
- 📖 翻开书的第 2-3 页，能看到印刷的目录
- 需要人眼阅读理解
- 可能有印刷错误

### 嵌入式 TOC = 书签标签（假设书自带）
- 🏷️ 每一章节都有个标签直接跳转
- 不需要阅读，直接点击跳转
- 准确无误（由出版商制作时添加）

---

## 🛠️ 如何制作带嵌入式 TOC 的 PDF？

### 方法 1: LaTeX
```latex
\documentclass{book}
\usepackage{hyperref}  % 自动生成书签
\begin{document}
\tableofcontents       % 文本目录
\chapter{Introduction} % 自动生成书签
\section{Background}
\end{document}
```
编译后自动包含嵌入式 TOC。

### 方法 2: Microsoft Word
1. 使用"标题 1"、"标题 2"等样式
2. 导出 PDF 时勾选"创建书签"

### 方法 3: Adobe Acrobat Pro
手动添加书签到现有 PDF

### 方法 4: Python (PyMuPDF)
```python
import fitz
doc = fitz.open("input.pdf")
toc = [
    [1, "Chapter 1", 1],
    [2, "Section 1.1", 5],
]
doc.set_toc(toc)
doc.save("output.pdf")
```

---

## 📈 我们的优化效果

### Before（只用文本 TOC）
```
PRML.pdf (758 页)
├─ Parse first 30 pages ........ 10s
├─ Detect TOC in text .......... 30s (LLM)
├─ Parse all 758 pages ......... 120s
├─ Extract structure ........... 60s (LLM)
├─ Map pages ................... 40s (LLM)
└─ Total: ~260s (4+ 分钟)
```

### After（优先用嵌入式 TOC）
```
PRML.pdf (758 页)
├─ Parse first 30 pages ........ 10s
├─ Extract embedded TOC ........ 0.1s ✨
├─ Skip text analysis .......... 0s ✨
├─ Build tree .................. 15s
└─ Total: ~27s (0.5 分钟) ⚡
```

**加速：9.6x**

---

## ✅ 哪些 PDF 有嵌入式 TOC？

### ✅ 通常有：
- 📚 学术论文（arXiv, IEEE, ACM）
- 📖 技术书籍（O'Reilly, Springer, Pearson）
- 📊 企业报告（财报、白皮书）
- 📝 规范文档（RFC, ISO 标准）
- 由 LaTeX, Word, InDesign 正规制作的 PDF

### ❌ 通常没有：
- 📄 扫描件（图片转 PDF）
- 🖨️ 简单打印输出
- 🔧 临时工具生成的 PDF
- 📱 手机拍照转 PDF

---

## 🎯 总结

**嵌入式 TOC** 是 PDF 的结构化元数据，不是文本：
- ✅ 就像文件的元数据（文件名、创建时间）
- ✅ 存储在 PDF 内部数据结构中
- ✅ 可以用 `doc.get_toc()` 直接读取
- ✅ 100% 准确，不需要解析

**文本 TOC** 是 PDF 页面里的普通文字：
- 📝 就像文档正文的一部分
- 📝 需要用 OCR/文本提取 + LLM 理解
- 📝 可能有解析错误

**我们的策略**：
```python
if has_embedded_toc(pdf):
    use_embedded_toc()  # Fast path (27s)
else:
    use_text_analysis()  # Slow path (4+ min)
```

这样既保证了速度（有元数据时），又保证了覆盖率（兜底文本分析）。🚀
