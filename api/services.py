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
        """Count total characters in tree content."""
        count = 0
        if content := tree.get("content"):
            count += len(content)
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
        """Check if any node has content."""
        if tree.get("content"):
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
    def convert_page_index_to_api_format(page_index_tree: dict) -> dict:
        """
        Convert PageIndex internal format to API format.

        PageIndex format -> API format:
        - title -> title
        - node_id -> id
        - text -> content
        - summary -> summary
        - nodes -> children
        - (derived) -> level (based on nesting)
        - start_index -> page_start (PDF only)
        - end_index -> page_end (PDF only)
        - line_num -> line_start (Markdown only)
        - display_title -> display_title (for UI, cleaned version of title)
        - is_noise -> is_noise (boolean, marks invalid entries)
        """
        def convert_node(node: dict, level: int = 0) -> dict:
            api_node = {
                "id": node.get("node_id", ""),
                "title": node.get("title", ""),
                "level": level,
                "children": []
            }

            # Optional fields
            if "text" in node:
                api_node["content"] = node["text"]
            if "summary" in node:
                api_node["summary"] = node["summary"]

            # Display enhancement fields (NEW)
            if "display_title" in node:
                api_node["display_title"] = node["display_title"]
            if "is_noise" in node:
                api_node["is_noise"] = node["is_noise"]

            # PDF-specific fields
            # Note: PageIndex already uses 1-based indexing, so no conversion needed
            if "start_index" in node:
                api_node["page_start"] = node["start_index"]
            if "end_index" in node:
                api_node["page_end"] = node["end_index"]

            # Markdown-specific fields
            if "line_num" in node:
                api_node["line_start"] = node["line_num"]

            # Recursively convert children
            for child in node.get("nodes", []):
                api_node["children"].append(convert_node(child, level + 1))

            return api_node

        # PageIndex output wraps in "structure" array
        # For documents with TOC, there may be multiple root-level sections
        # We'll create a virtual root node
        structure = page_index_tree.get("structure", [])

        if len(structure) == 0:
            # Empty document
            return {
                "id": "root",
                "title": page_index_tree.get("doc_name", "Document"),
                "level": 0,
                "children": []
            }

        if len(structure) == 1:
            # Single root section - convert it directly
            return convert_node(structure[0], 0)
        else:
            # Multiple root sections - create virtual root
            return {
                "id": "root",
                "title": page_index_tree.get("doc_name", "Document"),
                "level": 0,
                "children": [convert_node(s, 1) for s in structure]
            }

    @staticmethod
    def convert_api_to_page_index_format(api_tree: dict) -> dict:
        """
        Convert API format to PageIndex internal format.
        
        API format -> PageIndex format:
        - id -> node_id
        - title -> title
        - content -> text
        - summary -> summary
        - children -> nodes
        - page_start -> start_index (PDF only)
        - page_end -> end_index (PDF only)
        - line_start -> line_num (Markdown only)
        """
        def convert_node(node: dict) -> dict:
            page_index_node = {
                "node_id": node.get("id", ""),
                "title": node.get("title", ""),
                "nodes": []
            }
            
            # Optional fields
            if "content" in node:
                page_index_node["text"] = node["content"]
            if "summary" in node:
                page_index_node["summary"] = node["summary"]
            
            # PDF-specific fields
            if "page_start" in node:
                page_index_node["start_index"] = node["page_start"]
            if "page_end" in node:
                page_index_node["end_index"] = node["page_end"]
            
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

    def _get_node_by_id(self, tree: dict, node_id: str) -> Optional[dict]:
        """Find a node by its ID."""
        if tree.get("id") == node_id:
            return tree
        for child in tree.get("children", []):
            result = self._get_node_by_id(child, node_id)
            if result:
                return result
        return None

    def _build_context_from_nodes(self, tree: dict, node_ids: List[str]) -> str:
        """
        Build context string from relevant nodes.

        Strategy:
        - If pdf_file_path is available: Load actual page content dynamically
        - Otherwise: Use stored content (truncated) or summary

        This allows the tree to be lightweight while still providing
        full content during chat.
        """
        context_parts = []

        for node_id in node_ids:
            node = self._get_node_by_id(tree, node_id)
            if node:
                title = node.get("title", "")

                # Try to load actual page content if PDF is available
                if self.pdf_file_path and self.storage_service:
                    page_start = node.get("page_start")
                    page_end = node.get("page_end")
                    if page_start and page_end:
                        try:
                            pages = self.storage_service.get_pdf_pages(
                                self.pdf_file_path, page_start, page_end
                            )
                            content = "\n\n".join([p[1] for p in pages])
                            context_parts.append(f"# {title}\n\n{content}")
                            continue
                        except Exception as e:
                            logger.warning(f"Failed to load pages for {title}: {e}")

                # Fallback to stored content (truncated) or summary
                content = node.get("content") or node.get("summary", "")
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

    async def answer_question(
        self,
        question: str,
        tree: dict,
        history: Optional[List[dict]] = None,
        max_source_nodes: int = 8
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

        # Build conversation history text
        history_text = self._build_history_text(history)

        # Generate answer with history awareness
        prompt = self._build_chat_prompt(question, context, history_text)

        answer = await self.llm.chat(prompt)

        # Build source nodes with relevance info
        sources = []
        for node_id in node_ids:
            node = self._get_node_by_id(tree, node_id)
            if node:
                sources.append({
                    "id": node_id,
                    "title": node.get("title", ""),
                    "relevance": 0.8  # Default relevance (could be refined)
                })

        # Build debug path
        debug_path = []
        for path in search_result.get("paths", []):
            debug_path.extend(path)

        return {
            "answer": answer,
            "sources": sources,
            "debug_path": debug_path,
            "provider": self.llm.provider,
            "model": self.llm.model,
            "system_prompt": prompt,  # Return the complete system prompt
            "raw_output": answer,  # Raw LLM output (same as answer in this case)
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
