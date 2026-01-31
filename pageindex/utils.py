import tiktoken
import openai
import logging
import os
import random
from datetime import datetime
import time
import json
from typing import Optional, List
import PyPDF2
import copy
import asyncio
import pymupdf
import re
from io import BytesIO
from dotenv import load_dotenv
from markitdown import MarkItDown
load_dotenv()
import logging
import yaml
from pathlib import Path
from types import SimpleNamespace as config

# Unified LLM configuration (same as API service)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")

# Provider configuration (matches api/services.py)
PROVIDER_CONFIG = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "max_tokens": 8192  # DeepSeek limit
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,  # Use default OpenAI URL
        "default_model": "gpt-4o-mini",
        "max_tokens": 16384  # Safe limit for most OpenAI models
    },
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "base_url": None,  # Gemini uses different API
        "default_model": "gemini-1.5-flash",
        "max_tokens": 8192  # Gemini flash limit
    },
    "openrouter": {
        "api_key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "deepseek/deepseek-chat",
        "max_tokens": 16384  # 16K - reasonable limit for most responses
    },
    "zhipu": {
        "api_key_env": "ZHIPU_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        "default_model": "glm-4.7",
        "max_tokens": 8192  # Zhipu limit
    }
}

def get_llm_config():
    """Get LLM config based on LLM_PROVIDER environment variable."""
    provider = LLM_PROVIDER
    if provider not in PROVIDER_CONFIG:
        raise ValueError(f"Unsupported provider: {provider}. Use one of: {list(PROVIDER_CONFIG.keys())}")

    config = PROVIDER_CONFIG[provider]
    api_key = os.getenv(config["api_key_env"])
    if not api_key:
        raise ValueError(f"API key not found. Set {config['api_key_env']} environment variable.")

    return {
        "api_key": api_key,
        "base_url": config["base_url"],
        "model": config["default_model"],
        "max_tokens": config.get("max_tokens", 8192)  # Default to 8192 if not specified
   }

# Get LLM config at module load time
_llm_config = get_llm_config()
CHATGPT_API_KEY = _llm_config["api_key"]
OPENAI_BASE_URL = _llm_config["base_url"]
MAX_TOKENS = _llm_config["max_tokens"]

def count_tokens(text, model=None):
    if not text:
        return 0
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        # For DeepSeek and other OpenAI-compatible models, use cl100k_base encoding
        enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    return len(tokens)

def ChatGPT_API_with_finish_reason(model, prompt, api_key=CHATGPT_API_KEY, chat_history=None, base_url=OPENAI_BASE_URL):
    """
    Send chat request to OpenAI-compatible API with retry and exponential backoff.
    Returns (response_content, finish_reason).
    """
    max_retries = 10
    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    # Import monitor lazily to avoid circular imports
    try:
        from .performance_monitor import get_monitor
        monitor = get_monitor()
        stage = monitor._current_stage or "unknown"
    except Exception:
        stage = "unknown"

    for i in range(max_retries):
        start_time = time.time()
        try:
            if chat_history:
                messages = chat_history
                messages.append({"role": "user", "content": prompt})
            else:
                messages = [{"role": "user", "content": prompt}]

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=MAX_TOKENS,
            )

            # Track LLM call with performance monitoring
            try:
                input_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') and response.usage else 0
                output_tokens = response.usage.completion_tokens if hasattr(response, 'usage') and response.usage else 0
                duration = time.time() - start_time

                # Debug: Log token usage
                print(f"[LLM] stage={stage} in={input_tokens} out={output_tokens} time={duration:.2f}s")

                monitor = get_monitor()
                monitor.track_llm_call(
                    stage=stage,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=(i == 0),
                    retry=(i > 0)
                )
            except Exception:
                pass  # Silently fail if monitor not available

            if response.choices[0].finish_reason == "length":
                return response.choices[0].message.content, "max_output_reached"
            else:
                return response.choices[0].message.content, "finished"

        except Exception as e:
            error_msg = str(e).lower()

            # Don't retry on certain errors
            if any(x in error_msg for x in [
                "authentication", "unauthorized", "invalid_api_key",
                "permission", "quota", "insufficient_quota", "401", "403", "429"
            ]):
                logging.error(f"Non-retryable error in ChatGPT_API_with_finish_reason: {e}")
                return "Error", "error"

            # Log retry attempt
            if i < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s, 8s...
                wait_time = min(2 ** i, 8) + random.uniform(0, 0.5)
                logging.warning(f"ChatGPT_API_with_finish_reason failed (attempt {i + 1}/{max_retries}), "
                                f"retrying in {wait_time:.1f}s. Error: {e}")
                time.sleep(wait_time)
            else:
                logging.error(f"ChatGPT_API_with_finish_reason failed after {max_retries} attempts. Error: {e}")
                return "Error", "error"



def ChatGPT_API(model, prompt, api_key=CHATGPT_API_KEY, chat_history=None, base_url=OPENAI_BASE_URL):
    """
    Send chat request to OpenAI-compatible API with retry and exponential backoff.
    """
    max_retries = 10
    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    # Import monitor lazily to avoid circular imports
    try:
        from .performance_monitor import get_monitor
        monitor = get_monitor()
        stage = monitor._current_stage or "unknown"
    except Exception:
        stage = "unknown"

    for i in range(max_retries):
        start_time = time.time()
        try:
            if chat_history:
                messages = chat_history
                messages.append({"role": "user", "content": prompt})
            else:
                messages = [{"role": "user", "content": prompt}]

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=MAX_TOKENS,
            )

            # Track LLM call with performance monitoring
            try:
                input_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') and response.usage else 0
                output_tokens = response.usage.completion_tokens if hasattr(response, 'usage') and response.usage else 0
                duration = time.time() - start_time

                # Debug: Log token usage
                print(f"[LLM] stage={stage} in={input_tokens} out={output_tokens} time={duration:.2f}s")

                monitor = get_monitor()
                monitor.track_llm_call(
                    stage=stage,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=(i == 0),
                    retry=(i > 0)
                )
            except Exception:
                pass  # Silently fail if monitor not available

            return response.choices[0].message.content

        except Exception as e:
            error_msg = str(e).lower()

            # Don't retry on certain errors
            if any(x in error_msg for x in [
                "authentication", "unauthorized", "invalid_api_key",
                "permission", "quota", "insufficient_quota", "401", "403", "429"
            ]):
                logging.error(f"Non-retryable error in ChatGPT_API: {e}")
                return "Error"

            # Log retry attempt
            if i < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s, 8s...
                wait_time = min(2 ** i, 8) + random.uniform(0, 0.5)
                logging.warning(f"ChatGPT_API failed (attempt {i + 1}/{max_retries}), "
                                f"retrying in {wait_time:.1f}s. Error: {e}")
                time.sleep(wait_time)
            else:
                logging.error(f"ChatGPT_API failed after {max_retries} attempts. Error: {e}")
                return "Error"
            

