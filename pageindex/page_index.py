import os
import json
import copy
import math
import random
import re
import logging
from .utils import *
from .performance_monitor import get_monitor, reset_monitor
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import progress callback for WebSocket updates
try:
    from .progress_callback import report_progress, set_document_id, get_document_id
    PROGRESS_CALLBACK_AVAILABLE = True
except ImportError:
    PROGRESS_CALLBACK_AVAILABLE = False
    # Fallback if progress_callback is not available
    def set_document_id(document_id: str):
        pass
    def get_document_id() -> str:
        return None

def _report(stage: str, progress: float = None, message: str = None, metadata: dict = None):
    """Helper function to report progress if callback is available."""
    if PROGRESS_CALLBACK_AVAILABLE:
        doc_id = get_document_id()
        if doc_id:
            try:
                report_progress(doc_id, stage, progress, message, metadata)
            except Exception:
                pass  # Silently fail to avoid interrupting parsing


################### check title in page #########################################################
async def check_title_appearance(item, page_list, start_index=1, model=None):
    """
    Check if a section title appears in a specific page.

    Uses simple text matching first, falls back to LLM if needed.
    """
    title = item['title']
    if 'physical_index' not in item or item['physical_index'] is None:
        return {'list_index': item.get('list_index'), 'answer': 'no', 'title': title, 'page_number': None}


    page_number = item['physical_index']
    page_text = page_list[page_number - start_index][0]


    # First try simple substring matching (case-insensitive)
    title_clean = title.lower().strip()
    page_text_lower = page_text.lower()

    if title_clean in page_text_lower:
        return {'list_index': item.get('list_index'), 'answer': 'yes', 'title': title, 'page_number': page_number}

    # Try word-by-word matching
    title_words = set(title_clean.split())
    if title_words and len(title_words) > 2:
        # If 70% of words appear in the page text
        words_found = sum(1 for word in title_words if word in page_text_lower)
        if words_found / len(title_words) >= 0.7:
            return {'list_index': item.get('list_index'), 'answer': 'yes', 'title': title, 'page_number': page_number}

    # Fallback to LLM with simplified prompt
    prompt = f"""Does the section "{title[:100]}" appear in this page?

Page text (first 500 chars):
{page_text[:500]}

Answer ONLY with "yes" or "no". No explanation."""

    try:
        response = await ChatGPT_API_async(model=model, prompt=prompt)
        if response and isinstance(response, str):
            response_clean = response.strip().lower()
            answer = 'yes' if 'yes' in response_clean else 'no'
            return {'list_index': item.get('list_index'), 'answer': answer, 'title': title, 'page_number': page_number}
    except Exception as e:
        logging.warning(f"LLM check_title_appearance failed: {e}")

    # Default to no if all methods fail
    return {'list_index': item.get('list_index'), 'answer': 'no', 'title': title, 'page_number': page_number}


async def check_title_appearance_in_start(title, page_text, model=None, logger=None):
    """
    Check if a section title appears at the start of a page.

    Uses simple text matching first, falls back to LLM if needed.
    """
    # First try simple check: is title at the beginning of page_text?
    page_text_stripped = page_text.lstrip()
    title_clean = title.strip()

    if page_text_stripped.startswith(title_clean):
        return "yes"

    # Check if title appears in first 300 characters
    if len(page_text_stripped) > 300:
        page_text_sample = page_text_stripped[:300]
    else:
        page_text_sample = page_text_stripped

    # Fuzzy match: check if title words appear at the start
    title_words = title_clean.lower().split()[:5]  # First 5 words
    page_words = page_text_sample.lower().split()[:10]  # First 10 words

    if title_words and title_words[0].lower() in [w.lower() for w in page_words[:5]]:
        # First word matches at the beginning
        return "yes"

    # LLM fallback with simplified prompt
    prompt = f"""Does the section "{title[:100]}" start at the beginning of this page?

Page text (first 400 chars):
{page_text[:400]}

Answer ONLY with "yes" or "no". No explanation."""

    try:
        response = await ChatGPT_API_async(model=model, prompt=prompt)
        if response and isinstance(response, str):
            response_clean = response.strip().lower()
            if 'yes' in response_clean:
                return "yes"
    except Exception as e:
        logging.warning(f"LLM check_title_appearance_in_start failed: {e}")

    return "no"


async def check_title_appearance_in_start_concurrent(structure, page_list, model=None, logger=None):
    if logger:
        logger.info("Checking title appearance in start concurrently")

    # Count items to validate
    items_to_check = sum(1 for item in structure if item.get('physical_index') is not None)
    print(f"[DEBUG] check_title_appearance: Validating {items_to_check} titles...")
    _report("toc_postprocessing", progress=50, message=f"Validating {items_to_check} section titles...")

    # skip items without physical_index
    for item in structure:
        if item.get('physical_index') is None:
            item['appear_start'] = 'no'

    # only for items with valid physical_index
    tasks = []
    valid_items = []
    for item in structure:
        if item.get('physical_index') is not None:
            page_text = page_list[item['physical_index'] - 1][0]
            tasks.append(check_title_appearance_in_start(item['title'], page_text, model=model, logger=logger))
            valid_items.append(item)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item, result in zip(valid_items, results):
        if isinstance(result, Exception):
            if logger:
                logger.error(f"Error checking start for {item['title']}: {result}")
            item['appear_start'] = 'no'
        else:
            item['appear_start'] = result

    # Debug: Show validation results
    confirmed = sum(1 for r in results if not isinstance(r, Exception) and r == 'yes')
    print(f"[DEBUG] check_title_appearance: {confirmed}/{len(results)} titles confirmed")
    _report("toc_postprocessing", progress=55,
           message=f"Validated {confirmed}/{len(results)} section titles")

    return structure


def toc_detector_single_page(content, model=None):
    """
    Detect if the page contains a table of contents.

    Uses simplified prompt to avoid truncation issues.
    Falls back to keyword detection if LLM fails.
    Now requires page citations for TOC detection to reduce false positives.
    """
    import re

    # First, try keyword-based detection (faster and more reliable)
    # Remove 'section' as it's too generic and causes false positives
    # Add Chinese TOC keywords
    toc_keywords = ['table of contents', 'contents', 'chapter', '目录', '目　录']
    content_lower = content.lower()

    # Check for TOC indicators
    has_multiple_headings = sum(1 for line in content_lower.split('\n') if line.strip())
    has_toc_keywords = any(keyword in content_lower for keyword in toc_keywords)

    # NEW: Also check for page citations
    # English page references
    english_page_pattern = r'\b(?:p|page|pp)\.?\s*\d+|\d+\s*(?:p|page|pp)\.?'
    # Chinese page references
    chinese_page_pattern = r'第\s*\d+\s*页|\d+\s*页'

    has_page_citations = (
        re.search(english_page_pattern, content, re.IGNORECASE) or
        re.search(chinese_page_pattern, content)
    )

    # Quick check: if we see clear TOC patterns WITH page citations
    if has_toc_keywords and has_multiple_headings > 3 and has_page_citations:
        return "yes"

    # If we have TOC keywords but NO page citations, be more cautious
    # Use LLM to verify
    if has_toc_keywords and has_multiple_headings > 3 and not has_page_citations:
        # Prompt that emphasizes page citations are required
        prompt = f"""Does this page contain a table of contents with explicit page number references?

Text (first 400 chars):
{content[:400]}

Answer ONLY with "yes" or "no". No explanation.

Important: A table of contents MUST have page number references (like "Page 5", "p.12", "第3页", etc.).
Documents with just numbered sections (1., 2., 3.) are NOT table of contents.
Abstracts, summaries, notation lists, figure lists, table lists are NOT table of contents."""

        try:
            response = ChatGPT_API(model=model, prompt=prompt)
            if response and isinstance(response, str):
                response_clean = response.strip().lower()
                if "yes" in response_clean:
                    return "yes"
        except Exception as e:
            logging.warning(f"LLM toc_detector failed: {e}")

    # For ambiguous cases, use LLM with simplified prompt
    prompt = f"""Does this page contain a table of contents with explicit page number references?

Text (first 400 chars):
{content[:400]}

Answer ONLY with "yes" or "no". No explanation.

Note: A table of contents MUST have page number references. Abstracts, summaries, notation lists, figure lists, table lists are NOT table of contents."""

    try:
        response = ChatGPT_API(model=model, prompt=prompt)
        if response and isinstance(response, str):
            response_clean = response.strip().lower()
            if "yes" in response_clean:
                return "yes"
    except Exception as e:
        logging.warning(f"LLM toc_detector failed: {e}")

    return "no"


