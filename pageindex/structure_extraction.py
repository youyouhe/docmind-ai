"""
Enhanced Structure Extraction Module
====================================

Implements two-phase structure extraction:
1. Analyze document structure type
2. Apply appropriate extraction strategy (structured/semantic/hybrid)
"""

import json
import re
import logging
from typing import List, Dict, Tuple, Optional
from pageindex.prompts.structure_extraction_prompts import (
    ANALYZE_DOCUMENT_STRUCTURE_PROMPT,
    EXTRACT_STRUCTURED_TOC_PROMPT,
    EXTRACT_SEMANTIC_TOC_PROMPT,
    EXTRACT_HYBRID_TOC_PROMPT,
    FILL_MISSING_SECTIONS_PROMPT,
    NUMBERING_PATTERN_EXAMPLES
)


def extract_json_object_first(content):
    """
    Extract JSON by prioritizing objects {...} over arrays [...].
    This is specifically for structure analysis which expects a dict.

    Args:
        content: Raw text content

    Returns:
        dict: Parsed JSON object, or None if extraction fails
    """
    def find_matching_bracket(text, start_char, end_char):
        """Find matching bracket starting from first occurrence of start_char."""
        start_idx = text.find(start_char)
        if start_idx == -1:
            return None

        count = 0
        in_string = False
        escape_next = False

        for i in range(start_idx, len(text)):
            char = text[i]

            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if not in_string:
                if char == start_char:
                    count += 1
                elif char == end_char:
                    count -= 1
                    if count == 0:
                        return text[start_idx:i+1]

        return None

    try:
        # Try to find JSON object {...} FIRST (prioritized for structure analysis)
        json_str = find_matching_bracket(content, '{', '}')
        if json_str:
            json_str = json_str.replace('None', 'null')
            result = json.loads(json_str)
            if isinstance(result, dict):
                return result

        return None
    except Exception as e:
        return None


def analyze_document_structure(document_text: str, model=None) -> Dict:
    """
    Phase 1: Analyze document to determine its structure type.

    Returns:
        {
            "structure_type": "highly_structured" | "partially_structured" | "minimally_structured" | "unstructured",
            "confidence": 0.0-1.0,
            "numbering_patterns_found": [...],
            "estimated_section_count": int,
            "hierarchy_depth": int,
            "extraction_strategy": "numbering_based" | "semantic_based" | "hybrid"
        }
    """
    from pageindex.utils import ChatGPT_API

    # Sample the document (first 3000 chars for quick analysis)
    sample_text = document_text[:3000] if len(document_text) > 3000 else document_text

    prompt = ANALYZE_DOCUMENT_STRUCTURE_PROMPT.format(document_text=sample_text)

    try:
        response = ChatGPT_API(model=model, prompt=prompt)

        # Debug: print LLM response
        print(f"[DEBUG] Structure analysis LLM response (first 500 chars):\n{response[:500]}")

        # Try to parse JSON response with robust extraction
        from pageindex.utils import extract_json_markdown_block, extract_json_bracket_matching

        # Try multiple extraction methods
        analysis = None

        # Method 1: Markdown code block
        analysis = extract_json_markdown_block(response)
        if analysis and isinstance(analysis, dict):
            print(f"[DEBUG] Successfully extracted via markdown block")

        # Method 2: Object-first extraction (for structure analysis)
        if not analysis or not isinstance(analysis, dict):
            analysis = extract_json_object_first(response)
            if analysis:
                print(f"[DEBUG] Successfully extracted via object-first extraction")

        # Method 3: Bracket matching (original, may return list)
        if not analysis or not isinstance(analysis, dict):
            analysis = extract_json_bracket_matching(response)
            if analysis and isinstance(analysis, dict):
                print(f"[DEBUG] Successfully extracted via bracket matching")

        # Method 4: Direct JSON parsing
        if not analysis or not isinstance(analysis, dict):
            try:
                analysis = json.loads(response.strip())
                if isinstance(analysis, dict):
                    print(f"[DEBUG] Successfully extracted via direct JSON parsing")
            except Exception as parse_error:
                print(f"[DEBUG] Direct JSON parsing failed: {parse_error}")
                pass

        # Validate we got a dict with required keys
        if analysis and isinstance(analysis, dict) and 'structure_type' in analysis:
            logging.info(f"[Structure Analysis] Type: {analysis.get('structure_type')}, "
                        f"Strategy: {analysis.get('extraction_strategy')}, "
                        f"Confidence: {analysis.get('confidence')}")
            return analysis
        else:
            raise ValueError(f"Invalid analysis response: missing required keys or wrong type. Got: {type(analysis)}")
        
    except Exception as e:
        logging.warning(f"Structure analysis failed: {e}, falling back to pattern detection")
        print(f"[DEBUG] Analysis error: {str(e)[:200]}")
        # Fallback to rule-based detection
        return detect_structure_patterns(document_text)


