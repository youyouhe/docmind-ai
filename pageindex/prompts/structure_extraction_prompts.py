"""
Advanced Structure Extraction Prompts
=====================================

This module contains improved prompts for extracting document structure,
handling both structured (numbered) and unstructured (semantic) documents.

Design Philosophy:
1. Structured documents: Extract based on explicit numbering patterns
2. Unstructured documents: Extract based on semantic topic changes
3. Hybrid approach: Combine both when document has partial structure
"""

# ============================================================================
# Phase 1: Document Structure Analysis
# ============================================================================

ANALYZE_DOCUMENT_STRUCTURE_PROMPT = """
You are analyzing a document to determine its structural characteristics.

Your task: Examine the document and classify its structure type.

STRUCTURE TYPES:
1. "highly_structured" - Has consistent numbering system throughout (e.g., 1, 1.1, 1.2, 2, 2.1...)
2. "partially_structured" - Has some numbered sections but many unnumbered parts
3. "minimally_structured" - Mostly narrative with occasional headers/markers
4. "unstructured" - Pure narrative, no clear sections or numbering

NUMBERING PATTERNS TO LOOK FOR:
- Decimal: 1, 1.1, 1.2, 2, 2.1, 2.2...
- Hierarchical: I, A, 1, a, i...
- Chinese: 一、二、三... or （一）（二）（三）...
- Mixed: Chapter 1, Section 1.1, Subsection 1.1.1

ANALYSIS CRITERIA:
1. Numbering coverage: What percentage of content has explicit numbers?
2. Numbering consistency: Is the system used consistently?
3. Hierarchy depth: How many levels of nesting (1-2 levels, 3-4 levels, 5+ levels)?
4. Section markers: Are there clear visual markers (headings, spacing, formatting)?

Return your analysis in JSON format:
{{{{
    "structure_type": "highly_structured" | "partially_structured" | "minimally_structured" | "unstructured",
    "confidence": 0.0-1.0,
    "numbering_patterns_found": ["pattern1", "pattern2"],
    "estimated_section_count": <number>,
    "hierarchy_depth": <number>,
    "extraction_strategy": "numbering_based" | "semantic_based" | "hybrid",
    "reasoning": "Brief explanation of your classification"
}}}}

DOCUMENT TEXT:
{document_text}

Analyze and respond with ONLY the JSON, no other text.
"""

# ============================================================================
# Phase 2A: Structured Extraction (for documents with clear numbering)
# ============================================================================