async def ChatGPT_API_async(model, prompt, api_key=CHATGPT_API_KEY, base_url=OPENAI_BASE_URL):
    """
    Send async chat request to OpenAI-compatible API with retry and exponential backoff.
    """
    max_retries = 10
    messages = [{"role": "user", "content": prompt}]

    # Import monitor lazily to avoid circular imports
    try:
        from .performance_monitor import get_monitor
        monitor = get_monitor()
        stage = monitor._current_stage or "unknown"
    except Exception:
        stage = "unknown"

    for i in range(max_retries):
        start_time = time.time()
        try:
            async with openai.AsyncOpenAI(api_key=api_key, base_url=base_url) as client:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                    max_tokens=MAX_TOKENS,
                )

                # Track LLM call with performance monitoring
                try:
                    input_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') and response.usage else 0
                    output_tokens = response.usage.completion_tokens if hasattr(response, 'usage') and response.usage else 0
                    duration = time.time() - start_time

                    # Debug: Log token usage
                    print(f"[LLM] stage={stage} in={input_tokens} out={output_tokens} time={duration:.2f}s")

                    monitor = get_monitor()
                    monitor.track_llm_call(
                        stage=stage,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        success=(i == 0),
                        retry=(i > 0)
                    )
                except Exception:
                    pass  # Silently fail if monitor not available

                return response.choices[0].message.content

        except Exception as e:
            error_msg = str(e).lower()

            # Don't retry on certain errors
            if any(x in error_msg for x in [
                "authentication", "unauthorized", "invalid_api_key",
                "permission", "quota", "insufficient_quota", "401", "403", "429"
            ]):
                logging.error(f"Non-retryable error in ChatGPT_API_async: {e}")
                return "Error"

            # Log retry attempt
            if i < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s, 8s...
                wait_time = min(2 ** i, 8) + random.uniform(0, 0.5)
                logging.warning(f"ChatGPT_API_async failed (attempt {i + 1}/{max_retries}), "
                                f"retrying in {wait_time:.1f}s. Error: {e}")
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"ChatGPT_API_async failed after {max_retries} attempts. Error: {e}")
                return "Error"
            
def get_json_content(response):
    start_idx = response.find("```json")
    if start_idx != -1:
        start_idx += 7
        response = response[start_idx:]
        
    end_idx = response.rfind("```")
    if end_idx != -1:
        response = response[:end_idx]
    
    json_content = response.strip()
    return json_content
         

def extract_json(content):
    """
    Extract JSON from content, handling markdown code blocks and extra text.
    """
    try:
        # First, try to extract JSON enclosed within ```json and ```
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7  # Adjust index to start after the delimiter
            end_idx = content.rfind("```")
            json_content = content[start_idx:end_idx].strip()
        else:
            # If no delimiters, assume entire content could be JSON
            json_content = content.strip()

        # Clean up common issues that might cause parsing errors
        json_content = json_content.replace('None', 'null')  # Replace Python None with JSON null
        json_content = ' '.join(json_content.split())  # Normalize whitespace

        # Attempt to parse and return the JSON object
        return json.loads(json_content)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to extract JSON: {e}")
        # If "Extra data" error, try to find the end of valid JSON
        if "Extra data" in str(e):
            try:
                # Find the end of the JSON by matching brackets
                content_stripped = json_content.strip()
                if content_stripped.startswith('{'):
                    # Find matching closing brace
                    brace_count = 0
                    in_string = False
                    escape_next = False
                    end_pos = 0
                    for i, char in enumerate(content_stripped):
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
                            if char == '{':
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    end_pos = i + 1
                                    break
                    if end_pos > 0:
                        json_content = content_stripped[:end_pos]
                        return json.loads(json_content)
            except Exception as e2:
                logging.error(f"Failed to extract JSON by bracket matching: {e2}")

        # Try to clean up the content further if initial parsing fails
        try:
            # Remove any trailing commas before closing brackets/braces
            json_content = json_content.replace(',]', ']').replace(',}', '}')
            return json.loads(json_content)
        except:
            logging.error("Failed to parse JSON even after cleanup")
            return None
    except Exception as e:
        logging.error(f"Unexpected error while extracting JSON: {e}")
        return None


# ============================================================================
# Enhanced JSON Parsing (v2.0.0 Accuracy Improvements)
# ============================================================================

def validate_json_schema(data, schema_type='toc'):
    """
    Validate JSON data against expected schema.
    
    Args:
        data: Parsed JSON data to validate
        schema_type: Type of schema - 'toc', 'title_check', 'appear_start'
    
    Returns:
        bool: True if data matches expected schema
    """
    import re
    
    if schema_type == 'toc':
        # TOC schema: list of dicts with structure, title, physical_index
        if not isinstance(data, list):
            return False
        
        required_keys = {'structure', 'title', 'physical_index'}
        for item in data:
            if not isinstance(item, dict):
                return False
            if not required_keys.issubset(item.keys()):
                return False
            # Validate physical_index format - accept both placeholder format and integer
            physical_idx = item.get('physical_index')
            # Accept either: <physical_index_N> format OR an integer (or string representation of integer)
            if isinstance(physical_idx, int):
                # Direct integer is valid
                continue
            elif isinstance(physical_idx, str):
                # String must be either placeholder format or parseable as integer
                if not re.match(r'<physical_index_\d+>', physical_idx):
                    # Try to parse as integer
                    try:
                        int(physical_idx)
                    except ValueError:
                        return False
            else:
                return False
        return True
    
    elif schema_type == 'title_check':
        # Title check schema: dict with 'appear_start' key
        if not isinstance(data, dict):
            return False
        return 'appear_start' in data
    
    elif schema_type == 'appear_start':
        # Appear start schema: list of dicts with 'start' and 'start_index'
        if not isinstance(data, list):
            return False
        for item in data:
            if not isinstance(item, dict):
                return False
            if 'start' not in item or 'start_index' not in item:
                return False
        return True

    elif schema_type == 'single_item_fixer':
        # Single item fixer schema: dict with 'thinking' (optional) and 'physical_index' keys
        if not isinstance(data, dict):
            return False
        if 'physical_index' not in data:
            return False
        # Validate physical_index - accept integer, null, or string that can be parsed as integer
        physical_idx = data.get('physical_index')
        # Allow None (null) for cases where LLM cannot find the title
        if physical_idx is None:
            return True
        if isinstance(physical_idx, int):
            return True
        elif isinstance(physical_idx, str):
            try:
                int(physical_idx)
                return True
            except ValueError:
                return False
        return False

    # Unknown schema type
    return False


def extract_json_markdown_block(content):
    """
    Extract JSON from markdown code blocks (```json ... ```).
    
    Args:
        content: Raw text content
    
    Returns:
        dict or list: Parsed JSON, or None if extraction fails
    """
    try:
        # Try to find ```json ... ``` block
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7  # Skip past ```json
            end_idx = content.find("```", start_idx)
            if end_idx != -1:
                json_str = content[start_idx:end_idx].strip()
                # Clean up
                json_str = json_str.replace('None', 'null')
                return json.loads(json_str)
        
        # Try ``` without json marker
        start_idx = content.find("```")
        if start_idx != -1:
            start_idx += 3
            end_idx = content.find("```", start_idx)
            if end_idx != -1:
                json_str = content[start_idx:end_idx].strip()
                json_str = json_str.replace('None', 'null')
                return json.loads(json_str)
        
        return None
    except Exception as e:
        logging.debug(f"Markdown block extraction failed: {e}")
        return None