def detect_structure_patterns(text: str) -> Dict:
    """
    Fallback: Rule-based structure detection when LLM analysis fails.
    """
    patterns_found = []
    
    # Detect various numbering patterns
    decimal_pattern = r'\n\s*\d+\.\d+\s+[\u4e00-\u9fa5\w]'  # 1.1, 2.3
    if len(re.findall(decimal_pattern, text[:2000])) >= 3:
        patterns_found.append("decimal")
    
    chapter_pattern = r'(第[一二三四五六七八九十]+章|Chapter\s+\d+|CHAPTER\s+\d+)'
    if re.search(chapter_pattern, text[:2000]):
        patterns_found.append("chapter")
    
    section_pattern = r'\n\s*\d+\.\s+[\u4e00-\u9fa5\w]'  # 1. , 2. 
    section_count = len(re.findall(section_pattern, text[:2000]))
    if section_count >= 3:
        patterns_found.append("numbered_sections")
    
    # Determine structure type based on patterns
    if len(patterns_found) >= 2 and section_count >= 5:
        structure_type = "highly_structured"
        strategy = "numbering_based"
        estimated_count = section_count * 3  # Rough estimate
    elif len(patterns_found) >= 1:
        structure_type = "partially_structured"
        strategy = "hybrid"
        estimated_count = section_count * 2
    else:
        structure_type = "unstructured"
        strategy = "semantic_based"
        estimated_count = 10  # Default guess
    
    return {
        "structure_type": structure_type,
        "confidence": 0.7,  # Lower confidence for rule-based
        "numbering_patterns_found": patterns_found,
        "estimated_section_count": estimated_count,
        "hierarchy_depth": 2 if "decimal" in patterns_found else 1,
        "extraction_strategy": strategy,
        "reasoning": f"Rule-based detection found patterns: {patterns_found}"
    }


