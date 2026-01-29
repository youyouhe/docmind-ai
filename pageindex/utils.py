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
        "max_tokens": 8192  # Conservative limit, varies by model
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
    



def list_to_tree(data):
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
        node = {
            'title': item.get('title'),
            'start_index': item.get('start_index'),
            'end_index': item.get('end_index'),
            'nodes': []
        }
        
        nodes[structure] = node
        
        # Find parent
        parent_structure = get_parent_structure(structure)
        
        if parent_structure:
            # Add as child to parent if parent exists
            if parent_structure in nodes:
                nodes[parent_structure]['nodes'].append(node)
            else:
                root_nodes.append(node)
        else:
            # No parent, this is a root node
            root_nodes.append(node)
    
    # Helper function to clean empty children arrays and validate page ranges
    def clean_node(node, parent_start=None, parent_end=None):
        # Validate and clamp child's page range to parent's range
        if parent_start is not None and parent_end is not None:
            # Ensure child's start_index is within parent's range
            if node['start_index'] < parent_start:
                node['start_index'] = parent_start
            if node['start_index'] > parent_end:
                node['start_index'] = parent_end
            # Ensure child's end_index is within parent's range
            if node['end_index'] < parent_start:
                node['end_index'] = parent_start
            if node['end_index'] > parent_end:
                node['end_index'] = parent_end
            # Ensure start_index <= end_index
            if node['start_index'] > node['end_index']:
                node['start_index'] = node['end_index']

        if not node['nodes']:
            del node['nodes']
        else:
            for child in node['nodes']:
                # Pass parent's range to children
                clean_node(child, node['start_index'], node['end_index'])
        return node

    # Clean and return the tree
    return [clean_node(node) for node in root_nodes]

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



def post_processing(structure, end_physical_index):
    # First convert page_number to start_index in flat list
    for i, item in enumerate(structure):
        start_idx = item.get('physical_index')

        # Validate and set start_index
        if start_idx is None or not isinstance(start_idx, int) or start_idx < 1:
            # Fallback: use previous item's end_index + 1, or 1 if first item
            if i > 0:
                prev_end = structure[i - 1].get('end_index', end_physical_index)
                start_idx = min(prev_end + 1, end_physical_index)
            else:
                start_idx = 1
        # Ensure start_index doesn't exceed end_physical_index
        start_idx = min(start_idx, end_physical_index)
        item['start_index'] = start_idx

        if i < len(structure) - 1:
            next_physical_index = structure[i + 1].get('physical_index')
            # Only set end_index if next_physical_index exists and is valid
            if next_physical_index is not None and isinstance(next_physical_index, int):
                if structure[i + 1].get('appear_start') == 'yes':
                    end_idx = next_physical_index - 1
                else:
                    end_idx = next_physical_index
                # Ensure end_index is at least start_index
                end_idx = max(end_idx, start_idx)
                item['end_index'] = min(end_idx, end_physical_index)
            else:
                # Fallback to end_physical_index if next physical_index is invalid
                item['end_index'] = max(start_idx, end_physical_index)
        else:
            item['end_index'] = max(start_idx, end_physical_index)
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
            # Truncate to max 5000 characters for leaf nodes
            node['text'] = full_text[:5000] if len(full_text) > 5000 else full_text
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