def extract_json_bracket_matching(content):
    """
    Extract JSON by finding matching brackets/braces.
    Handles both objects {...} and arrays [...].
    
    Args:
        content: Raw text content
    
    Returns:
        dict or list: Parsed JSON, or None if extraction fails
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
        # Try to find JSON array [...] first (more common for TOC)
        json_str = find_matching_bracket(content, '[', ']')
        if json_str:
            json_str = json_str.replace('None', 'null')
            return json.loads(json_str)
        
        # Try to find JSON object {...}
        json_str = find_matching_bracket(content, '{', '}')
        if json_str:
            json_str = json_str.replace('None', 'null')
            return json.loads(json_str)
        
        return None
    except Exception as e:
        logging.debug(f"Bracket matching extraction failed: {e}")
        return None


def extract_json_regex_patterns(content):
    """
    Extract JSON using regex patterns as fallback.
    
    Args:
        content: Raw text content
    
    Returns:
        dict or list: Parsed JSON, or None if extraction fails
    """
    import re
    
    try:
        # Pattern 1: JSON in code fence with optional language marker
        pattern1 = r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```'
        match = re.search(pattern1, content, re.DOTALL)
        if match:
            json_str = match.group(1).replace('None', 'null')
            return json.loads(json_str)
        
        # Pattern 2: JSON object without code fence
        pattern2 = r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'
        match = re.search(pattern2, content, re.DOTALL)
        if match:
            json_str = match.group(1).replace('None', 'null')
            return json.loads(json_str)
        
        # Pattern 3: JSON array without code fence
        pattern3 = r'(\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])'
        match = re.search(pattern3, content, re.DOTALL)
        if match:
            json_str = match.group(1).replace('None', 'null')
            return json.loads(json_str)
        
        return None
    except Exception as e:
        logging.debug(f"Regex pattern extraction failed: {e}")
        return None


def extract_json_llm_repair(content, model=None, schema_type='toc'):
    """
    Use LLM to repair malformed JSON as last resort.
    
    Args:
        content: Malformed JSON text
        model: LLM model to use for repair
        schema_type: Expected schema type
    
    Returns:
        dict or list: Repaired and parsed JSON, or None if repair fails
    """
    try:
        if model is None:
            model = 'deepseek-chat'  # Default model
        
        repair_prompt = f"""The following text contains malformed JSON that needs to be fixed.
Please extract and repair it to match the {schema_type} schema format.

Requirements:
- Return ONLY valid JSON, no explanation
- Maintain all original data
- Fix syntax errors (missing commas, quotes, brackets)
- Ensure proper formatting

Text to repair:
{content[:2000]}