def check_if_toc_extraction_is_complete(content, toc, model=None):
    """
    Check if TOC extraction is complete.

    Uses simplified prompt to avoid truncation issues.
    """
    # Simple heuristic: if TOC has multiple entries, consider it complete
    toc_lines = [line.strip() for line in toc.split('\n') if line.strip()]
    if len(toc_lines) > 5:  # Has at least 5 entries
        return "yes"

    # For edge cases, use LLM with simplified prompt
    prompt = f"""Is this table of contents complete?

Document (first 300 chars):
{content[:300]}

TOC (first 300 chars):
{toc[:300]}

Answer ONLY with "yes" or "no". No explanation."""

    try:
        response = ChatGPT_API(model=model, prompt=prompt)
        if response and isinstance(response, str):
            response_clean = response.strip().lower()
            if "yes" in response_clean:
                return "yes"
            elif "no" in response_clean:
                return "no"
    except Exception as e:
        logging.warning(f"LLM check_if_toc_extraction_is_complete failed: {e}")

    # Default to complete if we have some entries
    return "yes" if len(toc_lines) > 0 else "no"


def check_if_toc_transformation_is_complete(content, toc, model=None):
    """
    Check if the TOC transformation is complete.

    Uses a simplified prompt to avoid long responses that get truncated.
    Falls back to simple heuristics if LLM call fails.
    """
    # Try LLM-based check first with simplified prompt
    prompt = f"""Check if the table of contents transformation is complete.

Raw TOC (first 500 chars):
{content[:500]}

Transformed TOC (first 500 chars):
{toc[:500]}

Is the transformed TOC complete? Answer ONLY with "yes" or "no". No explanation."""

    try:
        response = ChatGPT_API(model=model, prompt=prompt)
        if response and isinstance(response, str):
            response_clean = response.strip().lower()
            if "yes" in response_clean:
                return "yes"
            elif "no" in response_clean:
                return "no"
    except Exception as e:
        logging.warning(f"LLM check failed: {e}, using heuristic")

    # Fallback: simple heuristic check
    # Consider complete if toc has more entries than raw or similar length
    content_entries = len([line for line in content.split('\n') if line.strip()])
    toc_entries = len([line for line in toc.split('\n') if line.strip()])

    if toc_entries >= content_entries * 0.8:  # At least 80% of entries
        return "yes"
    else:
        return "no"

def extract_toc_content(content, model=None):
    prompt = f"""
    Your job is to extract the full table of contents from the given text, replace ... with :

    Given text: {content}

    Directly return the full table of contents content. Do not output anything else."""

    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

    # If finished in one go, return immediately
    if finish_reason == "finished":
        return response

    chat_history = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response},
    ]
    prompt = f"""please continue the generation of table of contents , directly output the remaining part of the structure"""
    new_response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt, chat_history=chat_history)
    response = response + new_response

    # Add iteration limit to prevent infinite loops
    max_iterations = 20
    iteration = 0

    # Track previous output length to detect stagnation
    prev_length = 0
    stagnation_count = 0

    while iteration < max_iterations:
        iteration += 1

        # Check if we're making progress (output is growing)
        current_length = len(response)
        if current_length == prev_length:
            stagnation_count += 1
        else:
            stagnation_count = 0
        prev_length = current_length

        # Exit if no progress for 3 iterations
        if stagnation_count >= 3:
            logging.warning(f"extract_toc_content: No progress for {stagnation_count} iterations, forcing exit at iteration {iteration}")
            break

        # Exit if finished naturally
        if finish_reason == "finished":
            logging.info(f"extract_toc_content: Finished naturally at iteration {iteration}")
            break

        # Check if TOC extraction is complete (using heuristic)
        if_complete = check_if_toc_transformation_is_complete(content, response, model)
        if if_complete == "yes":
            logging.info(f"extract_toc_content: TOC extraction complete at iteration {iteration}")
            break

        chat_history = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ]
        prompt = f"""please continue the generation of table of contents , directly output the remaining part of the structure"""
        new_response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt, chat_history=chat_history)
        response = response + new_response

    if iteration >= max_iterations:
        logging.warning(f"extract_toc_content: Max iterations ({max_iterations}) reached, forcing exit")

    return response

def detect_page_index(toc_content, model=None):
    print('start detect_page_index')

    # Stricter detection: require explicit page reference patterns
    import re

    # Pattern 1: English page references (p., page, pp.) with numbers
    english_pattern = r'\b(?:p|page|pp)\.?\s*\d+|\d+\s*(?:p|page|pp)\.?'

    # Pattern 2: Chinese page references (第X页, 第X节, etc.)
    chinese_pattern = r'第\s*\d+\s*[页章节节]|页\s*\d+|\d+\s*页'

    # Pattern 3: Standard TOC format - numbers/dots at end of lines MUST have explicit indicators
    # Count lines with explicit page references
    lines = toc_content.split('\n')
    lines_with_page_refs = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for English page reference
        if re.search(english_pattern, line, re.IGNORECASE):
            lines_with_page_refs += 1
            continue

        # Check for Chinese page reference
        if re.search(chinese_pattern, line):
            lines_with_page_refs += 1
            continue

        # Check for dots followed by number (traditional TOC format: "Title ..... 5")
        # But ONLY if there are clear dot leaders (.....)
        if re.search(r'\.{5,}\s*\d+\s*$', line):
            lines_with_page_refs += 1
            continue

    # Require at least 3 lines with explicit page references AND at least 20% of non-empty lines
    non_empty_lines = [l for l in lines if l.strip()]
    if len(non_empty_lines) > 0:
        page_ref_ratio = lines_with_page_refs / len(non_empty_lines)
    else:
        page_ref_ratio = 0

    # Stricter threshold: need at least 3 explicit page references AND 20% ratio
    if lines_with_page_refs >= 3 and page_ref_ratio >= 0.2:
        logging.info(f"Found {lines_with_page_refs} lines with explicit page references ({page_ref_ratio*100:.1f}%)")
        return "yes"

    logging.info(f"Insufficient page references: {lines_with_page_refs} lines ({page_ref_ratio*100:.1f}%)")
    return "no"

def toc_extractor(page_list, toc_page_list, model):
    def transform_dots_to_colon(text):
        text = re.sub(r'\.{5,}', ': ', text)
        # Handle dots separated by spaces
        text = re.sub(r'(?:\. ){5,}\.?', ': ', text)
        return text
    
    toc_content = ""
    for page_index in toc_page_list:
        toc_content += page_list[page_index][0]
    toc_content = transform_dots_to_colon(toc_content)
    has_page_index = detect_page_index(toc_content, model=model)
    
    return {
        "toc_content": toc_content,
        "page_index_given_in_toc": has_page_index
    }




def toc_index_extractor(toc, content, model=None):
    print('start toc_index_extractor')
    tob_extractor_prompt = """
    You are given a table of contents in a json format and several pages of a document, your job is to add the physical_index to the table of contents in the json format.

    The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    The response should be in the following JSON format: 
    [
        {
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "physical_index": "<physical_index_X>" (keep the format)
        },
        ...
    ]

    Only add the physical_index to the sections that are in the provided pages.
    If the section is not in the provided pages, do not add the physical_index to it.
    Directly return the final JSON structure. Do not output anything else."""

    prompt = tob_extractor_prompt + '\nTable of contents:\n' + str(toc) + '\nDocument pages:\n' + content
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)    
    return json_content