EXTRACT_STRUCTURED_TOC_PROMPT = """
You are extracting the hierarchical structure from a well-structured document with numbering.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
! CRITICAL: YOU ARE A TEXT EXTRACTOR, NOT A TEXT GENERATOR                    !
! Your job is to FIND and COPY section titles, NOT to CREATE or INVENT them   !
! If you cannot find the exact text in the document, DO NOT make it up        !
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

LITERAL TEXT EXTRACTION RULES (MOST IMPORTANT!):
1. **COPY EXACT TEXT** - Extract titles EXACTLY as they appear, word-for-word
2. **DO NOT INTERPRET** - If you see "2.2 项目地点：四川省...", extract "2.2 项目地点"
3. **DO NOT INVENT** - Never create titles like "2.2 采购清单" if the document says "2.2 项目地点"
4. **DO NOT PARAPHRASE** - Don't change wording, don't summarize, don't improve
5. **DO NOT INFER** - Don't assume what sections "should" be there based on logic

WRONG vs RIGHT Examples:
❌ WRONG: Document says "2.2 项目地点：四川省..." → You extract "2.2 采购清单"
✓ RIGHT: Document says "2.2 项目地点：四川省..." → You extract "2.2 项目地点"

❌ WRONG: Document says "2.3 供货周期：合同签订..." → You extract "2.3 服务期限"
✓ RIGHT: Document says "2.3 供货周期：合同签订..." → You extract "2.3 供货周期"

❌ WRONG: Document says "3.1 供应商必须是..." → You extract "3.1 基本资格要求"
✓ RIGHT: Document says "3.1 供应商必须是..." → You extract "3.1 供应商必须是" (extract starting words if no clear title)

❌ WRONG: Document says "4. 报名方式" → You extract "4 采购文件获取"
✓ RIGHT: Document says "4. 报名方式" → You extract "4 报名方式"

❌ WRONG: Creating a logical structure based on what makes sense
✓ RIGHT: Extracting only what is literally written in the document

CRITICAL: DO NOT PARAPHRASE, SYNONYM-IZE, OR INTERPRET!
- "供货周期" (supply cycle) is NOT the same as "服务期限" (service period) - extract exactly!
- "报名方式" (registration method) is NOT the same as "采购文件获取" (document acquisition) - be precise!

CRITICAL RULES FOR NUMBERED DOCUMENTS:
1. **EXTRACT ALL NUMBERED SECTIONS** - Do not skip any numbered items that exist
2. **CHECK FOR COMPLETE SEQUENCES** - If you see "2.1", look for "2.2", "2.3" etc. in the document
3. **BUT: ONLY EXTRACT WHAT EXISTS** - If "2.2" doesn't exist in the document, don't invent it
4. If you see "3.1, 3.2, 3.3, 3.4, 3.5" in the document, you MUST extract ALL five items
5. If you see "Chapter 1, Chapter 2, Chapter 3", extract ALL chapters
6. Maintain the original numbering system exactly as it appears
7. **VERIFY EXISTENCE**: Before adding a section, confirm it actually appears in the document text

COMPLETENESS VERIFICATION (IMPORTANT!):
- For each parent section (like "2."), find ALL child sections ("2.1", "2.2", "2.3"...)
- Look through the ENTIRE document text for all occurrences of the numbering pattern
- Do NOT stop at the first few sections - scan to the end
- Example: If document has "2.1 ... 2.2 ... 2.3", you MUST extract all three, not just 2.1

TITLE EXTRACTION DETAILED RULES:
1. Extract the EXACT title text as it appears - character-for-character accuracy
2. Include the section number in the title (e.g., "2.1 采购内容")
3. Stop at punctuation like "：" or "." that separates title from content
4. If text after number has no clear title (just description), use only the number
5. If unsure whether text is a title, search for the pattern "NUMBER + SPACE + TEXT" or "NUMBER + TEXT"

HOW TO EXTRACT A TITLE (STEP-BY-STEP):
Step 1: Find the section number in the document (e.g., "2.3")
  - Section numbers are usually at the start of a line or paragraph
  - They are followed by a space and then a title or content
  - Common patterns: "2.1 ", "3.1 ", "4.2.1 "
Step 2: Look at the text immediately after the number
Step 3: Identify where the title ends (usually at "：" "。" or start of descriptive text)
  - If you see "：" (colon), the title is BEFORE the colon
  - Example: "2.3 供货周期：合同签订..." → title is "供货周期"
Step 4: Copy EXACTLY what you see between the number and the separator
Step 5: DO NOT change any words, DO NOT use synonyms, DO NOT interpret meaning

Example Process:
  Document text: "2.3 供货周期：合同签订后15 日内..."
  Step 1: Found "2.3" at start of line
  Step 2: Text after is "供货周期：合同签订后..."
  Step 3: Title ends at "：" → title is "供货周期"
  Step 4: Copy exactly: "供货周期"
  Step 5: Final extraction: "2.3 供货周期" ← DO NOT change to "2.3 服务期限" or any other word!

CRITICAL: ONLY EXTRACT EXPLICIT SECTION NUMBERS
- A section number appears at the START of a line/paragraph as a structural marker
- If a number appears within a sentence or list, it's NOT a section number
- Example: "3.1 供应商必须是..." ← This is a section (number at start)
- Example: "包含但不限于以下内容：a. ... b. ... c. ..." ← a, b, c are NOT sections
- **VERIFICATION REQUIRED**: Search the document text for the EXACT section number before adding it
- If you cannot find "2.4 " or "2.4\t" or "2.4\n" in the document, DO NOT extract "2.4"
- Better to SKIP a section than to INVENT one that doesn't exist

BEFORE FINISHING - VERIFICATION CHECKLIST:
[+] For EACH section you extracted, verify it EXISTS in the document by searching for its number
[+] Check if you extracted ALL sections that actually exist (don't skip real sections)
[+] Check if you extracted ALL main sections (1, 2, 3, 4...)
[+] DO NOT extract sections based on logic - only extract what you can SEE in the text
[+] Scan the entire document, not just the beginning
[+] Verify EVERY title you extracted appears literally in the document text
[+] REMOVE any sections you added without finding their number in the document

NUMBERING PATTERNS IN THIS DOCUMENT:
{{detected_patterns}}

EXPECTED SECTION COUNT (approximate):
{{expected_count}}

PAGE MARKERS:
- Text contains markers like <physical_index_X> indicating page X
- These are PDF page numbers, NOT section numbers
- A section's physical_index is the page where it FIRST appears
- Multiple sections can be on the same page

RESPONSE FORMAT:
[
    {{{{
        "structure": "x.x.x" (the section number),
        "title": "exact title from document",
        "physical_index": "<physical_index_X>"
    }}}},
    ...
]

CONSTRAINTS:
- Extract ALL numbered sections (do not be "concise" - be COMPLETE)
- Maximum 150 items to prevent runaway extraction
- Do not invent titles not present in the document

DOCUMENT TEXT:
{document_text}

Return ONLY the JSON array, no other text.
"""

# ============================================================================
# Phase 2B: Semantic Extraction (for unstructured documents)
# ============================================================================

