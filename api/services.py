"""
Business logic layer for PageIndex API.

This module provides:
- LLM provider abstraction (gemini, deepseek, openrouter)
- Tree search service using LLM reasoning
- Document parsing service (PDF and Markdown)
"""

import asyncio
import json
import os
import tempfile
import logging
import random
import time
from typing import Optional, List, Dict, Any, Literal, Callable
from pathlib import Path

import aiofiles
from openai import AsyncOpenAI

# Configure logging
logger = logging.getLogger("pageindex.api.services")


# =============================================================================
# LLM Provider Factory
# =============================================================================

class LLMProvider:
    """
    Support multiple LLM providers: gemini, deepseek, openrouter.

    All providers use OpenAI-compatible API except Gemini.
    """

    SUPPORTED_PROVIDERS = ["deepseek", "gemini", "openrouter", "openai", "zhipu"]

    def __init__(self, provider: str, api_key: Optional[str] = None, model: Optional[str] = None, 
                 log_callback: Optional[Callable] = None):
        """
        Initialize LLM provider.

        Args:
            provider: Provider name (deepseek, gemini, openrouter, openai, zhipu)
            api_key: API key (if None, reads from environment)
            model: Model name (if None, uses default for provider)
            log_callback: Optional callback function for logging LLM calls
                         Signature: log_callback(operation_type: str, prompt: str, response: str, 
                                                model: str, duration_ms: int, success: bool, 
                                                error_msg: Optional[str], metadata: Optional[dict])
        """
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}. Use one of: {self.SUPPORTED_PROVIDERS}")

        self.provider = provider
        self.api_key = api_key or self._get_api_key_from_env(provider)
        self.model = model or self._get_default_model(provider)
        self.log_callback = log_callback

        # Initialize OpenAI client (for compatible APIs)
        if provider != "gemini":
            base_url = self._get_base_url(provider)
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=base_url,
            )

    def _get_api_key_from_env(self, provider: str) -> str:
        """Get API key from environment variable."""
        key_map = {
            "deepseek": "DEEPSEEK_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
        }
        env_key = key_map.get(provider, f"{provider.upper()}_API_KEY")
        key = os.getenv(env_key)
        if not key:
            raise ValueError(f"API key not found. Set {env_key} environment variable.")
        return key

    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider."""
        model_map = {
            "deepseek": "deepseek-reasoner",
            "gemini": "gemini-1.5-flash",
            "openrouter": "deepseek/deepseek-chat",
            "openai": "gpt-4o-mini",
            "zhipu": "glm-4.7",
        }
        return model_map.get(provider, "default")

    def _get_base_url(self, provider: str) -> Optional[str]:
        """Get base URL for OpenAI-compatible APIs."""
        url_map = {
            "deepseek": "https://api.deepseek.com/v1",  # Use /v1 for OpenAI compatibility
            "openrouter": "https://openrouter.ai/api/v1",
            "zhipu": "https://open.bigmodel.cn/api/coding/paas/v4",
            "openai": None,  # Default OpenAI URL
        }
        return url_map.get(provider)

    async def chat(self, prompt: str, model: Optional[str] = None, max_retries: int = 3,
                   operation_type: str = "chat", metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Send chat request to LLM with automatic retry on failure.

        Args:
            prompt: The prompt to send
            model: Override model name
            max_retries: Maximum number of retry attempts
            operation_type: Type of operation for logging (e.g., 'toc_extraction', 'node_summary')
            metadata: Additional metadata for logging

        Returns:
            LLM response text

        Raises:
            Exception: If all retries are exhausted
        """
        model = model or self.model
        last_error = None
        start_time = time.time()

        for attempt in range(max_retries):
            try:
                if self.provider == "gemini":
                    response = await self._chat_gemini(prompt, model)
                else:
                    response = await self._chat_openai_compat(prompt, model)
                
                # Log successful call if callback is set
                if self.log_callback:
                    duration_ms = int((time.time() - start_time) * 1000)
                    self.log_callback(
                        operation_type=operation_type,
                        prompt=prompt,
                        response=response,
                        model=model,
                        duration_ms=duration_ms,
                        success=True,
                        error_msg=None,
                        metadata=metadata
                    )
                
                return response

            except Exception as e:
                last_error = e
                # Don't retry on certain errors
                error_msg = str(e).lower()
                if any(x in error_msg for x in [
                    "authentication", "unauthorized", "invalid_api_key",
                    "permission", "quota", "limit", "401", "403", "429"
                ]):
                    logger.error(f"Non-retryable error in LLM chat: {e}")
                    # Log the failed call
                    if self.log_callback:
                        duration_ms = int((time.time() - start_time) * 1000)
                        self.log_callback(
                            operation_type=operation_type,
                            prompt=prompt,
                            response=None,
                            model=model,
                            duration_ms=duration_ms,
                            success=False,
                            error_msg=str(e),
                            metadata=metadata
                        )
                    raise

                if attempt < max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s...
                    wait_time = (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(f"LLM chat failed (attempt {attempt + 1}/{max_retries}), "
                                    f"retrying in {wait_time:.1f}s. Error: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"LLM chat failed after {max_retries} attempts. Last error: {e}")
                    # Log the final failed call
                    if self.log_callback:
                        duration_ms = int((time.time() - start_time) * 1000)
                        self.log_callback(
                            operation_type=operation_type,
                            prompt=prompt,
                            response=None,
                            model=model,
                            duration_ms=duration_ms,
                            success=False,
                            error_msg=str(e),
                            metadata=metadata
                        )

        # All retries exhausted
        raise Exception(f"LLM chat failed after {max_retries} attempts. Last error: {last_error}")

    async def _chat_openai_compat(self, prompt: str, model: str) -> str:
        """Chat using OpenAI-compatible API."""
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content

    async def _chat_gemini(self, prompt: str, model: str) -> str:
        """Chat using Google Gemini API."""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("Install google-generativeai: pip install google-generativeai")

        genai.configure(api_key=self.api_key)
        client = genai.GenerativeModel(model)

        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.generate_content(prompt)
        )
        return response.text


# =============================================================================
# Tree Search Service
# =============================================================================

class TreeSearchService:
    """
    Tree search using LLM reasoning.
    Finds relevant nodes in a document tree based on user questions.
    """

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize tree search service.

        Args:
            llm_provider: Configured LLM provider
        """
        self.llm = llm_provider

    def _flatten_tree_for_search(self, tree: dict) -> List[dict]:
        """
        Flatten tree structure for LLM search.
        Only includes id, title, and summary for brevity.
        """
        result = []

        def traverse(node: dict, level: int = 0):
            node_info = {
                "id": node.get("id", ""),
                "title": node.get("title", ""),
                "level": level
            }
            # Include summary if available
            if summary := node.get("summary"):
                node_info["summary"] = summary

            result.append(node_info)

            # Recursively process children
            for child in node.get("children", []):
                traverse(child, level + 1)

        traverse(tree)
        return result

    async def search_nodes(
        self,
        question: str,
        tree: dict,
        max_nodes: int = 8,
        is_list_question: bool = False
    ) -> Dict[str, Any]:
        """
        Search for relevant nodes based on question.

        Args:
            question: User's question
            tree: Document tree structure
            max_nodes: Maximum number of nodes to return
            is_list_question: Whether this is a list/enumeration question

        Returns:
            Dictionary with thinking, node_ids, and path information
        """
        # Flatten tree for search
        flat_tree = self._flatten_tree_for_search(tree)

        # Build LLM prompt with list question awareness
        if is_list_question:
            prompt = f"""You are a document search assistant. Your task is to find ALL relevant sections in a document tree based on a user's question.

User Question: {question}

Document Tree Structure:
{json.dumps(flat_tree, ensure_ascii=False, indent=2)}

IMPORTANT: This is a LIST question. The user wants a COMPLETE enumeration.
Instructions:
1. Analyze the question and understand what complete list is being requested
2. Examine the document tree structure (titles and summaries)
3. Select ALL nodes that are relevant to the question (up to {max_nodes} nodes)
4. Do NOT truncate - include all matching items for a complete list
5. Return your reasoning and the selected node IDs

Response Format (JSON):
{{
    "thinking": "Your thought process explaining why you selected these nodes",
    "node_ids": ["id1", "id2", ...]
}}

Respond only with valid JSON, no additional text."""
        else:
            prompt = f"""You are a document search assistant. Your task is to find the most relevant sections in a document tree based on a user's question.

User Question: {question}

Document Tree Structure:
{json.dumps(flat_tree, ensure_ascii=False, indent=2)}

Instructions:
1. Analyze the question and understand what information is being sought
2. Examine the document tree structure (titles and summaries)
3. Select the most relevant node IDs (maximum {max_nodes})
4. Return your reasoning and the selected node IDs

Response Format (JSON):
{{
    "thinking": "Your thought process explaining why you selected these nodes",
    "node_ids": ["id1", "id2", ...]
}}

Respond only with valid JSON, no additional text."""

        # Call LLM
        response = await self.llm.chat(prompt)

        # Parse response
        return self._parse_search_response(response, tree)

    def _parse_search_response(self, response: str, tree: dict) -> Dict[str, Any]:
        """
        Parse LLM search response and extract node paths.

        Args:
            response: LLM JSON response
            tree: Original tree for path extraction

        Returns:
            Parsed search results with paths
        """
        try:
            # Extract JSON from response (handle markdown code blocks)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            data = json.loads(response.strip())
            node_ids = data.get("node_ids", [])
            thinking = data.get("thinking", "")

            # Build path information
            paths = []
            for node_id in node_ids:
                path = self._find_path_to_node(tree, node_id)
                if path:
                    paths.append(path)

            return {
                "thinking": thinking,
                "node_ids": node_ids,
                "paths": paths
            }

        except json.JSONDecodeError as e:
            return {
                "thinking": f"Failed to parse LLM response: {e}",
                "node_ids": [],
                "paths": [],
                "error": str(e)
            }

    def _find_path_to_node(self, tree: dict, target_id: str, current_path: Optional[List[str]] = None) -> Optional[List[str]]:
        """
        Find path to a node by ID.

        Args:
            tree: Tree structure
            target_id: Target node ID
            current_path: Current path during recursion

        Returns:
            List of node IDs from root to target, or None if not found
        """
        if current_path is None:
            current_path = []

        node_id = tree.get("id", "")

        # Check if this is the target
        if node_id == target_id:
            return current_path + [node_id]

        # Search in children
        for child in tree.get("children", []):
            result = self._find_path_to_node(child, target_id, current_path + [node_id])
            if result:
                return result

        return None


# =============================================================================
# Document Parse Service
# =============================================================================

class ParseService:
    """
    Document parsing service for PDF and Markdown files.
    """

    # Class variable to store performance data from last PDF parse
    _last_pdf_performance = {}

    @staticmethod
    def get_last_pdf_performance() -> dict:
        """Get performance data from the last PDF parse."""
        return ParseService._last_pdf_performance.copy()

    @staticmethod
    def clear_last_pdf_performance() -> None:
        """Clear stored PDF performance data."""
        ParseService._last_pdf_performance = {}

    @staticmethod
    def _calculate_level(tree: dict, current_level: int = 0) -> int:
        """Calculate maximum depth of tree."""
        max_depth = current_level
        for child in tree.get("children", []):
            child_depth = ParseService._calculate_level(child, current_level + 1)
            max_depth = max(max_depth, child_depth)
        return max_depth

    @staticmethod
    def _count_total_characters(tree: dict) -> int:
        """Count total characters in tree summary."""
        count = 0
        if summary := tree.get("summary"):
            count += len(summary)
        for child in tree.get("children", []):
            count += ParseService._count_total_characters(child)
        return count

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation (approximately 4 chars per token)."""
        return len(text) // 4

    @staticmethod
    def _check_has_summaries(tree: dict) -> bool:
        """Check if any node has a summary."""
        if tree.get("summary"):
            return True
        for child in tree.get("children", []):
            if ParseService._check_has_summaries(child):
                return True
        return False

    @staticmethod
    def _check_has_content(tree: dict) -> bool:
        """Check if any node has content (summary serves as content now)."""
        if tree.get("summary"):
            return True
        for child in tree.get("children", []):
            if ParseService._check_has_content(child):
                return True
        return False

    @staticmethod
    def _count_nodes(tree: dict) -> int:
        """Count total nodes in tree."""
        count = 1
        for child in tree.get("children", []):
            count += ParseService._count_nodes(child)
        return count

    @staticmethod
    def convert_page_index_to_api_format(page_index_tree: dict, doc_title: str = None) -> dict:
        """
        Convert PageIndex internal format to API format (optimized for size).

        PageIndex format -> API format:
        - title -> title
        - node_id -> id
        - summary -> summary
        - nodes -> children
        - start_index -> ps (PDF only, page start)
        - end_index -> pe (PDF only, page end)
        - line_num -> line_start (Markdown only)

        Removed fields (size optimization):
        - level (implicit from tree nesting)
        - content (use summary instead)
        - display_title (use title directly)
        - is_noise (not used by frontend)
        """
        def convert_node(node: dict) -> dict:
            api_node = {
                "id": node.get("node_id", ""),
                "title": node.get("title", ""),
                "children": []
            }

            # Summary only (content excluded for size optimization)
            # Skip empty summaries to save space
            if node.get("summary"):
                api_node["summary"] = node["summary"]

            # PDF-specific fields (abbreviated keys)
            # Note: PageIndex already uses 1-based indexing, so no conversion needed
            if "start_index" in node:
                api_node["ps"] = node["start_index"]
            if "end_index" in node:
                api_node["pe"] = node["end_index"]

            # Markdown-specific fields
            if "line_num" in node:
                api_node["line_start"] = node["line_num"]

            # Recursively convert children
            for child in node.get("nodes", []):
                api_node["children"].append(convert_node(child))

            return api_node

        # Determine root title: prefer explicit doc_title, fallback to doc_name
        root_title = doc_title or page_index_tree.get("doc_name", "Document")

        # PageIndex output wraps in "structure" array
        # For documents with TOC, there may be multiple root-level sections
        # We'll create a virtual root node
        structure = page_index_tree.get("structure", [])

        if len(structure) == 0:
            # Empty document
            return {
                "id": "root",
                "title": root_title,
                "children": []
            }

        if len(structure) == 1:
            # Single root section - use root_title as its title
            result = convert_node(structure[0])
            result["title"] = root_title
            return result
        else:
            # Multiple root sections - create virtual root
            return {
                "id": "root",
                "title": root_title,
                "children": [convert_node(s) for s in structure]
            }

    @staticmethod
    def convert_api_to_page_index_format(api_tree: dict) -> dict:
        """
        Convert API format to PageIndex internal format.
        
        API format -> PageIndex format:
        - id -> node_id
        - title -> title
        - summary -> summary
        - children -> nodes
        - ps -> start_index (PDF only)
        - pe -> end_index (PDF only)
        - line_start -> line_num (Markdown only)
        """
        def convert_node(node: dict) -> dict:
            page_index_node = {
                "node_id": node.get("id", ""),
                "title": node.get("title", ""),
                "nodes": []
            }

            # Optional fields
            if "summary" in node:
                page_index_node["summary"] = node["summary"]

            # PDF-specific fields (support both abbreviated and legacy keys)
            ps = node.get("ps") or node.get("page_start")
            pe = node.get("pe") or node.get("page_end")
            if ps is not None:
                page_index_node["start_index"] = ps
            if pe is not None:
                page_index_node["end_index"] = pe

            # Markdown-specific fields
            if "line_start" in node:
                page_index_node["line_num"] = node["line_start"]
            
            # Recursively convert children
            for child in node.get("children", []):
                page_index_node["nodes"].append(convert_node(child))
            
            return page_index_node
        
        # Convert to PageIndex structure format
        if isinstance(api_tree, list):
            # Multiple root nodes
            return {
                "doc_name": "Document",
                "structure": [convert_node(node) for node in api_tree]
            }
        else:
            # Single root node or virtual root
            if api_tree.get("id") == "root" and api_tree.get("children"):
                # Virtual root - extract children as structure
                return {
                    "doc_name": api_tree.get("title", "Document"),
                    "structure": [convert_node(child) for child in api_tree["children"]]
                }
            else:
                # Single real root
                return {
                    "doc_name": api_tree.get("title", "Document"),
                    "structure": [convert_node(api_tree)]
                }

    @staticmethod
    def calculate_tree_stats(tree: dict) -> dict:
        """
        Calculate statistics for a tree.

        Returns:
            Dictionary with tree statistics
        """
        total_nodes = ParseService._count_nodes(tree)
        max_depth = ParseService._calculate_level(tree)
        total_characters = ParseService._count_total_characters(tree)
        total_tokens = ParseService._estimate_tokens(str(tree))
        has_summaries = ParseService._check_has_summaries(tree)
        has_content = ParseService._check_has_content(tree)

        return {
            "total_nodes": total_nodes,
            "max_depth": max_depth,
            "total_characters": total_characters,
            "total_tokens": total_tokens,
            "has_summaries": has_summaries,
            "has_content": has_content
        }

    @staticmethod
    async def parse_markdown(
        file_path: str,
        model: Optional[str] = None,
        if_add_node_summary: bool = True,
        if_add_node_text: bool = True,
        llm_provider: Optional["LLMProvider"] = None,
        max_concurrent: int = 10
    ) -> dict:
        """
        Parse Markdown file to tree structure.

        Args:
            file_path: Path to Markdown file
            model: LLM model to use (default: uses llm_provider.model if not specified)
            if_add_node_summary: Whether to add node summaries
            if_add_node_text: Whether to add full text content
            llm_provider: LLM provider instance for API calls
            max_concurrent: Maximum concurrent LLM calls for summary generation

        Returns:
            PageIndex format tree structure
        """
        from pageindex.page_index_md import md_to_tree

        # Use provider's configured model if not specified
        if model is None and llm_provider is not None:
            model = llm_provider.model

        result = await md_to_tree(
            md_path=file_path,
            model=model,
            if_add_node_summary="yes" if if_add_node_summary else "no",
            if_add_node_text="yes" if if_add_node_text else "no",
            llm_provider=llm_provider,
            max_concurrent=max_concurrent
        )

        return result

    @staticmethod
    async def parse_pdf(
        file_path: str,
        model: Optional[str] = None,
        toc_check_pages: int = 20,
        max_pages_per_node: int = 10,
        max_tokens_per_node: int = 20000,
        if_add_node_summary: bool = True,
        if_add_node_id: bool = True,
        if_add_node_text: bool = False,
        llm_provider: Optional["LLMProvider"] = None,
        custom_prompt: Optional[str] = None,
        progress_callback: Optional[Any] = None
    ) -> dict:
        """
        Parse PDF file to tree structure.

        Args:
            file_path: Path to PDF file
            model: LLM model to use (default: uses llm_provider.model if not specified)
            toc_check_pages: Number of pages to check for TOC
            max_pages_per_node: Maximum pages per node
            max_tokens_per_node: Maximum tokens per node
            if_add_node_summary: Whether to add node summaries
            if_add_node_id: Whether to add node IDs
            if_add_node_text: Whether to add full text content
            llm_provider: LLM provider instance (for future use with PDF parsing)
            custom_prompt: Custom prompt for TOC extraction
            progress_callback: ProgressCallback instance for real-time updates

        Returns:
            PageIndex format tree structure
        """
        from pageindex_v2 import page_index_main
        from pageindex_v2 import ConfigLoader
        from pageindex.progress_callback import register_callback

        # Use provider's configured model if not specified
        if model is None and llm_provider is not None:
            model = llm_provider.model

        # Build options dict
        user_opt = {
            "model": model,
            "toc_check_page_num": toc_check_pages,
            "max_page_num_each_node": max_pages_per_node,
            "max_token_num_each_node": max_tokens_per_node,
            "if_add_node_id": "yes" if if_add_node_id else "no",
            "if_add_node_summary": "yes" if if_add_node_summary else "no",
            "if_add_node_text": "yes" if if_add_node_text else "no",
            "if_add_doc_description": "no",
        }

        # Add custom_prompt if provided
        if custom_prompt:
            user_opt["custom_prompt"] = custom_prompt

        # Load config using ConfigLoader
        opt = ConfigLoader().load(user_opt)

        # Register progress callback if provided
        document_id = None
        if progress_callback is not None:
            document_id = getattr(progress_callback, 'document_id', None)
            if document_id:
                register_callback(document_id, progress_callback)

        # Create a wrapper that processes updates periodically during parsing
        async def parse_with_updates():
            # Run the synchronous page_index_main in a thread to avoid event loop conflicts
            # page_index_main uses asyncio.run() internally which conflicts with FastAPI
            import asyncio
            loop = asyncio.get_event_loop()

            # Start a background task to process progress updates
            async def process_updates():
                while progress_callback is not None:
                    await progress_callback.process_updates()
                    await asyncio.sleep(0.2)  # Process updates every 200ms
                    # Check if parsing is done by checking if callback is disabled
                    if not progress_callback.is_enabled():
                        break

            update_task = None
            if progress_callback is not None and document_id:
                update_task = asyncio.create_task(process_updates())

            try:
                parsed_data = await loop.run_in_executor(
                    None,
                    lambda: page_index_main(file_path, opt=opt)
                )
            finally:
                if update_task:
                    update_task.cancel()
                    try:
                        await update_task
                    except asyncio.CancelledError:
                        pass

            return parsed_data

        parsed_data = await parse_with_updates()

        # Unregister callback and process final updates
        if document_id:
            from pageindex.progress_callback import unregister_callback
            if progress_callback:
                await progress_callback.process_updates()
                progress_callback.disable()
            unregister_callback(document_id)

        # Extract result and performance data
        # page_index_main now returns {"result": ..., "performance": ...}
        if isinstance(parsed_data, dict) and "result" in parsed_data:
            result = parsed_data["result"]
            # Store performance data for later retrieval
            ParseService._last_pdf_performance = parsed_data.get("performance", {})
        else:
            # Backward compatibility for old return format
            result = parsed_data
            ParseService._last_pdf_performance = {}

        return result


# =============================================================================
# Chat Service
# =============================================================================

class ChatService:
    """
    Chat/Q&A service using tree search and LLM generation.
    """

    def __init__(self, llm_provider: LLMProvider, pdf_file_path: Optional[str] = None, storage_service: Optional["StorageService"] = None):
        """
        Initialize chat service.

        Args:
            llm_provider: Configured LLM provider
            pdf_file_path: Path to the PDF file (for dynamic page content loading)
            storage_service: Storage service instance
        """
        self.llm = llm_provider
        self.search_service = TreeSearchService(llm_provider)
        self.pdf_file_path = pdf_file_path
        self.storage_service = storage_service
        self.pdf_paths: Dict[str, str] = {}  # document_id -> pdf_path mapping

    def set_pdf_paths(self, pdf_paths: Dict[str, str]):
        """Set multiple PDF paths for document set support."""
        self.pdf_paths = pdf_paths
        if pdf_paths:
            self.pdf_file_path = list(pdf_paths.values())[0]  # Keep first as fallback

    def _get_node_by_id(self, tree: dict, node_id: str) -> Optional[dict]:
        """Find a node by its ID."""
        if tree.get("id") == node_id:
            return tree
        for child in tree.get("children", []):
            result = self._get_node_by_id(child, node_id)
            if result:
                return result
        return None

    def _get_pdf_for_node(self, node: dict) -> Optional[str]:
        """Get the PDF path for a node based on its document prefix."""
        # Check if node has document_id attribute
        node_doc_id = node.get("document_id")
        if node_doc_id and node_doc_id in self.pdf_paths:
            return self.pdf_paths[node_doc_id]
        
        # Check parent document from node ID (e.g., "doc-xxx-nodeid")
        node_id = node.get("id", "")
        if node_id.startswith("doc-"):
            parts = node_id.split("-")
            if len(parts) >= 2:
                doc_id = parts[1]
                if doc_id in self.pdf_paths:
                    return self.pdf_paths[doc_id]
        
        # Fallback to first PDF
        return self.pdf_file_path

    def _build_context_from_nodes(self, tree: dict, node_ids: List[str]) -> str:
        """
        Build context string from relevant nodes.

        Strategy:
        - If pdf_paths available: Load actual page content dynamically from correct PDF
        - Otherwise: Use summary as fallback
        """
        context_parts = []

        for node_id in node_ids:
            node = self._get_node_by_id(tree, node_id)
            if node:
                title = node.get("title", "")

                # Try to load actual page content if PDF is available
                pdf_path = self._get_pdf_for_node(node)
                if pdf_path and self.storage_service:
                    # Support both abbreviated (ps/pe) and legacy (page_start/page_end) keys
                    page_start = node.get("ps") or node.get("page_start")
                    page_end = node.get("pe") or node.get("page_end")
                    if page_start and page_end:
                        try:
                            pages = self.storage_service.get_pdf_pages(
                                pdf_path, page_start, page_end
                            )
                            content = "\n\n".join([p[1] for p in pages])
                            context_parts.append(f"# {title}\n\n{content}")
                            continue
                        except Exception as e:
                            logger.warning(f"Failed to load pages for {title}: {e}")

                # Fallback to summary
                content = node.get("summary", "")
                context_parts.append(f"# {title}\n\n{content}")

        return "\n\n---\n\n".join(context_parts)

    def _is_list_question(self, question: str) -> bool:
        """
        Detect if the question is asking for a list/complete enumeration.

        List questions typically contain keywords like:
        - 列出, 列表, 所有, 全部, 多少, 有哪些
        - list, all, every, what are, how many
        """
        list_keywords = [
            "列出", "列表", "采购清单", "所有", "全部", "都有哪些", "有哪些",
            "多少", "几个", "几项", "包含", "包括",
            "list", "all", "every", "what are", "how many", "enumerate"
        ]
        question_lower = question.lower()
        return any(keyword in question or keyword.lower() in question_lower for keyword in list_keywords)

    # Tool intent detection patterns
    TOOL_PATTERNS = {
        "extract_dates": ["有效时间", "关键日期", "提取日期", "截止日期", "投标时间", "有效期", "时间信息", "日期信息"],
        "extract_budget": ["预算", "价格", "报价", "费用", "成本", "总价", "金额", "采购金额", "预算价", "控制价", "标底"],
        "add_to_timeline": ["添加到时间线", "添加该项目到", "加入时间线", "项目管理时间线", "添加到项目管理", "加入项目管理"],
    }

    def _detect_tool_intent(self, question: str) -> Optional[str]:
        """Detect if the user question implies a tool call."""
        for tool_name, patterns in self.TOOL_PATTERNS.items():
            if any(p in question for p in patterns):
                return tool_name
        return None

    def _build_date_extraction_prompt(self, question: str, context: str, history_text: str) -> str:
        """Build a prompt for extracting key dates from document content."""
        history_section = f"\n对话历史：\n{history_text}\n" if history_text else ""

        return f"""你是一个文档分析助手。请从以下文档内容中提取所有关键日期信息。

文档内容：
{context}
{history_section}
用户问题：{question}

请按以下格式回答，首先用自然语言总结关键日期，然后在最后附上一个JSON代码块：

[用自然语言总结所有发现的关键日期...]

```json
{{
  "project_name": "项目名称",
  "start_date": "YYYY-MM-DD 或 null",
  "end_date": "YYYY-MM-DD 或 null",
  "milestones": [
    {{"name": "里程碑名称", "date": "YYYY-MM-DD", "type": "类型"}}
  ],
  "budget": 数字或null,
  "budget_unit": "万元"
}}
```

注意：
1. 日期格式统一为YYYY-MM-DD
2. 如果文档中没有明确的日期，使用null
3. milestones 应尽可能列出文档中所有可识别的时间节点，type 从以下招投标全流程类型中选取：
   - publish: 公告发布
   - doc_deadline: 招标文件获取截止
   - qa_deadline: 答疑截止
   - bid_deadline: 投标截止
   - opening: 开标
   - evaluation: 评标
   - award_notice: 中标公示
   - contract_sign: 合同签订
   - delivery: 交货
   - acceptance: 验收
   - warranty_start: 质保开始
   - warranty_end: 质保结束
   - payment: 付款
   - custom: 其他自定义
4. project_name 应从文档中提取项目名称
5. start_date 一般为公告发布日期或项目开始日期
6. end_date 一般为合同结束日期或项目有效期截止日期
7. budget 为预算金额数字（不带单位），budget_unit 为金额单位，尽量统一为万元
8. 即使只有一个日期也要尽量归类到正确的 milestone type"""

    def _build_budget_extraction_prompt(self, question: str, context: str, history_text: str) -> str:
        """Build a prompt for extracting budget/price info from document content."""
        history_section = f"\n对话历史：\n{history_text}\n" if history_text else ""

        return f"""你是一个文档分析助手。请从以下文档内容中提取预算、价格或成本相关的信息。

文档内容：
{context}
{history_section}
用户问题：{question}

请按以下格式回答，首先用自然语言总结价格信息，然后在最后附上一个JSON代码块：

[用自然语言总结所有发现的价格/预算信息...]

```json
{{
  "budget": 数字或null,
  "budget_unit": "万元 或 元 或其他单位",
  "budget_details": "预算详情描述"
}}
```

注意：
1. budget 为数字，不要带单位
2. 如果文档中有多个价格，取预算总价或采购控制价
3. 尽量将金额统一转换为万元（如 500万元 → budget: 500, budget_unit: "万元"）
4. 如果金额以"元"为单位且大于10000，转换为万元
5. 如果文档中没有明确的价格信息，budget 使用 null"""

    async def _handle_extract_budget(
        self, question: str, tree: dict, history: List[dict],
        context: str, sources: list, debug_path: list,
        document_id: Optional[str] = None,
    ) -> dict:
        """Handle budget extraction and auto-update timeline if entry exists."""
        import re
        from api.database import get_db

        history_text = self._build_history_text(history)
        prompt = self._build_budget_extraction_prompt(question, context, history_text)
        answer = await self.llm.chat(prompt)

        # Try to parse budget JSON from the answer
        budget_json = None
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', answer, re.DOTALL)
        if json_match:
            try:
                budget_json = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        tool_call_result = {"name": "extract_budget", "status": "completed"}

        # Auto-update timeline if entry exists for this document
        if budget_json and budget_json.get("budget") is not None:
            document_id = document_id or tree.get("id", "")
            db = get_db()
            existing_entries = db.get_timeline_entries(document_id)

            if existing_entries:
                # Update the first matching entry with budget info
                entry = existing_entries[0]
                updated = db.update_timeline_entry(
                    entry["id"],
                    budget=budget_json["budget"],
                    budget_unit=budget_json.get("budget_unit", "万元"),
                )
                if updated:
                    budget_val = budget_json["budget"]
                    budget_unit = budget_json.get("budget_unit", "万元")
                    answer += f"\n\n---\n已自动更新项目时间线中的预算信息：**{budget_val} {budget_unit}**"
                    tool_call_result = {
                        "name": "update_timeline_budget",
                        "status": "completed",
                        "result": updated,
                    }

        return {
            "answer": answer,
            "sources": sources,
            "debug_path": debug_path,
            "provider": self.llm.provider,
            "model": self.llm.model,
            "system_prompt": prompt,
            "raw_output": answer,
            "tool_call": tool_call_result,
        }

    async def _handle_add_to_timeline(
        self, question: str, tree: dict, history: List[dict],
        context: str, sources: list, debug_path: list,
        document_id: Optional[str] = None,
    ) -> dict:
        """Handle 'add to timeline' tool call by parsing previous date extraction."""
        import re
        import uuid as uuid_module
        from api.database import get_db

        # Look for JSON block in recent history
        date_json = None
        for msg in reversed(history or []):
            if msg.get("role") == "assistant":
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', msg["content"], re.DOTALL)
                if json_match:
                    try:
                        date_json = json.loads(json_match.group(1))
                        break
                    except json.JSONDecodeError:
                        continue

        if not date_json:
            # No previous extraction found, extract now
            history_text = self._build_history_text(history)
            extraction_prompt = self._build_date_extraction_prompt(question, context, history_text)
            extraction_result = await self.llm.chat(extraction_prompt)
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', extraction_result, re.DOTALL)
            if json_match:
                try:
                    date_json = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

        if not date_json:
            return {
                "answer": '抱歉，我无法从文档中提取到日期信息。请先让我分析文档的关键日期，例如问我"这个文档的有效时间是什么？"',
                "sources": sources,
                "debug_path": debug_path,
                "provider": self.llm.provider,
                "model": self.llm.model,
                "system_prompt": "",
                "raw_output": "",
            }

        # Use actual document_id, fall back to tree root id
        document_id = document_id or tree.get("id", "")

        # Create the timeline entry
        db = get_db()
        entry_id = str(uuid_module.uuid4())
        budget_val = date_json.get("budget")
        budget_unit = date_json.get("budget_unit", "万元")
        # Convert budget to float if it's a string
        if isinstance(budget_val, str):
            try:
                budget_val = float(budget_val)
            except (ValueError, TypeError):
                budget_val = None

        entry = db.create_timeline_entry(
            entry_id=entry_id,
            document_id=document_id,
            project_name=date_json.get("project_name", tree.get("title", "未命名项目")),
            start_date=date_json.get("start_date"),
            end_date=date_json.get("end_date"),
            milestones=date_json.get("milestones", []),
            budget=budget_val,
            budget_unit=budget_unit if budget_val is not None else None,
            notes=question,
        )

        # Build confirmation message
        milestones_text = ""
        for m in date_json.get("milestones", []):
            milestones_text += f"\n- {m.get('name', '')}: {m.get('date', '')}"

        budget_text = f"\n**预算**: {budget_val} {budget_unit}" if budget_val is not None else ""

        answer = f"""已成功将该项目添加到时间线！

**项目名称**: {entry.get('project_name')}
**有效期**: {entry.get('start_date') or '未指定'} ~ {entry.get('end_date') or '未指定'}{budget_text}
**关键里程碑**:{milestones_text if milestones_text else ' 无'}

你可以在文档列表的"项目时间线"标签页查看所有项目的时间线。"""

        return {
            "answer": answer,
            "sources": sources,
            "debug_path": debug_path,
            "provider": self.llm.provider,
            "model": self.llm.model,
            "system_prompt": "",
            "raw_output": answer,
            "tool_call": {
                "name": "add_to_timeline",
                "status": "completed",
                "result": entry,
            },
        }

    async def answer_question(
        self,
        question: str,
        tree: dict,
        history: Optional[List[dict]] = None,
        max_source_nodes: int = 8,
        document_id: Optional[str] = None,
    ) -> dict:
        """
        Answer a question based on document tree.

        Args:
            question: User's question
            tree: Document tree structure
            history: Conversation history (list of {role, content} dicts)
            max_source_nodes: Maximum number of source nodes to use

        Returns:
            Dictionary with answer, sources, and debug info
        """
        history = history or []

        # Detect tool intent before normal flow
        tool_intent = self._detect_tool_intent(question)

        # Detect if this is a list question
        is_list_question = self._is_list_question(question)

        # Search for relevant nodes (with list question awareness)
        search_result = await self.search_service.search_nodes(
            question=question,
            tree=tree,
            max_nodes=max_source_nodes,
            is_list_question=is_list_question
        )

        node_ids = search_result.get("node_ids", [])

        # Build context from relevant nodes
        context = self._build_context_from_nodes(tree, node_ids)

        # Build source nodes with relevance info
        sources = []
        for node_id in node_ids:
            node = self._get_node_by_id(tree, node_id)
            if node:
                sources.append({
                    "id": node_id,
                    "title": node.get("title", ""),
                    "relevance": 0.8
                })

        # Build debug path
        debug_path = []
        for path in search_result.get("paths", []):
            debug_path.extend(path)

        # Handle tool intents
        if tool_intent == "extract_dates":
            history_text = self._build_history_text(history)
            prompt = self._build_date_extraction_prompt(question, context, history_text)
            answer = await self.llm.chat(prompt)

            return {
                "answer": answer,
                "sources": sources,
                "debug_path": debug_path,
                "provider": self.llm.provider,
                "model": self.llm.model,
                "system_prompt": prompt,
                "raw_output": answer,
                "tool_call": {"name": "extract_dates", "status": "completed"},
            }

        elif tool_intent == "extract_budget":
            return await self._handle_extract_budget(
                question, tree, history, context, sources, debug_path, document_id
            )

        elif tool_intent == "add_to_timeline":
            return await self._handle_add_to_timeline(
                question, tree, history, context, sources, debug_path, document_id
            )

        # Normal chat flow
        history_text = self._build_history_text(history)
        prompt = self._build_chat_prompt(question, context, history_text)
        answer = await self.llm.chat(prompt)

        return {
            "answer": answer,
            "sources": sources,
            "debug_path": debug_path,
            "provider": self.llm.provider,
            "model": self.llm.model,
            "system_prompt": prompt,
            "raw_output": answer,
        }

    def _build_history_text(self, history: List[dict]) -> str:
        """
        Build conversation history text for the prompt.

        Args:
            history: List of {role, content} dicts

        Returns:
            Formatted history text
        """
        if not history:
            return ""

        history_lines = []
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                history_lines.append(f"User: {content}")
            elif role == "assistant":
                history_lines.append(f"Assistant: {content}")

        return "\n".join(history_lines)

    def _build_chat_prompt(self, question: str, context: str, history_text: str) -> str:
        """
        Build the chat prompt with history and context.

        Args:
            question: Current user question
            context: Document context
            history_text: Formatted conversation history

        Returns:
            Complete prompt for the LLM
        """
        if history_text:
            prompt = f"""You are a helpful assistant that answers questions based on the provided document content. The user may ask follow-up questions that reference previous parts of the conversation.

Conversation History:
{history_text}

Current User Question: {question}

Relevant Document Content:
{context}

Instructions:
1. Answer the question using ONLY the provided document content
2. Consider the conversation history for context and pronoun references
3. If the answer cannot be found in the content, say so clearly
4. Be concise but thorough
5. Reference specific sections when relevant
6. For follow-up questions, maintain continuity with previous answers

Answer:"""
        else:
            prompt = f"""You are a helpful assistant that answers questions based on the provided document content.

User Question: {question}

Relevant Document Content:
{context}

Instructions:
1. Answer the question using ONLY the provided document content
2. If the answer cannot be found in the content, say so clearly
3. Be concise but thorough
4. Reference specific sections when relevant

Answer:"""

        return prompt