def extract_structure_enhanced(document_text: str, 
                               structure_analysis: Dict,
                               model=None,
                               logger=None) -> List[Dict]:
    """
    Phase 2: Extract structure using appropriate strategy based on analysis.
    
    Args:
        document_text: Full document text with page markers
        structure_analysis: Result from analyze_document_structure()
        model: LLM model name
        logger: Logger instance
        
    Returns:
        List of structure items with title, structure, physical_index
    """
    from pageindex.utils import ChatGPT_API_with_finish_reason
    from pageindex.utils import extract_json_v2
    
    strategy = structure_analysis.get('extraction_strategy', 'numbering_based')
    patterns = structure_analysis.get('numbering_patterns_found', [])
    expected_count = structure_analysis.get('estimated_section_count', 20)
    
    # DEBUG: Check document text
    print(f"[DEBUG] document_text length: {len(document_text)} chars")
    print(f"[DEBUG] document_text preview: {document_text[:200]}")
    
    if logger:
        logger.info(f"[Enhanced Extraction] Using strategy: {strategy}")
        logger.info(f"[Enhanced Extraction] Patterns: {patterns}")
        logger.info(f"[Enhanced Extraction] Expected count: {expected_count}")
    
    # Choose appropriate prompt
    if strategy == 'numbering_based':
        prompt_template = EXTRACT_STRUCTURED_TOC_PROMPT
        prompt = prompt_template.format(
            detected_patterns=", ".join(patterns) if patterns else "Standard decimal numbering",
            expected_count=expected_count,
            document_text=document_text
        )
    elif strategy == 'semantic_based':
        prompt_template = EXTRACT_SEMANTIC_TOC_PROMPT
        prompt = prompt_template.format(
            expected_count=expected_count,
            document_text=document_text
        )
    else:  # hybrid
        prompt_template = EXTRACT_HYBRID_TOC_PROMPT
        prompt = prompt_template.format(
            detected_patterns=", ".join(patterns) if patterns else "Mixed numbering",
            document_text=document_text
        )
    
    # DEBUG: Verify prompt encoding
    print(f"[DEBUG] Prompt length: {len(prompt)} chars")
    print(f"[DEBUG] Document text in prompt (first 200 chars): {prompt[prompt.find('DOCUMENT TEXT:'):prompt.find('DOCUMENT TEXT:')+200] if 'DOCUMENT TEXT:' in prompt else 'NOT FOUND'}")
    
    # Call LLM
    print(f"\n[Enhanced Extraction] Strategy: {strategy}, Expected items: ~{expected_count}")
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    
    # Debug output
    print(f"[Enhanced Extraction] Response length: {len(response)} chars")
    print(f"[Enhanced Extraction] First 500 chars:\n{response[:500]}\n")
    
    if finish_reason != 'finished':
        raise Exception(f'LLM finish reason: {finish_reason}')
    
    # Extract JSON
    extracted_structure = extract_json_v2(response, expected_schema='toc', model=model)
    
    # Handle None case
    if extracted_structure is None:
        extracted_structure = []
    
    print(f"[Enhanced Extraction] Extracted {len(extracted_structure)} items")
    
    # Validate completeness for structured documents
    if strategy == 'numbering_based' and extracted_structure:
        extracted_structure = validate_and_complete_structure(
            extracted_structure, 
            document_text,
            patterns,
            model,
            logger
        )
    
    return extracted_structure if extracted_structure else []


def validate_and_complete_structure(extracted: List[Dict],
                                    document_text: str,
                                    patterns: List[str],
                                    model=None,
                                    logger=None) -> List[Dict]:
    """
    Validate extracted structure for completeness, especially for numbered documents.
    Detect missing sections and attempt to fill gaps with targeted re-extraction.
    """
    if not extracted:
        return extracted
    
    # Extract all structure numbers
    structure_numbers = [item.get('structure', '') for item in extracted]
    
    # Check for sequence gaps in numbered sections
    gaps_found = []
    
    # Check decimal patterns (1.1, 1.2, 1.3...)
    decimal_sections = {}
    for num in structure_numbers:
        if re.match(r'^\d+\.\d+$', num):
            parts = num.split('.')
            parent = parts[0]
            child = int(parts[1])
            if parent not in decimal_sections:
                decimal_sections[parent] = []
            decimal_sections[parent].append(child)
    
    # Detect gaps
    for parent, children in decimal_sections.items():
        children.sort()
        for i in range(len(children) - 1):
            if children[i+1] - children[i] > 1:
                for missing in range(children[i] + 1, children[i+1]):
                    gaps_found.append(f"{parent}.{missing}")
    
    if gaps_found:
        logging.warning(f"[Structure Validation] Potential gaps detected: {gaps_found}")
        print(f"\n[!] [Gap Detection] Missing sections found: {', '.join(gaps_found)}")
        print(f"    Attempting targeted re-extraction to fill gaps...")
        
        # Attempt to fill gaps with targeted extraction
        try:
            filled_sections = fill_missing_sections(
                missing_sections=gaps_found,
                document_text=document_text,
                model=model
            )
            
            if filled_sections:
                print(f"[+] [Gap Filling] Successfully found {len(filled_sections)} missing sections")
                # Merge filled sections into extracted structure
                extracted.extend(filled_sections)
                # Sort by structure number for proper ordering
                extracted = sorted(extracted, key=lambda x: parse_section_number(x.get('structure', '')))
            else:
                print(f"[-] [Gap Filling] Could not find missing sections in document")
                
        except Exception as e:
            logging.error(f"[Gap Filling] Failed: {e}")
            print(f"[-] [Gap Filling] Error: {e}")
    else:
        print(f"[+] [Structure Validation] No gaps detected - all sequences complete")
    
    return extracted