def toc_transformer(toc_content, model=None):
    print('start toc_transformer')
    init_prompt = """
    You are given a table of contents, You job is to transform the whole table of content into a JSON format included table_of_contents.

    structure is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    The response should be in the following JSON format:
    {
    table_of_contents: [
        {
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "page": <page number or None>,
        },
        ...
        ],
    }
    You should transform the full table of contents in one go.
    Directly return the final JSON structure, do not output anything else. """

    prompt = init_prompt + '\n Given table of contents\n:' + toc_content
    last_complete, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

    # If finished in one go, return immediately
    if finish_reason == "finished":
        last_complete = extract_json(last_complete)
        cleaned_response = convert_page_to_int(last_complete['table_of_contents'])
        return cleaned_response

    last_complete = get_json_content(last_complete)

    # Add iteration limit to prevent infinite loops
    max_iterations = 20
    iteration = 0

    # Track previous output length to detect stagnation
    prev_length = 0
    stagnation_count = 0

    while iteration < max_iterations:
        iteration += 1

        # Check if we're making progress (output is growing)
        current_length = len(last_complete)
        if current_length == prev_length:
            stagnation_count += 1
        else:
            stagnation_count = 0
        prev_length = current_length

        # Exit if no progress for 3 iterations
        if stagnation_count >= 3:
            logging.warning(f"toc_transformer: No progress for {stagnation_count} iterations, forcing exit at iteration {iteration}")
            break

        # Trim to last complete JSON object
        position = last_complete.rfind('}')
        if position != -1:
            last_complete = last_complete[:position+2]

        prompt = f"""
        Your task is to continue the table of contents json structure, directly output the remaining part of the json structure.
        The response should be in the following JSON format:

        The raw table of contents json structure is:
        {toc_content}

        The incomplete transformed table of contents json structure is:
        {last_complete}

        Please continue the json structure, directly output the remaining part of the json structure."""

        new_complete, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

        # Always append the new content
        if new_complete.startswith('```json'):
            new_complete = get_json_content(new_complete)
        last_complete = last_complete + new_complete

        # Exit if finished naturally
        if finish_reason == "finished":
            logging.info(f"toc_transformer: Finished naturally at iteration {iteration}")
            break

        # Check if TOC transformation is complete (using heuristic)
        if_complete = check_if_toc_transformation_is_complete(toc_content, last_complete, model)
        if if_complete == "yes":
            logging.info(f"toc_transformer: TOC transformation complete at iteration {iteration}")
            break

    if iteration >= max_iterations:
        logging.warning(f"toc_transformer: Max iterations ({max_iterations}) reached, forcing exit")


    # Try json.loads first, fall back to extract_json if it fails
    try:
        last_complete = json.loads(last_complete)
    except json.JSONDecodeError as e:
        last_complete = extract_json(last_complete)
        if last_complete is None:
            raise ValueError(f"Failed to parse LLM response as JSON. Original error: {e}")

    if 'table_of_contents' not in last_complete:
        raise ValueError(f"LLM response missing 'table_of_contents' key. Response: {str(last_complete)[:500]}")

    cleaned_response=convert_page_to_int(last_complete['table_of_contents'])
    return cleaned_response
    



def find_toc_pages(start_page_index, page_list, opt, logger=None):
    print('start find_toc_pages')
    _report("toc_detection", progress=5, message="Searching for table of contents...")
    last_page_is_yes = False
    toc_page_list = []
    i = start_page_index

    while i < len(page_list):
        # Only check beyond max_pages if we're still finding TOC pages
        if i >= opt.toc_check_page_num and not last_page_is_yes:
            break
        detected_result = toc_detector_single_page(page_list[i][0],model=opt.model)
        if detected_result == 'yes':
            if logger:
                logger.info(f'Page {i} has toc')
            toc_page_list.append(i)
            last_page_is_yes = True
            _report("toc_detection", progress=5 + (i / opt.toc_check_page_num) * 5,
                   message=f"Found TOC on page {i + 1}")
        elif detected_result == 'no' and last_page_is_yes:
            if logger:
                logger.info(f'Found the last page with toc: {i-1}')
            break
        i += 1

    if not toc_page_list:
        if logger:
            logger.info('No toc found')
        _report("toc_detection", progress=10, message="No table of contents found")
    else:
        _report("toc_detection", progress=10,
               message=f"Found TOC on {len(toc_page_list)} page(s)")

    return toc_page_list

def remove_page_number(data):
    if isinstance(data, dict):
        data.pop('page_number', None)  
        for key in list(data.keys()):
            if 'nodes' in key:
                remove_page_number(data[key])
    elif isinstance(data, list):
        for item in data:
            remove_page_number(item)
    return data

def extract_matching_page_pairs(toc_page, toc_physical_index, start_page_index):
    pairs = []
    for phy_item in toc_physical_index:
        for page_item in toc_page:
            if phy_item.get('title') == page_item.get('title'):
                physical_index = phy_item.get('physical_index')
                # Convert physical_index to int if it's a string
                if physical_index is not None:
                    try:
                        physical_index_int = int(physical_index)
                        if physical_index_int >= start_page_index:
                            page = page_item.get('page')
                            # Only add if page is also valid
                            if page is not None and isinstance(page, int):
                                pairs.append({
                                    'title': phy_item.get('title'),
                                    'page': page,
                                    'physical_index': physical_index_int
                                })
                    except (ValueError, TypeError):
                        # Skip if physical_index can't be converted to int
                        continue
    return pairs


def calculate_page_offset(pairs):
    differences = []
    for pair in pairs:
        try:
            physical_index = pair.get('physical_index')
            page_number = pair.get('page')
            # Validate both are integers before calculating difference
            if isinstance(physical_index, int) and isinstance(page_number, int):
                difference = physical_index - page_number
                differences.append(difference)
        except (KeyError, TypeError, AttributeError):
            continue

    if not differences:
        return None

    difference_counts = {}
    for diff in differences:
        difference_counts[diff] = difference_counts.get(diff, 0) + 1

    most_common = max(difference_counts.items(), key=lambda x: x[1])[0]

    return most_common

def add_page_offset_to_toc_json(data, offset):
    # Handle None offset - just remove the page field without adding offset
    if offset is None:
        for i in range(len(data)):
            if data[i].get('page') is not None and isinstance(data[i]['page'], int):
                data[i]['physical_index'] = data[i]['page']
                del data[i]['page']
        return data

    for i in range(len(data)):
        if data[i].get('page') is not None and isinstance(data[i]['page'], int):
            data[i]['physical_index'] = data[i]['page'] + offset
            del data[i]['page']

    return data



def calculate_optimal_chunk_size(total_tokens, model=None):
    """
    Calculate optimal chunk size based on document size and model context window.

    Strategy:
    - Small docs (<50K tokens): Use 1 chunk
    - Medium docs (50K-100K): Use 2-3 chunks
    - Large docs (100K-150K): Use 3-5 chunks
    - Very large docs (>150K): Use max model capacity

    Args:
        total_tokens: Total token count of the document
        model: Model name to determine context window

    Returns:
        Optimal max_tokens per chunk
    """
    # Model context windows (conservative estimates, leaving room for prompt/response)
    MODEL_CONTEXT = {
        # Gemini 2.5
        "gemini-2.5-flash": 1000000,
        "gemini-2.5-pro": 1000000,
        "gemini-1.5": 1000000,
        # GPT-4o
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        # Claude
        "claude-3-5-sonnet": 200000,
        "claude-3-opus": 200000,
        # DeepSeek
        "deepseek-chat": 128000,
        "deepseek-coder": 128000,
        # Default for OpenRouter models
        "openrouter": 128000,
    }

    # Get model context limit
    model_lower = (model or "").lower()
    max_context = 128000  # Default conservative

    for key, limit in MODEL_CONTEXT.items():
        if key in model_lower:
            max_context = limit
            break

    # Reserve space for prompt and response (about 30K tokens)
    available_for_content = max_context - 30000

    # Dynamic chunking strategy
    if total_tokens <= 50000:
        # Small docs: single chunk
        return min(total_tokens + 5000, available_for_content)
    elif total_tokens <= 100000:
        # Medium docs: 2-3 chunks
        return min(total_tokens / 2 + 10000, available_for_content)
    elif total_tokens <= 150000:
        # Large docs: 3-5 chunks
        return min(total_tokens / 3 + 10000, available_for_content)
    else:
        # Very large docs: use max capacity
        return available_for_content