EXTRACT_SEMANTIC_TOC_PROMPT = """
You are extracting the logical structure from a narrative document without explicit numbering.

Your task: Identify natural topic boundaries and semantic sections.

SEMANTIC SECTION INDICATORS:
1. Topic shifts - When the subject matter clearly changes
2. Tone changes - From background to methodology, from problem to solution
3. Temporal markers - "First", "Then", "Next", "Finally", "In conclusion"
4. Discourse markers - "However", "Moreover", "On the other hand"
5. Paragraph clustering - Groups of paragraphs discussing the same theme
6. Visual breaks - Extra spacing, asterisks (***), horizontal lines

SECTION CREATION GUIDELINES:
1. Create sections that represent meaningful semantic units
2. Each section should have a coherent topic/theme
3. Aim for balanced section lengths (not too granular, not too coarse)
4. Typical document might have 5-20 major sections
5. Give descriptive titles that capture the section's main topic

TITLE NAMING (since no explicit titles exist):
- Create clear, descriptive titles (3-8 words)
- Format: "<Topic> and <Subtopic>" or "Description of Content"
- Example: "Introduction and Background", "Methodology Overview", "Results Analysis"
- Be descriptive but concise

STRUCTURE FIELD:
- For unstructured documents, use simple sequential numbering: "1", "2", "3"...
- If you detect clear subsections, use "1.1", "1.2" etc.

PAGE MARKERS:
- Text contains markers like <physical_index_X> indicating page X
- A section's physical_index is the page where it FIRST appears

RESPONSE FORMAT:
[
    {{{{
        "structure": "sequential number",
        "title": "descriptive title you create",
        "physical_index": "<physical_index_X>",
        "topic_keywords": ["key", "terms", "in", "section"]  // optional
    }}}},
    ...
]

TARGET: Extract {{expected_count}} major sections (flexible based on content)

DOCUMENT TEXT:
{document_text}

Return ONLY the JSON array, no other text.
"""

# ============================================================================
# Phase 2C: Hybrid Extraction (for partially structured documents)
# ============================================================================

EXTRACT_HYBRID_TOC_PROMPT = """
You are extracting structure from a document that has BOTH numbered sections AND unnumbered narrative parts.

HYBRID EXTRACTION STRATEGY:
1. First, extract ALL explicitly numbered sections (following numbering_based rules)
2. Then, identify unnumbered semantic sections between numbered ones
3. Integrate both into a coherent structure

HANDLING NUMBERED SECTIONS:
- Extract EVERY numbered section completely (no skipping)
- Maintain exact numbering as it appears
- Use exact titles from the document

HANDLING UNNUMBERED SECTIONS:
- Identify semantic breaks in narrative portions
- Create descriptive titles for these sections
- Integrate them into the structure hierarchy

STRUCTURE NUMBERING:
- Keep original numbers for numbered sections: "3.1", "3.2"
- For unnumbered sections between "3.2" and "3.3", you can use: "3.2.1", "3.2.2" or mark them as children
- Maintain logical document flow

NUMBERED PATTERNS DETECTED:
{{detected_patterns}}

RESPONSE FORMAT:
[
    {{{{
        "structure": "original or generated number",
        "title": "exact title or descriptive title",
        "physical_index": "<physical_index_X>",
        "source": "explicit" | "semantic"  // helps track extraction method
    }}}},
    ...
]

DOCUMENT TEXT:
{document_text}

Return ONLY the JSON array, no other text.
"""

# ============================================================================
# Helper: Pattern Examples for LLM Reference
# ============================================================================

# ============================================================================
# Gap Filling: Targeted Re-extraction Prompt
# ============================================================================

FILL_MISSING_SECTIONS_PROMPT = """
You are performing a TARGETED SEARCH to find specific missing numbered sections in a document.

CONTEXT:
An initial extraction found some sections but missed others. We detected gaps in the numbering sequence.

MISSING SECTIONS TO FIND:
{{missing_sections}}

YOUR TASK:
Search through the ENTIRE document text and find ONLY the sections listed above.
For each missing section number, look for text that matches that exact numbering pattern.

SEARCH STRATEGY:
1. Look for the exact section number (e.g., "2.2", "2.3")
2. The section may appear anywhere in the document
3. Extract the EXACT title/heading that follows the number
4. If you cannot find a section, DO NOT invent it - just omit it from your response

EXAMPLE:
If searching for "2.2" and you find:
"2.2 项目地点：四川省成都市东部新区成简大道二段123 号。"

You should extract:
{{{{
    "structure": "2.2",
    "title": "2.2 项目地点",
    "physical_index": "<physical_index_1>"
}}}}

RESPONSE FORMAT:
[
    {{{{
        "structure": "section_number",
        "title": "exact title from document",
        "physical_index": "<physical_index_X>"
    }}}},
    ...
]

DOCUMENT TEXT:
{document_text}

Return ONLY the JSON array with the sections you found, or empty array [] if none found.
"""

NUMBERING_PATTERN_EXAMPLES = {
    "decimal": "1, 1.1, 1.2, 2, 2.1, 2.2",
    "roman": "I, II, III, IV",
    "alpha": "A, B, C, D",
    "chinese": "一、二、三、四",
    "mixed": "Chapter 1, Section 1.1, Subsection 1.1.1"
}