def parse_section_number(section_str: str) -> tuple:
    """
    Convert section number string to tuple for sorting.
    Examples: "2.1" -> (2, 1), "3" -> (3,), "采购清单.1" -> (9999, 1)
    """
    if not section_str:
        return (9999,)
    
    # Extract numeric parts
    parts = re.findall(r'\d+', section_str)
    if parts:
        return tuple(int(p) for p in parts)
    else:
        # Non-numeric sections go to end
        return (9999,)


def fill_missing_sections(missing_sections: List[str],
                          document_text: str,
                          model=None) -> List[Dict]:
    """
    Perform targeted re-extraction to find specific missing sections.
    
    Args:
        missing_sections: List of section numbers like ["2.2", "2.3"]
        document_text: Full document text
        model: LLM model name
        
    Returns:
        List of found sections in same format as extracted structure
    """
    from pageindex.utils import ChatGPT_API_with_finish_reason
    from pageindex.utils import extract_json_v2
    
    print(f"\n[Targeted Extraction] Searching for: {', '.join(missing_sections)}")
    
    # Format missing sections list for prompt
    sections_list = ", ".join(missing_sections)
    
    # Build prompt
    prompt = FILL_MISSING_SECTIONS_PROMPT.format(
        missing_sections=sections_list,
        document_text=document_text
    )
    
    # Call LLM for targeted extraction
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    
    if finish_reason != 'finished':
        raise Exception(f'LLM finish reason: {finish_reason}')
    
    # Parse JSON response
    found_sections = extract_json_v2(response, expected_schema='toc', model=model)
    
    # Filter out "NOT_FOUND" entries
    if found_sections:
        found_sections = [s for s in found_sections if s.get('title') != 'NOT_FOUND']
    
    print(f"[Targeted Extraction] Found {len(found_sections)} of {len(missing_sections)} missing sections")
    
    return found_sections if found_sections else []


def generate_toc_init_enhanced(part: str, model=None, custom_prompt=None, logger=None):
    """
    Enhanced version of generate_toc_init using two-phase extraction.
    
    This is a drop-in replacement for the original generate_toc_init function.
    """
    print('\n' + '='*70)
    print('ENHANCED STRUCTURE EXTRACTION')
    print('='*70)
    
    # Phase 1: Analyze document structure
    print('\n[Phase 1] Analyzing document structure...')
    structure_analysis = analyze_document_structure(part, model=model)
    
    print(f"  Structure Type: {structure_analysis.get('structure_type')}")
    print(f"  Extraction Strategy: {structure_analysis.get('extraction_strategy')}")
    print(f"  Confidence: {structure_analysis.get('confidence', 0):.2%}")
    print(f"  Patterns Found: {', '.join(structure_analysis.get('numbering_patterns_found', []))}")
    print(f"  Estimated Sections: ~{structure_analysis.get('estimated_section_count')}")
    
    # Phase 2: Extract structure
    print('\n[Phase 2] Extracting document structure...')
    extracted_structure = extract_structure_enhanced(
        part, 
        structure_analysis,
        model=model,
        logger=logger
    )
    
    print(f"\n[Phase 2] [+] Extracted {len(extracted_structure)} structure items")
    print('='*70 + '\n')
    
    return extracted_structure