def page_list_to_group_text(page_contents, token_lengths, max_tokens=200000, overlap_page=1):    
    num_tokens = sum(token_lengths)
    
    if num_tokens <= max_tokens:
        # merge all pages into one text
        page_text = "".join(page_contents)
        return [page_text]
    
    subsets = []
    current_subset = []
    current_token_count = 0

    expected_parts_num = math.ceil(num_tokens / max_tokens)
    average_tokens_per_part = math.ceil(((num_tokens / expected_parts_num) + max_tokens) / 2)
    
    for i, (page_content, page_tokens) in enumerate(zip(page_contents, token_lengths)):
        if current_token_count + page_tokens > average_tokens_per_part:

            subsets.append(''.join(current_subset))
            # Start new subset from overlap if specified
            overlap_start = max(i - overlap_page, 0)
            current_subset = page_contents[overlap_start:i]
            current_token_count = sum(token_lengths[overlap_start:i])
        
        # Add current page to the subset
        current_subset.append(page_content)
        current_token_count += page_tokens

    # Add the last subset if it contains any pages
    if current_subset:
        subsets.append(''.join(current_subset))
    
    print('divide page_list to groups', len(subsets))
    return subsets

def add_page_number_to_toc(part, structure, model=None):
    fill_prompt_seq = """
    You are given an JSON structure of a document and a partial part of the document. Your task is to check if the title that is described in the structure is started in the partial given document.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X. 

    If the full target section starts in the partial given document, insert the given JSON structure with the "start": "yes", and "start_index": "<physical_index_X>".

    If the full target section does not start in the partial given document, insert "start": "no",  "start_index": None.

    The response should be in the following format. 
        [
            {
                "structure": <structure index, "x.x.x" or None> (string),
                "title": <title of the section>,
                "start": "<yes or no>",
                "physical_index": "<physical_index_X> (keep the format)" or None
            },
            ...
        ]    
    The given structure contains the result of the previous part, you need to fill the result of the current part, do not change the previous result.
    Directly return the final JSON structure. Do not output anything else."""

    prompt = fill_prompt_seq + f"\n\nCurrent Partial Document:\n{part}\n\nGiven Structure\n{json.dumps(structure, indent=2)}\n"
    current_json_raw = ChatGPT_API(model=model, prompt=prompt)
    json_result = extract_json(current_json_raw)
    
    for item in json_result:
        if 'start' in item:
            del item['start']
    return json_result


def remove_first_physical_index_section(text):
    """
    Removes the first section between <physical_index_X> and <physical_index_X> tags,
    and returns the remaining text.
    """
    pattern = r'<physical_index_\d+>.*?<physical_index_\d+>'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        # Remove the first matched section
        return text.replace(match.group(0), '', 1)
    return text

### add verify completeness
def generate_toc_continue(toc_content, part, model=None, custom_prompt=None):
    print('start generate_toc_continue')
    base_prompt = """
    You are an expert in extracting hierarchical tree structure.
    You are given a tree structure of the previous part and the text of the current part.
    Your task is to continue the tree structure from the previous part to include the current part.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    For the title, you need to extract the original title from the text, only fix the space inconsistency.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

    For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

    The response should be in the following format.
        [
            {
                "structure": <structure index, "x.x.x"> (string),
                "title": <title of the section, keep the original title>,
                "physical_index": "<physical_index_X> (keep the format)"
            },
            ...
        ]

    Directly return the additional part of the final JSON structure. Do not output anything else."""

    # Append custom prompt if provided
    if custom_prompt and custom_prompt.strip():
        base_prompt += f"\n\nAdditional Instructions:\n{custom_prompt.strip()}"

    prompt = base_prompt + '\nGiven text\n:' + part + '\nPrevious tree structure\n:' + json.dumps(toc_content, indent=2)
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if finish_reason == 'finished':
        return extract_json(response)
    else:
        raise Exception(f'finish reason: {finish_reason}')
    
### add verify completeness
def generate_toc_init(part, model=None, custom_prompt=None):
    print('start generate_toc_init')
    base_prompt = """
    You are an expert in extracting hierarchical tree structure, your task is to generate the tree structure of the document.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    For the title, you need to extract the original title from the text, only fix the space inconsistency.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

    For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

    The response should be in the following format.
        [
            {{
                "structure": <structure index, "x.x.x"> (string),
                "title": <title of the section, keep the original title>,
                "physical_index": "<physical_index_X> (keep the format)"
            }},

        ],


    Directly return the final JSON structure. Do not output anything else."""

    # Append custom prompt if provided
    if custom_prompt and custom_prompt.strip():
        base_prompt += f"\n\nAdditional Instructions:\n{custom_prompt.strip()}"

    prompt = base_prompt + '\nGiven text\n:' + part
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

    if finish_reason == 'finished':
         return extract_json(response)
    else:
        raise Exception(f'finish reason: {finish_reason}')

def process_no_toc(page_list, start_index=1, model=None, logger=None, custom_prompt=None):
    print(f"[DEBUG] process_no_toc: Starting auto-structure generation for {len(page_list)} pages")
    _report("toc_processing", progress=12, message="Analyzing document structure...")

    page_contents=[]
    token_lengths=[]
    for page_index in range(start_index, start_index+len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index-start_index][0]}\n<physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))

    # Calculate optimal chunk size dynamically
    total_tokens = sum(token_lengths)
    optimal_chunk_size = calculate_optimal_chunk_size(total_tokens, model)
    print(f"[DEBUG] process_no_toc: Total tokens: {total_tokens:,}, optimal chunk size: {optimal_chunk_size:,}")

    group_texts = page_list_to_group_text(page_contents, token_lengths, max_tokens=optimal_chunk_size)
    logger.info(f'len(group_texts): {len(group_texts)}')

    print(f"[DEBUG] process_no_toc: Split into {len(group_texts)} chunks for processing")
    for i, group in enumerate(group_texts):
        tokens = count_tokens(group, model)
        print(f"[DEBUG]   Chunk {i+1}: {tokens:,} tokens")

    _report("toc_processing", progress=14, message=f"Analyzing {len(group_texts)} section(s)...")

    print(f"[DEBUG] process_no_toc: Generating initial structure from chunk 1...")
    toc_with_page_number= generate_toc_init(group_texts[0], model, custom_prompt)
    print(f"[DEBUG] process_no_toc: Initial structure: {len(toc_with_page_number)} items")

    # Report progress for each chunk
    total_chunks = len(group_texts)
    for i, group_text in enumerate(group_texts[1:], start=2):
        chunk_progress = 14 + ((i - 1) / total_chunks) * 20
        _report("toc_processing", progress=chunk_progress,
               message=f"Analyzing section {i}/{total_chunks}...")
        print(f"[DEBUG] process_no_toc: Extending structure with chunk {i}...")
        toc_with_page_number_additional = generate_toc_continue(toc_with_page_number, group_text, model, custom_prompt)
        toc_with_page_number.extend(toc_with_page_number_additional)
        print(f"[DEBUG] process_no_toc: After chunk {i}: {len(toc_with_page_number)} total items")

    logger.info(f'generate_toc: {toc_with_page_number}')

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    logger.info(f'convert_physical_index_to_int: {toc_with_page_number}')

    print(f"[DEBUG] process_no_toc: Complete. Final structure: {len(toc_with_page_number)} items\n")
    return toc_with_page_number