Return the corrected JSON:"""
        
        response = ChatGPT_API(model=model, prompt=repair_prompt)
        
        # Try to extract from repaired response
        return extract_json_markdown_block(response) or extract_json_bracket_matching(response)
    
    except Exception as e:
        logging.error(f"LLM repair failed: {e}")
        return None


def extract_json_v2(content, max_retries=2, expected_schema='toc', model=None):
    """
    Enhanced JSON extraction with multiple fallback strategies.
    
    This is the main entry point for improved JSON parsing. It tries
    multiple strategies in order of reliability:
    1. Markdown code block extraction
    2. Bracket matching
    3. Regex patterns
    4. LLM repair (last resort)
    
    Args:
        content: Raw text content from LLM response
        max_retries: Maximum LLM repair attempts (default: 2)
        expected_schema: Expected schema type for validation
        model: LLM model for repair attempts
    
    Returns:
        dict or list: Parsed and validated JSON, or None if all strategies fail
    """
    # Define strategies in priority order
    strategies = [
        ('markdown_block', extract_json_markdown_block),
        ('bracket_match', extract_json_bracket_matching),
        ('regex_pattern', extract_json_regex_patterns),
    ]
    
    # Try each strategy
    for strategy_name, strategy_func in strategies:
        try:
            result = strategy_func(content)
            
            if result is not None:
                # Validate against expected schema
                if validate_json_schema(result, expected_schema):
                    logging.debug(f"JSON extracted successfully via {strategy_name}")
                    return result
                else:
                    logging.debug(f"JSON from {strategy_name} failed schema validation")
        
        except Exception as e:
            logging.debug(f"Strategy {strategy_name} failed: {e}")
            continue
    
    # Last resort: Try LLM repair
    if max_retries > 0:
        logging.info(f"All extraction strategies failed. Attempting LLM repair (retries={max_retries})")
        try:
            repaired = extract_json_llm_repair(content, model, expected_schema)
            if repaired and validate_json_schema(repaired, expected_schema):
                logging.info("JSON successfully repaired by LLM")
                return repaired
        except Exception as e:
            logging.error(f"LLM repair failed: {e}")
    
    # All strategies failed
    logging.error(f"All JSON extraction strategies failed. Content preview: {content[:500]}")
    return None




async def extract_json_with_retry(
    llm_provider,  # LLMProvider instance
    prompt: str,
    model: Optional[str] = None,
    max_retries: int = 2,
    expected_keys: Optional[List[str]] = None
) -> Optional[dict]:
    """
    Extract JSON from LLM response with retry mechanism.

    Args:
        llm_provider: LLMProvider instance for retry
        prompt: The prompt to send
        model: Model override
        max_retries: Maximum retry attempts
        expected_keys: Expected keys in JSON for validation

    Returns:
        Parsed JSON dict or None if all retries fail
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            response = await llm_provider.chat(prompt, model=model)
            json_content = extract_json(response)

            # Validate expected keys if provided
            if json_content is not None:
                if isinstance(json_content, dict):
                    if expected_keys:
                        missing_keys = [k for k in expected_keys if k not in json_content]
                        if missing_keys:
                            raise ValueError(f"Missing expected keys: {missing_keys}")
                    return json_content
                else:
                    # Not a dict as expected
                    raise ValueError(f"Expected dict but got {type(json_content)}")

            # JSON extraction failed
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 0.5)
                logging.warning(f"JSON extraction failed (attempt {attempt + 1}/{max_retries}), "
                                f"retrying in {wait_time:.1f}s. Response preview: {response[:200]}...")
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"JSON extraction failed after {max_retries} attempts")

        except ValueError as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 0.5)
                logging.warning(f"JSON validation failed (attempt {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"JSON validation failed after {max_retries} attempts: {e}")

        except Exception as e:
            last_error = e
            logging.error(f"Unexpected error in extract_json_with_retry: {e}")
            break

    logging.error(f"All retry attempts failed. Last error: {last_error}")
    return None

def write_node_id(data, node_id=0):
    if isinstance(data, dict):
        data['node_id'] = str(node_id).zfill(4)
        node_id += 1
        for key in list(data.keys()):
            if 'nodes' in key:
                node_id = write_node_id(data[key], node_id)
    elif isinstance(data, list):
        for index in range(len(data)):
            node_id = write_node_id(data[index], node_id)
    return node_id

def get_nodes(structure):
    if isinstance(structure, dict):
        structure_node = copy.deepcopy(structure)
        structure_node.pop('nodes', None)
        nodes = [structure_node]
        for key in list(structure.keys()):
            if 'nodes' in key:
                nodes.extend(get_nodes(structure[key]))
        return nodes
    elif isinstance(structure, list):
        nodes = []
        for item in structure:
            nodes.extend(get_nodes(item))
        return nodes
    
def structure_to_list(structure):
    if isinstance(structure, dict):
        nodes = []
        nodes.append(structure)
        if 'nodes' in structure:
            nodes.extend(structure_to_list(structure['nodes']))
        return nodes
    elif isinstance(structure, list):
        nodes = []
        for item in structure:
            nodes.extend(structure_to_list(item))
        return nodes

    
def get_leaf_nodes(structure):
    if isinstance(structure, dict):
        if not structure['nodes']:
            structure_node = copy.deepcopy(structure)
            structure_node.pop('nodes', None)
            return [structure_node]
        else:
            leaf_nodes = []
            for key in list(structure.keys()):
                if 'nodes' in key:
                    leaf_nodes.extend(get_leaf_nodes(structure[key]))
            return leaf_nodes
    elif isinstance(structure, list):
        leaf_nodes = []
        for item in structure:
            leaf_nodes.extend(get_leaf_nodes(item))
        return leaf_nodes

def is_leaf_node(data, node_id):
    # Helper function to find the node by its node_id
    def find_node(data, node_id):
        if isinstance(data, dict):
            if data.get('node_id') == node_id:
                return data
            for key in data.keys():
                if 'nodes' in key:
                    result = find_node(data[key], node_id)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = find_node(item, node_id)
                if result:
                    return result
        return None

    # Find the node with the given node_id
    node = find_node(data, node_id)

    # Check if the node is a leaf node
    if node and not node.get('nodes'):
        return True
    return False

def get_last_node(structure):
    return structure[-1]


def extract_text_from_pdf(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    ###return text not list 
    text=""
    for page_num in range(len(pdf_reader.pages)):
        page = pdf_reader.pages[page_num]
        text+=page.extract_text()
    return text

def get_pdf_title(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    meta = pdf_reader.metadata
    title = meta.title if meta and meta.title else 'Untitled'
    return title

def get_text_of_pages(pdf_path, start_page, end_page, tag=True):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    text = ""
    for page_num in range(start_page-1, end_page):
        page = pdf_reader.pages[page_num]
        page_text = page.extract_text()
        if tag:
            text += f"<start_index_{page_num+1}>\n{page_text}\n<end_index_{page_num+1}>\n"
        else:
            text += page_text
    return text

def get_first_start_page_from_text(text):
    start_page = -1
    start_page_match = re.search(r'<start_index_(\d+)>', text)
    if start_page_match:
        start_page = int(start_page_match.group(1))
    return start_page

def get_last_start_page_from_text(text):
    start_page = -1
    # Find all matches of start_index tags
    start_page_matches = re.finditer(r'<start_index_(\d+)>', text)
    # Convert iterator to list and get the last match if any exist
    matches_list = list(start_page_matches)
    if matches_list:
        start_page = int(matches_list[-1].group(1))
    return start_page


def sanitize_filename(filename, replacement='-'):
    # In Linux, only '/' and '\0' (null) are invalid in filenames.
    # Null can't be represented in strings, so we only handle '/'.
    return filename.replace('/', replacement)

def get_pdf_name(pdf_path):
    # Extract PDF name
    if isinstance(pdf_path, str):
        pdf_name = os.path.basename(pdf_path)
    elif isinstance(pdf_path, BytesIO):
        pdf_reader = PyPDF2.PdfReader(pdf_path)
        meta = pdf_reader.metadata
        pdf_name = meta.title if meta and meta.title else 'Untitled'
        pdf_name = sanitize_filename(pdf_name)
    return pdf_name


class JsonLogger:
    def __init__(self, file_path):
        # Extract PDF name for logger name
        pdf_name = get_pdf_name(file_path)
            
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = f"{pdf_name}_{current_time}.json"
        os.makedirs("./logs", exist_ok=True)
        # Initialize empty list to store all messages
        self.log_data = []

    def log(self, level, message, **kwargs):
        if isinstance(message, dict):
            self.log_data.append(message)
        else:
            self.log_data.append({'message': message})
        # Add new message to the log data
        
        # Write entire log data to file
        with open(self._filepath(), "w") as f:
            json.dump(self.log_data, f, indent=2)

    def info(self, message, **kwargs):
        self.log("INFO", message, **kwargs)

    def warning(self, message, **kwargs):
        self.log("WARNING", message, **kwargs)

    def error(self, message, **kwargs):
        self.log("ERROR", message, **kwargs)

    def debug(self, message, **kwargs):
        self.log("DEBUG", message, **kwargs)

    def exception(self, message, **kwargs):
        kwargs["exception"] = True
        self.log("ERROR", message, **kwargs)

    def _filepath(self):
        return os.path.join("logs", self.filename)
    



def normalize_structure(structure):
    """
    Normalize various structure formats to standard numeric format.

    This improves robustness by handling LLM outputs that don't follow
    the expected "x.x.x" numeric format.

    Examples:
        "第一部分" → "1"
        "二" → "2"
        "4.综合比较与评价" → "4"
        "二.1" → "2.1"
        "1.1" → "1.1" (unchanged)
        "1.2.1" → "1.2.1" (unchanged)

    Args:
        structure: The structure string to normalize

    Returns:
        Normalized structure string in numeric format
    """
    if not structure:
        return structure

    structure = str(structure).strip()

    # Case 1: Already in standard format (numbers and dots only)
    # e.g., "1", "1.1", "1.2.3"
    if re.match(r'^[\d.]+$', structure):
        return structure

    # Case 2: Chinese ordinal numbers (第X部分)
    # e.g., "第一部分" → "1", "第二部分" → "2"
    match = re.match(r'第([一二三四五六七八九十百]+)部分', structure)
    if match:
        chinese_num = match.group(1)
        # Map Chinese numbers to digits
        cn_to_digits = {
            '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
            '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'
        }
        if chinese_num in cn_to_digits:
            return cn_to_digits[chinese_num]
        # Handle compound numbers like "十一", "十二"
        elif len(chinese_num) == 2 and chinese_num[0] == '十':
            second_digit = cn_to_digits.get(chinese_num[1], '0')
            return '1' + second_digit
        # Fallback: extract any digits from the string
        digits = re.findall(r'\d+', structure)
        return digits[0] if digits else structure

    # Case 3: Chinese numerals with dot-separated sub-items
    # e.g., "二.1" → "2.1", "三.2.1" → "3.2.1"
    if '.' in structure:
        parts = structure.split('.')
        normalized_parts = []
        for part in parts:
            if part in ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']:
                cn_to_digits = {
                    '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
                    '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'
                }
                normalized_parts.append(cn_to_digits[part])
            elif re.match(r'^\d+$', part):
                normalized_parts.append(part)
            else:
                # Keep original if not recognized
                normalized_parts.append(part)
        return '.'.join(normalized_parts) if any(p != part for p, part in zip(normalized_parts, parts)) else structure

    # Case 4: Chinese numerals directly (single level)
    # e.g., "一" → "1", "二" → "2", "三" → "3"
    if structure in ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']:
        cn_to_digits = {
            '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
            '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'
        }
        return cn_to_digits.get(structure, structure)

    # Case 5: Mixed format with number and text
    # e.g., "4.综合比较与评价" → "4"
    match = re.match(r'^(\d+)(?:\.|$)', structure)
    if match:
        return match.group(1)

    # Case 6: Try to extract any leading number
    # e.g., "2.3采购内容" might be parsed by LLM as structure
    match = re.match(r'^([\d.]+)', structure)
    if match:
        extracted = match.group(1)
        # Ensure it's a valid number/dot format
        if re.match(r'^[\d.]+$', extracted):
            return extracted

    # Fallback: return original if no pattern matches
    return structure


def list_to_tree(data):
    import logging
    import re
    logger = logging.getLogger("pageindex.utils")
    logger.info(f"[LIST_TO_TREE] Converting {len(data)} flat items to tree structure")

    # PRE-PROCESSING: Normalize all structure formats
    # This handles various LLM output formats (Chinese, mixed, etc.)
    normalized_count = 0
    for item in data:
        original_structure = item.get('structure')
        if original_structure:
            normalized = normalize_structure(original_structure)
            if normalized != original_structure:
                item['structure'] = normalized
                normalized_count += 1

    if normalized_count > 0:
        logger.info(f"[LIST_TO_TREE] Normalized {normalized_count} structure formats to numeric format")

    def get_parent_structure(structure):
        """Helper function to get the parent structure code"""
        if not structure:
            return None
        parts = str(structure).split('.')
        return '.'.join(parts[:-1]) if len(parts) > 1 else None

    # First pass: Create nodes and track parent-child relationships
    nodes = {}
    root_nodes = []

    for item in data:
        structure = item.get('structure')
        title = item.get('title', '')[:50]
        node = {
            'title': item.get('title'),
            'start_index': item.get('start_index'),
            'end_index': item.get('end_index'),
            'nodes': []
        }

        logger.info(f"[LIST_TO_TREE] Creating node '{title}' (structure={structure}, pages={node['start_index']}-{node['end_index']})")

        nodes[structure] = node

        # Find parent
        parent_structure = get_parent_structure(structure)

        if parent_structure:
            # Add as child to parent if parent exists
            if parent_structure in nodes:
                nodes[parent_structure]['nodes'].append(node)
                logger.info(f"[LIST_TO_TREE] Added '{title}' as child of '{parent_structure}'")
            else:
                root_nodes.append(node)
                logger.info(f"[LIST_TO_TREE] Parent '{parent_structure}' not found yet, '{title}' is root node")
        else:
            # No parent, this is a root node
            root_nodes.append(node)
            logger.info(f"[LIST_TO_TREE] '{title}' is root node (no parent)")

    logger.info(f"[LIST_TO_TREE] Tree built with {len(root_nodes)} root nodes, starting clean_node phase...")
    
    # Helper function to clean empty children arrays and validate page ranges
    def clean_node(node, parent_start=None, parent_end=None, depth=0):
        import logging
        logger = logging.getLogger("pageindex.utils")
        title = node.get('title', '')[:50]
        original_start = node['start_index']
        original_end = node['end_index']
        indent = "  " * depth

        logger.info(f"{indent}[CLEAN_NODE] '{title}': BEFORE start={original_start}, end={original_end}, parent_range=({parent_start},{parent_end})")

        # First, recursively process all children
        if node.get('nodes'):
            logger.info(f"{indent}[CLEAN_NODE] '{title}': processing {len(node['nodes'])} children...")
            for child in node['nodes']:
                clean_node(child, node['start_index'], node['end_index'], depth + 1)

            # After processing children, expand parent's range to cover all children
            # This ensures: parent.start_index <= all children.start_index
            #           parent.end_index >= all children.end_index
            child_min_start = min(child['start_index'] for child in node['nodes'])
            child_max_end = max(child['end_index'] for child in node['nodes'])

            logger.info(f"{indent}[CLEAN_NODE] '{title}': children range = [{child_min_start}, {child_max_end}]")

            node['start_index'] = min(node['start_index'], child_min_start)
            node['end_index'] = max(node['end_index'], child_max_end)

            if node['start_index'] != original_start or node['end_index'] != original_end:
                logger.info(f"{indent}[CLEAN_NODE] '{title}': EXPANDED to cover children: [{original_start},{original_end}] -> [{node['start_index']},{node['end_index']}]")

        # Option A: Parent nodes align to children (per ALGORITHM_PAGE_INDEX.md section 4)
        # Parent nodes will expand to cover all children's ranges
        # Children keep their original calculated ranges without clamping
        # This prevents data loss when a child's content extends beyond parent's original range
        if parent_start is not None and parent_end is not None:
            # Only log if child's range exceeds parent's original range
            # Parent will expand to cover it in the parent's own expansion step
            if node['start_index'] < parent_start or node['end_index'] > parent_end:
                logger.info(f"{indent}[CLEAN_NODE] '{title}': Child range [{node['start_index']},{node['end_index']}] exceeds parent's original range [{parent_start},{parent_end}]")
                logger.info(f"{indent}[CLEAN_NODE] '{title}': Parent will expand to cover this range (Option A)")

            # Ensure start_index <= end_index (basic validation)
            if node['start_index'] > node['end_index']:
                logger.warning(f"{indent}[CLEAN_NODE] '{title}': INVALID start > end ({node['start_index']} > {node['end_index']}), setting start to end")
                node['start_index'] = node['end_index']

        # Remove empty nodes array for leaf nodes
        if not node.get('nodes'):
            node.pop('nodes', None)

        logger.info(f"{indent}[CLEAN_NODE] '{title}': FINAL start={node['start_index']}, end={node['end_index']}")
        return node

    # Clean and return the tree
    logger.info(f"[LIST_TO_TREE] Starting clean_node phase for {len(root_nodes)} root nodes...")
    result = [clean_node(node) for node in root_nodes]
    logger.info(f"[LIST_TO_TREE] Tree conversion complete")
    return result

def add_preface_if_needed(data):
    if not isinstance(data, list) or not data:
        return data

    if data[0]['physical_index'] is not None and data[0]['physical_index'] > 1:
        preface_node = {
            "structure": "0",
            "title": "Preface",
            "physical_index": 1,
        }
        data.insert(0, preface_node)
    return data



def get_page_tokens(pdf_path, model="gpt-4o-2024-11-20", pdf_parser="PyMuPDF"):
    import os
    # Handle OpenRouter format (provider/model) by extracting the model part
    # For token counting, we use a compatible encoding
    tiktoken_model = model
    if "/" in model:
        # Extract the model name from OpenRouter format (e.g., "google/gemini-2.5-flash-lite" -> "gemini-2.5-flash-lite")
        # Fall back to a default encoding if the model is not directly supported
        try:
            tiktoken_model = model.split("/")[-1]
            enc = tiktoken.encoding_for_model(tiktoken_model)
        except KeyError:
            # If not supported, use cl100k_base (GPT-4 encoding) as a reasonable default
            enc = tiktoken.get_encoding("cl100k_base")
    else:
        enc = tiktoken.encoding_for_model(tiktoken_model)

    if pdf_parser == "markitdown":
        # Use Microsoft's markitdown library for better PDF table support
        md = MarkItDown()
        if isinstance(pdf_path, BytesIO):
            # For BytesIO, write to temp file first
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(pdf_path.getvalue())
                tmp_path = tmp.name
            try:
                result = md.convert(tmp_path)
                markdown_text = result.text_content
            finally:
                os.unlink(tmp_path)
        elif isinstance(pdf_path, str) and os.path.isfile(pdf_path) and pdf_path.lower().endswith(".pdf"):
            result = md.convert(pdf_path)
            markdown_text = result.text_content
        else:
            raise ValueError(f"Invalid pdf_path for markitdown parser: {pdf_path}")

        # Split markdown into pages (markitdown doesn't preserve page boundaries by default)
        # We'll use page separators if present, otherwise treat as single page
        page_separator = "\n\n---\n\n"  # Common markdown page separator
        if page_separator in markdown_text:
            pages = markdown_text.split(page_separator)
        else:
            # If no page separator, treat entire document as one page
            pages = [markdown_text]

        page_list = []
        for page_text in pages:
            token_length = len(enc.encode(page_text))
            page_list.append((page_text, token_length))
        return page_list
    elif pdf_parser == "PyPDF2":
        pdf_reader = PyPDF2.PdfReader(pdf_path)
        page_list = []
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            page_text = page.extract_text()
            token_length = len(enc.encode(page_text))
            page_list.append((page_text, token_length))
        return page_list
    elif pdf_parser == "PyMuPDF":
        if isinstance(pdf_path, BytesIO):
            pdf_stream = pdf_path
            doc = pymupdf.open(stream=pdf_stream, filetype="pdf")
        elif isinstance(pdf_path, str) and os.path.isfile(pdf_path) and pdf_path.lower().endswith(".pdf"):
            doc = pymupdf.open(pdf_path)

        # Debug: save parsed content to temp directory
        temp_dir = "temp_pdf_parse_debug"
        os.makedirs(temp_dir, exist_ok=True)

        page_list = []
        for i, page in enumerate(doc):
            page_text = page.get_text("text")
            token_length = len(enc.encode(page_text))
            page_list.append((page_text, token_length))

            # Save each page to temp file for debugging
            with open(f"{temp_dir}/page_{i+1}.txt", "w", encoding="utf-8") as f:
                f.write(f"=== Page {i+1} ===\n")
                f.write(f"Tokens: {token_length}\n")
                f.write(f"{'='*60}\n\n")
                f.write(page_text)

        doc.close()
        return page_list
    else:
        raise ValueError(f"Unsupported PDF parser: {pdf_parser}")

        

def get_text_of_pdf_pages(pdf_pages, start_page, end_page):
    text = ""
    for page_num in range(start_page-1, end_page):
        text += pdf_pages[page_num][0]
    return text

def get_text_of_pdf_pages_with_labels(pdf_pages, start_page, end_page):
    text = ""
    for page_num in range(start_page-1, end_page):
        text += f"<physical_index_{page_num+1}>\n{pdf_pages[page_num][0]}\n<physical_index_{page_num+1}>\n"
    return text

def get_number_of_pages(pdf_path):
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    num = len(pdf_reader.pages)
    return num



# ============================================================================
# Parent-Child Consistency Validation (Phase 1.4)
# ============================================================================

def validate_parent_child_consistency(structure, logger=None):
    """
    Validate and fix parent-child consistency in hierarchical TOC structure.
    
    Validates:
    1. Parent's physical_index should be <= all children's physical_index
    2. Structure codes are properly nested (e.g., "1.1" is child of "1")
    3. No orphaned children (children without valid parents)
    4. Physical indices are monotonically increasing within same level
    
    Args:
        structure: Flat list of TOC items with structure codes and physical_index
        logger: Optional logger instance
    
    Returns:
        tuple: (validated_structure, validation_report)
    """
    if not structure:
        return structure, {'status': 'empty'}
    
    import logging
    if logger is None:
        logger = logging.getLogger("pageindex.utils")
    
    logger.info("[PARENT_CHILD] Starting parent-child consistency validation")
    
    violations = []
    fixes_applied = 0
    
    # Build parent-child relationship map
    parent_map = {}
    for item in structure:
        struct_code = str(item.get('structure', ''))
        parts = struct_code.split('.')
        if len(parts) > 1:
            parent_code = '.'.join(parts[:-1])
            parent_map[struct_code] = parent_code
    
    # Find parent items by structure code
    struct_to_item = {str(item.get('structure', '')): item for item in structure}
    
    # Step 1: Detect all violations (without fixing yet)
    parent_violations = {}  # Track violations per parent: {parent_code: [child_indices]}
    
    for i, item in enumerate(structure):
        struct_code = str(item.get('structure', ''))
        title = item.get('title', '')[:30]
        phys_idx = item.get('physical_index')
        
        if phys_idx is None:
            continue
        
        # Check if this item has a parent
        if struct_code in parent_map:
            parent_code = parent_map[struct_code]
            parent_item = struct_to_item.get(parent_code)
            
            if parent_item is None:
                # Orphaned child - parent doesn't exist
                violation = {
                    'type': 'orphaned_child',
                    'position': i,
                    'structure': struct_code,
                    'title': title,
                    'parent_structure': parent_code
                }
                violations.append(violation)
                logger.warning(f"[PARENT_CHILD] Orphaned child '{title}' (structure={struct_code}), parent '{parent_code}' not found")
                
            elif parent_item.get('physical_index') is not None:
                parent_idx = parent_item['physical_index']
                parent_title = parent_item.get('title', '')[:30]
                
                # Validate: parent's page should be <= child's page
                if parent_idx > phys_idx:
                    violation = {
                        'type': 'parent_after_child',
                        'position': i,
                        'structure': struct_code,
                        'title': title,
                        'physical_index': phys_idx,
                        'parent_structure': parent_code,
                        'parent_title': parent_title,
                        'parent_index': parent_idx
                    }
                    violations.append(violation)
                    logger.warning(f"[PARENT_CHILD] Parent-child violation: parent '{parent_title}' (page {parent_idx}) comes after child '{title}' (page {phys_idx})")
                    
                    # Track this violation for later fixing
                    if parent_code not in parent_violations:
                        parent_violations[parent_code] = []
                    parent_violations[parent_code].append(phys_idx)
    
    # Step 2: Apply fixes to parents (adjust to minimum child index)
    for parent_code, child_indices in parent_violations.items():
        parent_item = struct_to_item.get(parent_code)
        if parent_item:
            min_child_idx = min(child_indices)
            old_idx = parent_item['physical_index']
            parent_item['physical_index'] = min_child_idx
            # Count each violation as a fix (not just each parent)
            fixes_applied += len(child_indices)
            parent_title = parent_item.get('title', '')[:30]
            logger.info(f"[PARENT_CHILD] Fixed: set parent '{parent_title}' physical_index from {old_idx} to {parent_item['physical_index']} (resolved {len(child_indices)} violations)")
    
    # Step 3: Check and fix non-monotonic ordering at same hierarchy level
    # Build children map first (for fixing strategy)
    children_map = {}  # {parent_code: [child_items]}
    for item in structure:
        struct_code = str(item.get('structure', ''))
        if struct_code in parent_map:
            parent_code = parent_map[struct_code]
            if parent_code not in children_map:
                children_map[parent_code] = []
            children_map[parent_code].append(item)
    
    # Group by hierarchy level
    by_level = {}
    for item in structure:
        struct_code = str(item.get('structure', ''))
        level = len(struct_code.split('.'))
        if level not in by_level:
            by_level[level] = []
        by_level[level].append(item)
    
    # Detect non-monotonic violations and fix them
    for level, items in by_level.items():
        prev_idx = None
        for item in items:
            phys_idx = item.get('physical_index')
            title = item.get('title', '')[:30]
            struct_code = str(item.get('structure', ''))
            
            if phys_idx is not None and prev_idx is not None:
                if phys_idx < prev_idx:
                    violation = {
                        'type': 'non_monotonic_same_level',
                        'level': level,
                        'title': title,
                        'physical_index': phys_idx,
                        'previous_index': prev_idx
                    }
                    violations.append(violation)
                    logger.warning(f"[PARENT_CHILD] Non-monotonic at level {level}: '{title}' (page {phys_idx}) comes before previous item (page {prev_idx})")
                    
                    # Fix strategy: if item has children, adjust to first child's index
                    # Otherwise, adjust to prev_idx + 1
                    children = children_map.get(struct_code, [])
                    if children:
                        child_indices = [c.get('physical_index') for c in children if c.get('physical_index') is not None]
                        if child_indices:
                            new_idx = min(child_indices)
                            item['physical_index'] = new_idx
                            fixes_applied += 1
                            logger.info(f"[PARENT_CHILD] Fixed non-monotonic: set '{title}' physical_index from {phys_idx} to {new_idx} (first child's index)")
                            phys_idx = new_idx
                    else:
                        # No children, just make it sequential
                        new_idx = prev_idx + 1
                        item['physical_index'] = new_idx
                        fixes_applied += 1
                        logger.info(f"[PARENT_CHILD] Fixed non-monotonic: set '{title}' physical_index from {phys_idx} to {new_idx} (prev + 1)")
                        phys_idx = new_idx
            
            if phys_idx is not None:
                prev_idx = phys_idx
    
    # Generate report
    report = {
        'status': 'success' if len(violations) == 0 else 'violations_found',
        'total_items': len(structure),
        'violations_count': len(violations),
        'fixes_applied': fixes_applied,
        'violation_types': {
            'orphaned_child': sum(1 for v in violations if v['type'] == 'orphaned_child'),
            'parent_after_child': sum(1 for v in violations if v['type'] == 'parent_after_child'),
            'non_monotonic_same_level': sum(1 for v in violations if v['type'] == 'non_monotonic_same_level')
        }
    }
    
    if logger:
        logger.info(f"[PARENT_CHILD] Validation complete: {report['violations_count']} violations found, {fixes_applied} fixes applied")
        for vtype, count in report['violation_types'].items():
            if count > 0:
                logger.info(f"[PARENT_CHILD]   - {vtype}: {count}")
    
    return structure, report


def post_processing(structure, end_physical_index):
    """
    Convert TOC structure to tree with proper page ranges.

    Page calculation logic:
    - start_index: Direct from TOC's physical_index (the page where chapter starts)
    - end_index: Next chapter's start page (minus 1 if next chapter appears mid-page)
    - If multiple chapters start on same page, they share that page range
    """
    import logging
    logger = logging.getLogger("pageindex.utils")

    logger.info(f"[PAGE_INDEX] post_processing: {len(structure)} items, document end page: {end_physical_index}")

    for i, item in enumerate(structure):
        title = item.get('title', '')[:50]
        physical_idx = item.get('physical_index')

        # --- Calculate start_index ---
        start_idx = physical_idx

        # Validate and set start_index
        if start_idx is None or not isinstance(start_idx, int) or start_idx < 1:
            # Fallback: use previous item's end_index + 1, or 1 if first item
            if i > 0:
                prev_end = structure[i - 1].get('end_index', end_physical_index)
                start_idx = min(prev_end + 1, end_physical_index)
                logger.info(f"[PAGE_INDEX] Item {i} '{title}': invalid physical_index={physical_idx}, using prev_end+1={start_idx}")
            else:
                start_idx = 1
                logger.info(f"[PAGE_INDEX] Item {i} '{title}': invalid physical_index={physical_idx}, using default=1")
        # Ensure start_index doesn't exceed end_physical_index
        original_start = start_idx
        start_idx = min(start_idx, end_physical_index)
        if start_idx != original_start:
            logger.info(f"[PAGE_INDEX] Item {i} '{title}': start_idx clamped from {original_start} to {start_idx}")

        item['start_index'] = start_idx

        # --- Calculate end_index ---
        if i < len(structure) - 1:
            next_item = structure[i + 1]
            next_start_idx = next_item.get('physical_index')
            next_title = next_item.get('title', '')[:50]

            if next_start_idx is not None and isinstance(next_start_idx, int):
                # Next chapter has a valid start page
                if next_item.get('appear_start') == 'yes':
                    # Next chapter appears mid-page, so current chapter ends before that page
                    end_idx = next_start_idx - 1
                    logger.info(f"[PAGE_INDEX] Item {i} '{title}': next chapter '{next_title}' appears mid-page, end_idx = next_start-1 = {end_idx}")
                else:
                    # Next chapter starts at the beginning of next_start_idx page
                    end_idx = next_start_idx
                    logger.info(f"[PAGE_INDEX] Item {i} '{title}': next chapter '{next_title}' starts at page {next_start_idx}, end_idx = {end_idx}")

                # Ensure end_index >= start_index (chapters with same start page share that page)
                if end_idx < start_idx:
                    logger.info(f"[PAGE_INDEX] Item {i} '{title}': end_idx {end_idx} < start_idx {start_idx}, adjusting to start_idx")
                    end_idx = start_idx

                item['end_index'] = min(end_idx, end_physical_index)
            else:
                # Next item has invalid start page, use document end
                item['end_index'] = max(start_idx, end_physical_index)
                logger.info(f"[PAGE_INDEX] Item {i} '{title}': next chapter has invalid page, extending to document end {end_physical_index}")
        else:
            # Last item, use document end
            item['end_index'] = max(start_idx, end_physical_index)
            logger.info(f"[PAGE_INDEX] Item {i} '{title}': last item, extending to document end {end_physical_index}")

        logger.info(f"[PAGE_INDEX] Item {i} '{title}': FINAL start={item['start_index']}, end={item['end_index']}")

    # Phase 1.4: Validate parent-child consistency before building tree
    structure, validation_report = validate_parent_child_consistency(structure, logger)
    if validation_report['status'] != 'empty':
        logger.info(f"[PAGE_INDEX] Parent-child validation: {validation_report}")

    tree = list_to_tree(structure)
    if len(tree)!=0:
        return tree
    else:
        ### remove appear_start
        for node in structure:
            node.pop('appear_start', None)
            node.pop('physical_index', None)
        return structure

def clean_structure_post(data):
    if isinstance(data, dict):
        data.pop('page_number', None)
        data.pop('start_index', None)
        data.pop('end_index', None)
        if 'nodes' in data:
            clean_structure_post(data['nodes'])
    elif isinstance(data, list):
        for section in data:
            clean_structure_post(section)
    return data

def remove_fields(data, fields=['text']):
    if isinstance(data, dict):
        return {k: remove_fields(v, fields)
            for k, v in data.items() if k not in fields}
    elif isinstance(data, list):
        return [remove_fields(item, fields) for item in data]
    return data

def print_toc(tree, indent=0):
    for node in tree:
        print('  ' * indent + node['title'])
        if node.get('nodes'):
            print_toc(node['nodes'], indent + 1)

def print_json(data, max_len=40, indent=2):
    def simplify_data(obj):
        if isinstance(obj, dict):
            return {k: simplify_data(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [simplify_data(item) for item in obj]
        elif isinstance(obj, str) and len(obj) > max_len:
            return obj[:max_len] + '...'
        else:
            return obj
    
    simplified = simplify_data(data)
    print(json.dumps(simplified, indent=indent, ensure_ascii=False))


def remove_structure_text(data):
    if isinstance(data, dict):
        data.pop('text', None)
        if 'nodes' in data:
            remove_structure_text(data['nodes'])
    elif isinstance(data, list):
        for item in data:
            remove_structure_text(item)
    return data


def check_token_limit(structure, limit=110000):
    list = structure_to_list(structure)
    for node in list:
        num_tokens = count_tokens(node['text'], model='gpt-4o')
        if num_tokens > limit:
            print(f"Node ID: {node['node_id']} has {num_tokens} tokens")
            print("Start Index:", node['start_index'])
            print("End Index:", node['end_index'])
            print("Title:", node['title'])
            print("\n")


def convert_physical_index_to_int(data):
    if isinstance(data, list):
        for i in range(len(data)):
            # Check if item is a dictionary and has 'physical_index' key
            if isinstance(data[i], dict) and 'physical_index' in data[i]:
                physical_index = data[i]['physical_index']
                # Skip if None or already an int
                if physical_index is None or isinstance(physical_index, int):
                    # Additional validation for int values: must be positive
                    if isinstance(physical_index, int) and physical_index <= 0:
                        logging.warning(f"Invalid physical_index (non-positive) for '{data[i].get('title', 'Unknown')}': {physical_index}")
                        data[i]['physical_index'] = None
                    continue
                if isinstance(physical_index, str):
                    try:
                        if physical_index.startswith('<physical_index_'):
                            converted = int(physical_index.split('_')[-1].rstrip('>').strip())
                        elif physical_index.startswith('physical_index_'):
                            converted = int(physical_index.split('_')[-1].strip())
                        else:
                            continue

                        # Validate converted value is positive
                        if converted <= 0:
                            logging.warning(f"Invalid physical_index (non-positive) for '{data[i].get('title', 'Unknown')}': {converted}")
                            data[i]['physical_index'] = None
                        else:
                            data[i]['physical_index'] = converted
                    except (ValueError, IndexError, AttributeError):
                        # If conversion fails, set to None
                        logging.warning(f"Failed to convert physical_index for '{data[i].get('title', 'Unknown')}': {physical_index}")
                        data[i]['physical_index'] = None
    elif isinstance(data, str):
        try:
            if data.startswith('<physical_index_'):
                data = int(data.split('_')[-1].rstrip('>').strip())
            elif data.startswith('physical_index_'):
                data = int(data.split('_')[-1].strip())
            # Check data is int
            if isinstance(data, int):
                return data
            else:
                return None
        except (ValueError, IndexError, AttributeError):
            return None
    return data


def convert_page_to_int(data):
    for item in data:
        if 'page' in item and isinstance(item['page'], str):
            try:
                item['page'] = int(item['page'])
            except ValueError:
                # Keep original value if conversion fails
                pass
    return data


def add_node_text(node, pdf_pages):
    """
    Add text content to nodes.

    Strategy:
    - Leaf nodes (no children): Add truncated content
    - Parent nodes (with children): No content added (will use summary instead)

    This makes the tree structure lightweight - content is only stored
    at the leaf level as a cache. Parent nodes rely on summaries.
    """
    if isinstance(node, dict):
        has_children = 'nodes' in node and node['nodes']

        if not has_children:
            # Leaf node: add content (truncated)
            start_page = node.get('start_index')
            end_page = node.get('end_index')
            full_text = get_text_of_pdf_pages(pdf_pages, start_page, end_page)
            # Truncate to max 500 characters for leaf nodes
            node['text'] = full_text[:500] if len(full_text) > 500 else full_text
        else:
            # Parent node: no content, will use summary instead
            node['text'] = ""

        # Recursively process children
        if 'nodes' in node:
            add_node_text(node['nodes'], pdf_pages)
    elif isinstance(node, list):
        for index in range(len(node)):
            add_node_text(node[index], pdf_pages)
    return


def add_node_text_with_labels(node, pdf_pages):
    if isinstance(node, dict):
        start_page = node.get('start_index')
        end_page = node.get('end_index')
        node['text'] = get_text_of_pdf_pages_with_labels(pdf_pages, start_page, end_page)
        if 'nodes' in node:
            add_node_text_with_labels(node['nodes'], pdf_pages)
    elif isinstance(node, list):
        for index in range(len(node)):
            add_node_text_with_labels(node[index], pdf_pages)
    return


async def generate_node_summary(node, model=None, llm_provider=None):
    """Generate a summary for a node. If llm_provider is provided, use its chat method; otherwise fall back to ChatGPT_API_async."""
    prompt = f"""You are given a part of a document, your task is to generate a description of the partial document about what are main points covered in the partial document.

    Partial Document Text: {node['text']}

    Directly return the description, do not include any other text.
    """
    if llm_provider is not None:
        # Use the API's llm_provider
        response = await llm_provider.chat(prompt, model=model)
    else:
        # Fall back to legacy ChatGPT_API_async
        response = await ChatGPT_API_async(model, prompt)
    return response


async def generate_summaries_for_structure(structure, model=None, llm_provider=None):
    """Generate summaries for all nodes in structure. Uses llm_provider if provided."""
    nodes = structure_to_list(structure)
    tasks = [generate_node_summary(node, model=model, llm_provider=llm_provider) for node in nodes]
    summaries = await asyncio.gather(*tasks)
    
    for node, summary in zip(nodes, summaries):
        node['summary'] = summary
    return structure


def create_clean_structure_for_description(structure):
    """
    Create a clean structure for document description generation,
    excluding unnecessary fields like 'text'.
    """
    if isinstance(structure, dict):
        clean_node = {}
        # Only include essential fields for description
        for key in ['title', 'node_id', 'summary', 'prefix_summary']:
            if key in structure:
                clean_node[key] = structure[key]
        
        # Recursively process child nodes
        if 'nodes' in structure and structure['nodes']:
            clean_node['nodes'] = create_clean_structure_for_description(structure['nodes'])
        
        return clean_node
    elif isinstance(structure, list):
        return [create_clean_structure_for_description(item) for item in structure]
    else:
        return structure


def generate_doc_description(structure, model=None):
    prompt = f"""Your are an expert in generating descriptions for a document.
    You are given a structure of a document. Your task is to generate a one-sentence description for the document, which makes it easy to distinguish the document from other documents.
        
    Document Structure: {structure}
    
    Directly return the description, do not include any other text.
    """
    response = ChatGPT_API(model, prompt)
    return response


def reorder_dict(data, key_order):
    if not key_order:
        return data
    return {key: data[key] for key in key_order if key in data}


def format_structure(structure, order=None):
    if not order:
        return structure
    if isinstance(structure, dict):
        if 'nodes' in structure:
            structure['nodes'] = format_structure(structure['nodes'], order)
        if not structure.get('nodes'):
            structure.pop('nodes', None)
        structure = reorder_dict(structure, order)
    elif isinstance(structure, list):
        structure = [format_structure(item, order) for item in structure]
    return structure


class ConfigLoader:
    def __init__(self, default_path: str = None):
        if default_path is None:
            default_path = Path(__file__).parent / "config.yaml"
        self._default_dict = self._load_yaml(default_path)

    @staticmethod
    def _load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _validate_keys(self, user_dict):
        unknown_keys = set(user_dict) - set(self._default_dict)
        if unknown_keys:
            raise ValueError(f"Unknown config keys: {unknown_keys}")

    def load(self, user_opt=None) -> config:
        """
        Load the configuration, merging user options with default values.
        """
        if user_opt is None:
            user_dict = {}
        elif isinstance(user_opt, config):
            user_dict = vars(user_opt)
        elif isinstance(user_opt, dict):
            user_dict = user_opt
        else:
            raise TypeError("user_opt must be dict, config(SimpleNamespace) or None")

        self._validate_keys(user_dict)
        merged = {**self._default_dict, **user_dict}
        return config(**merged)