def process_toc_no_page_numbers(toc_content, toc_page_list, page_list,  start_index=1, model=None, logger=None):
    page_contents=[]
    token_lengths=[]
    toc_content = toc_transformer(toc_content, model)
    logger.info(f'toc_transformer: {toc_content}')
    for page_index in range(start_index, start_index+len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index-start_index][0]}\n<physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))

    # Calculate optimal chunk size dynamically
    total_tokens = sum(token_lengths)
    optimal_chunk_size = calculate_optimal_chunk_size(total_tokens, model)
    print(f"[DEBUG] process_toc_no_page_numbers: Total tokens: {total_tokens:,}, optimal chunk size: {optimal_chunk_size:,}")

    group_texts = page_list_to_group_text(page_contents, token_lengths, max_tokens=optimal_chunk_size)
    logger.info(f'len(group_texts): {len(group_texts)}')

    toc_with_page_number=copy.deepcopy(toc_content)
    for group_text in group_texts:
        toc_with_page_number = add_page_number_to_toc(group_text, toc_with_page_number, model)
    logger.info(f'add_page_number_to_toc: {toc_with_page_number}')

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    logger.info(f'convert_physical_index_to_int: {toc_with_page_number}')

    return toc_with_page_number



def process_toc_with_page_numbers(toc_content, toc_page_list, page_list, toc_check_page_num=None, model=None, logger=None):
    toc_with_page_number = toc_transformer(toc_content, model)
    logger.info(f'toc_with_page_number: {toc_with_page_number}')

    toc_no_page_number = remove_page_number(copy.deepcopy(toc_with_page_number))

    start_page_index = toc_page_list[-1] + 1

    # Calculate optimal chunk size dynamically for content extraction
    # Collect all page contents first
    page_contents = []
    token_lengths = []
    for page_index in range(start_page_index, len(page_list)):
        page_text = f"<physical_index_{page_index+1}>\n{page_list[page_index][0]}\n<physical_index_{page_index+1}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))

    total_tokens = sum(token_lengths)
    optimal_chunk_size = calculate_optimal_chunk_size(total_tokens, model)
    logger.info(f'process_toc_with_page_numbers: Total content tokens: {total_tokens:,}, chunk size: {optimal_chunk_size:,}')

    # Group pages into chunks for toc_index_extractor
    group_texts = page_list_to_group_text(page_contents, token_lengths, max_tokens=optimal_chunk_size)

    # Process each chunk
    all_toc_with_physical_index = []
    for i, chunk_content in enumerate(group_texts, 1):
        logger.info(f'Processing chunk {i}/{len(group_texts)} with {count_tokens(chunk_content, model):,} tokens')
        toc_with_physical_index = toc_index_extractor(toc_no_page_number, chunk_content, model)
        all_toc_with_physical_index.extend(toc_with_physical_index)

    # Merge results from all chunks
    toc_with_physical_index = all_toc_with_physical_index
    logger.info(f'toc_with_physical_index: {toc_with_physical_index}')

    toc_with_physical_index = convert_physical_index_to_int(toc_with_physical_index)
    logger.info(f'toc_with_physical_index: {toc_with_physical_index}')

    matching_pairs = extract_matching_page_pairs(toc_with_page_number, toc_with_physical_index, start_page_index)
    logger.info(f'matching_pairs: {matching_pairs}')

    offset = calculate_page_offset(matching_pairs)
    if offset is None:
        logger.warning(f'Could not calculate page offset from {len(matching_pairs)} matching pairs. Using page numbers directly as physical_index.')
    else:
        logger.info(f'offset: {offset}')

    toc_with_page_number = add_page_offset_to_toc_json(toc_with_page_number, offset)
    logger.info(f'toc_with_page_number: {toc_with_page_number}')

    toc_with_page_number = process_none_page_numbers(toc_with_page_number, page_list, model=model)
    logger.info(f'toc_with_page_number: {toc_with_page_number}')

    return toc_with_page_number



##check if needed to process none page numbers
def process_none_page_numbers(toc_items, page_list, start_index=1, model=None):
    for i, item in enumerate(toc_items):
        if "physical_index" not in item:
            # logger.info(f"fix item: {item}")
            # Find previous physical_index
            prev_physical_index = 0  # Default if no previous item exists
            for j in range(i - 1, -1, -1):
                if toc_items[j].get('physical_index') is not None:
                    prev_physical_index = toc_items[j]['physical_index']
                    break

            # Find next physical_index
            next_physical_index = -1  # Default if no next item exists
            for j in range(i + 1, len(toc_items)):
                if toc_items[j].get('physical_index') is not None:
                    next_physical_index = toc_items[j]['physical_index']
                    break

            # If we couldn't find valid bounds, use the entire document
            if next_physical_index == -1:
                next_physical_index = len(page_list) + start_index - 1

            page_contents = []
            for page_index in range(prev_physical_index, next_physical_index+1):
                # Add bounds checking to prevent IndexError
                list_index = page_index - start_index
                if list_index >= 0 and list_index < len(page_list):
                    page_text = f"<physical_index_{page_index}>\n{page_list[list_index][0]}\n<physical_index_{page_index}>\n\n"
                    page_contents.append(page_text)
                else:
                    continue

            # Only proceed if we have some content to analyze
            if not page_contents:
                continue

            item_copy = copy.deepcopy(item)
            # Safely remove 'page' key if it exists
            if 'page' in item_copy:
                del item_copy['page']

            result = add_page_number_to_toc(page_contents, item_copy, model)
            # Validate result before accessing
            if result and len(result) > 0 and isinstance(result[0], dict):
                physical_index = result[0].get('physical_index')
                if physical_index is not None:
                    if isinstance(physical_index, str) and physical_index.startswith('<physical_index'):
                        item['physical_index'] = int(physical_index.split('_')[-1].rstrip('>').strip())
                        if 'page' in item:
                            del item['page']
                    elif isinstance(physical_index, int):
                        item['physical_index'] = physical_index
                        if 'page' in item:
                            del item['page']

    return toc_items




def check_toc(page_list, opt=None):
    toc_page_list = find_toc_pages(start_page_index=0, page_list=page_list, opt=opt)
    if len(toc_page_list) == 0:
        print('no toc found')
        return {'toc_content': None, 'toc_page_list': [], 'page_index_given_in_toc': 'no'}
    else:
        print('toc found')
        toc_json = toc_extractor(page_list, toc_page_list, opt.model)

        if toc_json['page_index_given_in_toc'] == 'yes':
            print('index found')
            return {'toc_content': toc_json['toc_content'], 'toc_page_list': toc_page_list, 'page_index_given_in_toc': 'yes'}
        else:
            current_start_index = toc_page_list[-1] + 1
            
            while (toc_json['page_index_given_in_toc'] == 'no' and 
                   current_start_index < len(page_list) and 
                   current_start_index < opt.toc_check_page_num):
                
                additional_toc_pages = find_toc_pages(
                    start_page_index=current_start_index,
                    page_list=page_list,
                    opt=opt
                )
                
                if len(additional_toc_pages) == 0:
                    break

                additional_toc_json = toc_extractor(page_list, additional_toc_pages, opt.model)
                if additional_toc_json['page_index_given_in_toc'] == 'yes':
                    print('index found')
                    return {'toc_content': additional_toc_json['toc_content'], 'toc_page_list': additional_toc_pages, 'page_index_given_in_toc': 'yes'}

                else:
                    current_start_index = additional_toc_pages[-1] + 1
            print('index not found')
            return {'toc_content': toc_json['toc_content'], 'toc_page_list': toc_page_list, 'page_index_given_in_toc': 'no'}






################### fix incorrect toc #########################################################
def single_toc_item_index_fixer(section_title, content, model=None):
    tob_extractor_prompt = """
    You are given a section title and several pages of a document, your job is to find the physical index of the start page of the section in the partial document.

    The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

    Reply in a JSON format:
    {
        "thinking": <explain which page, started and closed by <physical_index_X>, contains the start of this section>,
        "physical_index": "<physical_index_X>" (keep the format)
    }
    Directly return the final JSON structure. Do not output anything else."""

    prompt = tob_extractor_prompt + '\nSection Title:\n' + str(section_title) + '\nDocument pages:\n' + content
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)

    # Handle JSON extraction failure
    if json_content is None:
        logging.error(f"Failed to extract JSON from LLM response in single_toc_item_index_fixer")
        logging.error(f"LLM Response: {response[:500]}...")
        return None

    # Handle missing 'physical_index' key
    if not isinstance(json_content, dict):
        logging.error(f"Extracted content is not a dict in single_toc_item_index_fixer: {type(json_content)}")
        return None

    if 'physical_index' not in json_content:
        logging.error(f"'physical_index' key not found in JSON: {json_content}")
        return None

    return convert_physical_index_to_int(json_content['physical_index'])



async def fix_incorrect_toc(toc_with_page_number, page_list, incorrect_results, start_index=1, model=None, logger=None):
    print(f'start fix_incorrect_toc with {len(incorrect_results)} incorrect results')
    incorrect_indices = {result['list_index'] for result in incorrect_results}
    
    end_index = len(page_list) + start_index - 1
    
    incorrect_results_and_range_logs = []
    # Helper function to process and check a single incorrect item
    async def process_and_check_item(incorrect_item):
        list_index = incorrect_item['list_index']
        
        # Check if list_index is valid
        if list_index < 0 or list_index >= len(toc_with_page_number):
            # Return an invalid result for out-of-bounds indices
            return {
                'list_index': list_index,
                'title': incorrect_item['title'],
                'physical_index': incorrect_item.get('physical_index'),
                'is_valid': False
            }
        
        # Find the previous correct item
        prev_correct = None
        for i in range(list_index-1, -1, -1):
            if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                physical_index = toc_with_page_number[i].get('physical_index')
                if physical_index is not None:
                    prev_correct = physical_index
                    break
        # If no previous correct item found, use start_index
        if prev_correct is None:
            prev_correct = start_index - 1
        
        # Find the next correct item
        next_correct = None
        for i in range(list_index+1, len(toc_with_page_number)):
            if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                physical_index = toc_with_page_number[i].get('physical_index')
                if physical_index is not None:
                    next_correct = physical_index
                    break
        # If no next correct item found, use end_index
        if next_correct is None:
            next_correct = end_index
        
        incorrect_results_and_range_logs.append({
            'list_index': list_index,
            'title': incorrect_item['title'],
            'prev_correct': prev_correct,
            'next_correct': next_correct
        })

        page_contents=[]
        for page_index in range(prev_correct, next_correct+1):
            # Add bounds checking to prevent IndexError
            list_index = page_index - start_index
            if list_index >= 0 and list_index < len(page_list):
                page_text = f"<physical_index_{page_index}>\n{page_list[list_index][0]}\n<physical_index_{page_index}>\n\n"
                page_contents.append(page_text)
            else:
                continue
        content_range = ''.join(page_contents)
        
        physical_index_int = single_toc_item_index_fixer(incorrect_item['title'], content_range, model)
        
        # Check if the result is correct
        check_item = incorrect_item.copy()
        check_item['physical_index'] = physical_index_int
        check_result = await check_title_appearance(check_item, page_list, start_index, model)

        return {
            'list_index': list_index,
            'title': incorrect_item['title'],
            'physical_index': physical_index_int,
            'is_valid': check_result['answer'] == 'yes'
        }

    # Process incorrect items concurrently
    tasks = [
        process_and_check_item(item)
        for item in incorrect_results
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item, result in zip(incorrect_results, results):
        if isinstance(result, Exception):
            print(f"Processing item {item} generated an exception: {result}")
            continue
    results = [result for result in results if not isinstance(result, Exception)]

    # Update the toc_with_page_number with the fixed indices and check for any invalid results
    invalid_results = []
    for result in results:
        if result['is_valid']:
            # Add bounds checking to prevent IndexError
            list_idx = result['list_index']
            if 0 <= list_idx < len(toc_with_page_number):
                toc_with_page_number[list_idx]['physical_index'] = result['physical_index']
            else:
                # Index is out of bounds, treat as invalid
                invalid_results.append({
                    'list_index': result['list_index'],
                    'title': result['title'],
                    'physical_index': result['physical_index'],
                })
        else:
            invalid_results.append({
                'list_index': result['list_index'],
                'title': result['title'],
                'physical_index': result['physical_index'],
            })

    logger.info(f'incorrect_results_and_range_logs: {incorrect_results_and_range_logs}')
    logger.info(f'invalid_results: {invalid_results}')

    return toc_with_page_number, invalid_results



async def fix_incorrect_toc_with_retries(toc_with_page_number, page_list, incorrect_results, start_index=1, max_attempts=3, model=None, logger=None):
    print('start fix_incorrect_toc')
    fix_attempt = 0
    current_toc = toc_with_page_number
    current_incorrect = incorrect_results

    while current_incorrect:
        print(f"Fixing {len(current_incorrect)} incorrect results")
        
        current_toc, current_incorrect = await fix_incorrect_toc(current_toc, page_list, current_incorrect, start_index, model, logger)
                
        fix_attempt += 1
        if fix_attempt >= max_attempts:
            logger.info("Maximum fix attempts reached")
            break
    
    return current_toc, current_incorrect




################### verify toc #########################################################
async def verify_toc(page_list, list_result, start_index=1, N=None, model=None):
    print('start verify_toc')
    # Find the last non-None physical_index
    last_physical_index = None
    for item in reversed(list_result):
        if item.get('physical_index') is not None:
            last_physical_index = item['physical_index']
            break
    
    # Early return if we don't have valid physical indices
    # Relaxed threshold from 1/2 to 1/3 to accommodate documents with large table sections
    if last_physical_index is None or last_physical_index < len(page_list)/3:
        return 0, []
    
    # Determine which items to check
    if N is None:
        print('check all items')
        sample_indices = range(0, len(list_result))
    else:
        N = min(N, len(list_result))
        print(f'check {N} items')
        sample_indices = random.sample(range(0, len(list_result)), N)

    # Prepare items with their list indices
    indexed_sample_list = []
    for idx in sample_indices:
        item = list_result[idx]
        # Skip items with None physical_index (these were invalidated by validate_and_truncate_physical_indices)
        if item.get('physical_index') is not None:
            item_with_index = item.copy()
            item_with_index['list_index'] = idx  # Add the original index in list_result
            indexed_sample_list.append(item_with_index)

    # Run checks concurrently
    tasks = [
        check_title_appearance(item, page_list, start_index, model)
        for item in indexed_sample_list
    ]
    results = await asyncio.gather(*tasks)
    
    # Process results
    correct_count = 0
    incorrect_results = []
    for result in results:
        if result['answer'] == 'yes':
            correct_count += 1
        else:
            incorrect_results.append(result)
    
    # Calculate accuracy
    checked_count = len(results)
    accuracy = correct_count / checked_count if checked_count > 0 else 0
    print(f"accuracy: {accuracy*100:.2f}%")
    return accuracy, incorrect_results





################### main process #########################################################
async def meta_processor(page_list, mode=None, toc_content=None, toc_page_list=None, start_index=1, opt=None, logger=None):
    print(mode)
    print(f'start_index: {start_index}')

    # Get custom_prompt from opt if available
    custom_prompt = getattr(opt, 'custom_prompt', None) if opt else None

    if mode == 'process_toc_with_page_numbers':
        toc_with_page_number = process_toc_with_page_numbers(toc_content, toc_page_list, page_list, toc_check_page_num=opt.toc_check_page_num, model=opt.model, logger=logger)
    elif mode == 'process_toc_no_page_numbers':
        toc_with_page_number = process_toc_no_page_numbers(toc_content, toc_page_list, page_list, model=opt.model, logger=logger)
    else:
        toc_with_page_number = process_no_toc(page_list, start_index=start_index, model=opt.model, logger=logger, custom_prompt=custom_prompt)

    toc_with_page_number = [item for item in toc_with_page_number if item.get('physical_index') is not None]

    toc_with_page_number = validate_and_truncate_physical_indices(
        toc_with_page_number,
        len(page_list),
        start_index=start_index,
        logger=logger
    )

    accuracy, incorrect_results = await verify_toc(page_list, toc_with_page_number, start_index=start_index, model=opt.model)

    logger.info({
        'mode': 'process_toc_with_page_numbers',
        'accuracy': accuracy,
        'incorrect_results': incorrect_results
    })
    if accuracy == 1.0 and len(incorrect_results) == 0:
        return toc_with_page_number
    if accuracy > 0.6 and len(incorrect_results) > 0:
        toc_with_page_number, incorrect_results = await fix_incorrect_toc_with_retries(toc_with_page_number, page_list, incorrect_results,start_index=start_index, max_attempts=3, model=opt.model, logger=logger)
        return toc_with_page_number
    else:
        if mode == 'process_toc_with_page_numbers':
            return await meta_processor(page_list, mode='process_toc_no_page_numbers', toc_content=toc_content, toc_page_list=toc_page_list, start_index=start_index, opt=opt, logger=logger)
        elif mode == 'process_toc_no_page_numbers':
            return await meta_processor(page_list, mode='process_no_toc', start_index=start_index, opt=opt, logger=logger)
        else:
            raise Exception('Processing failed')
        
 
async def process_large_node_recursively(node, page_list, opt=None, logger=None):
    node_page_list = page_list[node['start_index']-1:node['end_index']]
    token_num = sum([page[1] for page in node_page_list])
    
    if node['end_index'] - node['start_index'] > opt.max_page_num_each_node and token_num >= opt.max_token_num_each_node:
        print('large node:', node['title'], 'start_index:', node['start_index'], 'end_index:', node['end_index'], 'token_num:', token_num)

        node_toc_tree = await meta_processor(node_page_list, mode='process_no_toc', start_index=node['start_index'], opt=opt, logger=logger)
        node_toc_tree = await check_title_appearance_in_start_concurrent(node_toc_tree, page_list, model=opt.model, logger=logger)
        
        # Filter out items with None physical_index before post_processing
        valid_node_toc_items = [item for item in node_toc_tree if item.get('physical_index') is not None]
        
        if valid_node_toc_items and node['title'].strip() == valid_node_toc_items[0]['title'].strip():
            node['nodes'] = post_processing(valid_node_toc_items[1:], node['end_index'])
            node['end_index'] = valid_node_toc_items[1]['start_index'] if len(valid_node_toc_items) > 1 else node['end_index']
        else:
            node['nodes'] = post_processing(valid_node_toc_items, node['end_index'])
            node['end_index'] = valid_node_toc_items[0]['start_index'] if valid_node_toc_items else node['end_index']
        
    if 'nodes' in node and node['nodes']:
        tasks = [
            process_large_node_recursively(child_node, page_list, opt, logger=logger)
            for child_node in node['nodes']
        ]
        await asyncio.gather(*tasks)
    
    return node

async def tree_parser(page_list, opt, doc=None, logger=None):
    """Parse document tree with detailed performance monitoring."""
    monitor = get_monitor()

    # Debug: Document info
    print(f"\n{'='*60}")
    print(f"[DEBUG] Starting tree parsing")
    print(f"[DEBUG] Total pages: {len(page_list)}")
    print(f"[DEBUG] Total tokens: {sum(p[1] for p in page_list):,}")
    print(f"{'='*60}\n")

    _report("tree_building", progress=11, message="Building document structure...")

    # Stage: TOC Detection
    check_toc_result = check_toc(page_list, opt)
    logger.info(check_toc_result)

    has_toc = check_toc_result.get("toc_content") and check_toc_result["toc_content"].strip() and check_toc_result.get("page_index_given_in_toc") == "yes"
    print(f"[DEBUG] TOC Detection: {'Found' if has_toc else 'Not Found - will generate structure'}")

    # Stage: TOC Processing
    async with monitor.stage("toc_processing"):
        if check_toc_result.get("toc_content") and check_toc_result["toc_content"].strip() and check_toc_result.get("page_index_given_in_toc") == "yes":
            _report("toc_processing", progress=12, message="Processing table of contents...")
            toc_with_page_number = await meta_processor(
                page_list,
                mode='process_toc_with_page_numbers',
                start_index=1,
                toc_content=check_toc_result['toc_content'],
                toc_page_list=check_toc_result['toc_page_list'],
                opt=opt,
                logger=logger)
        else:
            print(f"[DEBUG] Processing mode: process_no_toc (auto-generate structure)")
            toc_with_page_number = await meta_processor(
                page_list,
                mode='process_no_toc',
                start_index=1,
                opt=opt,
                logger=logger)

    print(f"[DEBUG] TOC items found: {len(toc_with_page_number)}")
    _report("toc_processing", progress=38, message=f"Found {len(toc_with_page_number)} sections")

    # Stage: TOC Post-processing
    async with monitor.stage("toc_postprocessing"):
        _report("toc_postprocessing", progress=45, message="Post-processing structure...")
        toc_with_page_number = add_preface_if_needed(toc_with_page_number)
        toc_with_page_number = await check_title_appearance_in_start_concurrent(toc_with_page_number, page_list, model=opt.model, logger=logger)

    # Filter out items with None physical_index before post_processings
    valid_toc_items = [item for item in toc_with_page_number if item.get('physical_index') is not None]
    invalid_count = len(toc_with_page_number) - len(valid_toc_items)
    print(f"[DEBUG] Valid TOC items: {len(valid_toc_items)} (filtered: {invalid_count})")

    _report("tree_building", progress=58, message="Building tree hierarchy...")

    toc_tree = post_processing(valid_toc_items, len(page_list))

    # Debug: Tree structure info
    from pageindex.utils import structure_to_list
    all_nodes = structure_to_list(toc_tree)

    def calculate_tree_depth(tree, current_depth=0):
        """Calculate the maximum depth of the tree structure."""
        if not tree or 'nodes' not in tree or not tree['nodes']:
            return current_depth
        return max(calculate_tree_depth(child, current_depth + 1) for child in tree['nodes'])

    max_depth = calculate_tree_depth(toc_tree)
    print(f"[DEBUG] Tree nodes created: {len(all_nodes)}, max depth: {max_depth}")
    _report("tree_building", progress=59, message=f"Tree built: {len(all_nodes)} nodes, depth {max_depth}")

    # Stage: Large Node Processing
    async with monitor.stage("large_node_processing"):
        large_nodes = [n for n in toc_tree if n.get('end_index', 0) - n.get('start_index', 0) > opt.max_page_num_each_node]
        if large_nodes:
            print(f"[DEBUG] Large nodes to process: {len(large_nodes)} (threshold: {opt.max_page_num_each_node} pages)")
            _report("large_node_processing", progress=60, message=f"Processing {len(large_nodes)} large section(s)...")
            for node in large_nodes:
                pages = node.get('end_index', 0) - node.get('start_index', 0)
                title = node.get('title', 'Unknown')[:40]
                print(f"  - '{title}...': {pages} pages")
        else:
            print(f"[DEBUG] No large nodes found (all nodes within {opt.max_page_num_each_node} pages)")

        tasks = [
            process_large_node_recursively(node, page_list, opt, logger=logger)
            for node in toc_tree
        ]
        await asyncio.gather(*tasks)

    # Final node count
    from pageindex.utils import structure_to_list
    final_nodes = structure_to_list(toc_tree)
    print(f"[DEBUG] Final tree nodes after large node processing: {len(final_nodes)}\n")
    _report("large_node_processing", progress=62, message=f"Final tree: {len(final_nodes)} nodes")

    return toc_tree


def page_index_main(doc, opt=None):
    """
    Main entry point for PDF parsing with performance monitoring.

    Performance tracking stages:
    - pdf_tokenization: Token counting
    - toc_detection: Finding TOC pages
    - toc_transformation: Converting TOC to JSON
    - toc_verification: Validating TOC entries
    - toc_fix: Fixing incorrect entries
    - tree_building: Building tree structure
    - large_node_processing: Handling oversized nodes
    - summary_generation: Creating node summaries
    """
    # Initialize performance monitor
    # Always reset for a fresh parse to avoid mixing data from previous runs
    reset_monitor()
    monitor = get_monitor()

    logger = JsonLogger(doc)

    is_valid_pdf = (
        (isinstance(doc, str) and os.path.isfile(doc) and doc.lower().endswith(".pdf")) or
        isinstance(doc, BytesIO)
    )
    if not is_valid_pdf:
        raise ValueError("Unsupported input type. Expected a PDF file path or BytesIO object.")

    # Set document_id for progress callbacks (from progress_callback registry)
    doc_id = get_document_id()
    if doc_id:
        _report("pdf_tokenization", progress=1, message="Reading PDF and counting tokens...")

    print('Parsing PDF...')

    # Stage: PDF Tokenization
    import time
    token_start = time.time()
    page_list = get_page_tokens(doc)
    token_duration = time.time() - token_start
    logger.info(f'[PERF] Stage: pdf_tokenization completed in {token_duration:.2f}s')

    logger.info({'total_page_number': len(page_list)})
    logger.info({'total_token': sum([page[1] for page in page_list])})

    _report("pdf_tokenization", progress=5,
           message=f"PDF loaded: {len(page_list)} pages, {sum([page[1] for page in page_list]):,} tokens")

    async def page_index_builder():
        # Stage: Tree Building (includes all TOC processing)
        async with monitor.stage("tree_building"):
            structure = await tree_parser(page_list, opt, doc=doc, logger=logger)

        if opt.if_add_node_id == 'yes':
            write_node_id(structure)
        if opt.if_add_node_text == 'yes':
            add_node_text(structure, page_list)

        if opt.if_add_node_summary == 'yes':
            async with monitor.stage("summary_generation"):
                from pageindex.utils import structure_to_list
                nodes_to_summarize = structure_to_list(structure)
                print(f"[DEBUG] Generating summaries for {len(nodes_to_summarize)} nodes...")
                _report("summary_generation", progress=63,
                       message=f"Generating summaries for {len(nodes_to_summarize)} sections...")

                if opt.if_add_node_text == 'no':
                    add_node_text(structure, page_list)

                # Generate summaries with progress tracking
                await _generate_summaries_with_progress(structure, model=opt.model, total_nodes=len(nodes_to_summarize))

                if opt.if_add_node_text == 'no':
                    remove_structure_text(structure)
                print(f"[DEBUG] Summary generation completed")
                _report("summary_generation", progress=95, message="Summarization complete")
            if opt.if_add_doc_description == 'yes':
                # Create a clean structure without unnecessary fields for description generation
                clean_structure = create_clean_structure_for_description(structure)
                doc_description = generate_doc_description(clean_structure, model=opt.model)
                return {
                    'doc_name': get_pdf_name(doc),
                    'doc_description': doc_description,
                    'structure': structure,
                }
        return {
            'doc_name': get_pdf_name(doc),
            'structure': structure,
        }

    result = asyncio.run(page_index_builder())

    # Get performance summary before returning
    perf_summary = monitor.get_summary()

    # Print performance summary
    monitor.print_summary()

    # Return result with performance data
    return {
        "result": result,
        "performance": perf_summary
    }


async def _generate_summaries_with_progress(structure, model, total_nodes):
    """Generate summaries with progress reporting."""
    import asyncio
    from pageindex.utils import structure_to_list

    nodes = structure_to_list(structure)
    completed = 0

    async def summarize_node(node):
        nonlocal completed
        try:
            await generate_summary_for_node(node, model)
            completed += 1
            # Report progress from 63% to 95%
            progress = 63 + (completed / total_nodes) * 32
            _report("summary_generation", progress,
                   message=f"Summarized {completed}/{total_nodes} sections",
                   metadata={"node": node.get('title', 'Unknown')[:50]})
        except Exception as e:
            print(f"Error summarizing node {node.get('title', 'Unknown')}: {e}")
            completed += 1

    # Summarize nodes concurrently with limit
    tasks = []
    semaphore = asyncio.Semaphore(10)  # Max 10 concurrent summaries

    async def bounded_summarize(node):
        async with semaphore:
            await summarize_node(node)

    for node in nodes:
        tasks.append(bounded_summarize(node))

    await asyncio.gather(*tasks)


async def generate_summary_for_node(node, model):
    """Generate summary for a single node."""
    from .utils import ChatGPT_API_async

    if 'text' not in node or not node['text']:
        return

    content = node['text']
    title = node.get('title', '')

    # Truncate content if too long (keep first 3000 chars)
    if len(content) > 3000:
        content = content[:3000]

    prompt = f"""Summarize the following section from a document in 1-2 sentences.

Section Title: {title}

Content:
{content}

Provide a concise summary that captures the main points."""

    try:
        summary = await ChatGPT_API_async(model=model, prompt=prompt)
        node['summary'] = summary.strip()
    except Exception as e:
        print(f"Error generating summary: {e}")
        node['summary'] = ""


def page_index(doc, model=None, toc_check_page_num=None, max_page_num_each_node=None, max_token_num_each_node=None,
               if_add_node_id=None, if_add_node_summary=None, if_add_doc_description=None, if_add_node_text=None):
    
    user_opt = {
        arg: value for arg, value in locals().items()
        if arg != "doc" and value is not None
    }
    opt = ConfigLoader().load(user_opt)
    return page_index_main(doc, opt)


def validate_and_truncate_physical_indices(toc_with_page_number, page_list_length, start_index=1, logger=None):
    """
    Validates and truncates physical indices that exceed the actual document length.
    This prevents errors when TOC references pages that don't exist in the document (e.g. the file is broken or incomplete).
    Enhanced to also check for indices less than start_index.
    """
    if not toc_with_page_number:
        return toc_with_page_number

    max_allowed_page = page_list_length + start_index - 1
    truncated_items = []
    invalid_items = []

    for i, item in enumerate(toc_with_page_number):
        if item.get('physical_index') is not None:
            original_index = item['physical_index']

            # Check 1: Index exceeds maximum allowed page
            if original_index > max_allowed_page:
                item['physical_index'] = None
                truncated_items.append({
                    'title': item.get('title', 'Unknown'),
                    'original_index': original_index,
                    'reason': 'exceeds_max'
                })
                if logger:
                    logger.info(f"Removed physical_index for '{item.get('title', 'Unknown')}' (was {original_index}, exceeds max page {max_allowed_page})")

            # Check 2: Index is less than start_index (invalid)
            elif original_index < start_index:
                item['physical_index'] = None
                invalid_items.append({
                    'title': item.get('title', 'Unknown'),
                    'original_index': original_index,
                    'reason': 'below_start'
                })
                if logger:
                    logger.warning(f"Removed physical_index for '{item.get('title', 'Unknown')}' (was {original_index}, below start index {start_index})")

    if truncated_items and logger:
        logger.info(f"Total removed items (exceeds max): {len(truncated_items)}")

    if invalid_items and logger:
        logger.info(f"Total removed items (below start): {len(invalid_items)}")

    print(f"Document validation: {page_list_length} pages, valid range: {start_index}-{max_allowed_page}")
    if truncated_items:
        print(f"  - Truncated {len(truncated_items)} TOC items that exceeded document length")
    if invalid_items:
        print(f"  - Removed {len(invalid_items)} TOC items with invalid page numbers (below start)")

    return toc_with_page_number