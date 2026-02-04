"""
LLM Client - Multi-provider support with DeepSeek optimization
Supports: OpenAI, DeepSeek, and compatible APIs
Features: Async calls, debug logging, retry mechanism
"""
import os
import json
import asyncio
from typing import Any, Dict, Optional, List
from openai import AsyncOpenAI


class LLMClient:
    """
    Async LLM client with multi-provider support
    Optimized for DeepSeek with detailed debug logging
    """
    
    def __init__(
        self,
        provider: str = "deepseek",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        debug: bool = True
    ):
        self.provider = provider.lower()
        self.debug = debug  # Set debug first!
        self.model = model or self._get_default_model()
        self.api_key = api_key or self._get_api_key()
        self.base_url = base_url or self._get_base_url()
        self.client = None
        self._init_client()
    
    def _get_default_model(self) -> str:
        """Get default model for provider"""
        defaults = {
            "deepseek": "deepseek-chat",
            "openai": "gpt-4o",
        }
        return defaults.get(self.provider, "deepseek-chat")
    
    def _get_api_key(self) -> str:
        """Get API key from environment"""
        env_vars = {
            "deepseek": "DEEPSEEK_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        env_var = env_vars.get(self.provider, "OPENAI_API_KEY")
        key = os.getenv(env_var, "")
        
        if self.debug and key:
            masked = key[:10] + "..." + key[-4:] if len(key) > 14 else "***"
            print(f"[LLM] Loaded {self.provider.upper()} API Key: {masked}")
        
        return key
    
    def _get_base_url(self) -> Optional[str]:
        """Get base URL for provider"""
        urls = {
            "deepseek": "https://api.deepseek.com/v1",
            "openai": None,  # Use default
        }
        return urls.get(self.provider)
    
    def _init_client(self):
        """Initialize async client"""
        if not self.api_key:
            print(f"[LLM] Warning: No API key for {self.provider}")
            return
        
        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        
        self.client = AsyncOpenAI(**kwargs)
        
        if self.debug:
            print(f"[LLM] Initialized {self.provider} client")
            print(f"[LLM] Model: {self.model}")
            if self.base_url:
                print(f"[LLM] Base URL: {self.base_url}")
    
    async def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
        max_tokens: Optional[int] = None,
        response_format: Optional[str] = None
    ) -> str:
        """
        Async chat with retry and debug logging
        
        Args:
            prompt: User prompt
            system: System message
            temperature: Sampling temperature
            max_retries: Maximum retry attempts
            max_tokens: Maximum tokens in response
            response_format: Optional response format ("json_object" for JSON mode)
        """
        if not self.client:
            raise ValueError("LLM client not initialized. Check API key.")
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        if self.debug:
            print(f"\n{'='*60}")
            print(f"[LLM REQUEST] {self.model}")
            print(f"{'='*60}")
            if system:
                sys_preview = system[:150].replace('\n', ' ')
                print(f"[SYSTEM] {sys_preview}...")
            prompt_preview = prompt[:300].replace('\n', ' ')
            print(f"[PROMPT] {prompt_preview}...")
            print(f"[PARAMS] temp={temperature}, retries={max_retries}, format={response_format}")
        
        for attempt in range(max_retries):
            try:
                params = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                }
                
                # Only use JSON mode if explicitly requested
                if response_format == "json_object" and self._supports_json():
                    params["response_format"] = {"type": "json_object"}
                
                if max_tokens:
                    params["max_tokens"] = max_tokens
                
                response = await self.client.chat.completions.create(**params)
                
                content = response.choices[0].message.content
                
                if self.debug:
                    usage = response.usage
                    print(f"\n[LLM RESPONSE] Tokens: {usage.prompt_tokens} → {usage.completion_tokens} (total: {usage.total_tokens})")
                    content_preview = content[:200].replace('\n', ' ')
                    print(f"[CONTENT] {content_preview}...")
                    print(f"{'='*60}")
                
                return content
                
            except Exception as e:
                print(f"[LLM ERROR] Attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    raise
    
    def _supports_json(self) -> bool:
        """Check if model supports JSON mode"""
        return self.provider in ["openai", "deepseek"]
    
    async def chat_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Chat with JSON parsing and structured output
        
        Automatically ensures the prompt contains "json" keyword for DeepSeek API
        and uses response_format: json_object for supported providers.
        """
        # DeepSeek requires the word "json" in prompt when using response_format: json_object
        # Check both system and user prompt
        has_json_keyword = "json" in prompt.lower()
        if system:
            has_json_keyword = has_json_keyword or "json" in system.lower()
        
        if self.provider == "deepseek" and not has_json_keyword:
            prompt = f"{prompt}\n\nPlease respond in JSON format."
        
        # Use JSON response format
        content = await self.chat(
            prompt, 
            system, 
            temperature, 
            max_tokens=max_tokens,
            response_format="json_object"
        )
        
        try:
            # Clean up markdown if present
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[JSON ERROR] Failed to parse: {e}")
            print(f"[RAW CONTENT] {content[:500]}")
            return {}


# Batch processing helper
async def batch_llm_calls(
    client: LLMClient,
    prompts: List[str],
    max_concurrent: int = 5,
    debug: bool = True
) -> List[str]:
    """
    Execute multiple LLM calls concurrently with rate limiting
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def call_with_limit(prompt: str, index: int) -> str:
        async with semaphore:
            if debug:
                print(f"[BATCH] Processing item {index + 1}/{len(prompts)}")
            try:
                return await client.chat(prompt)
            except Exception as e:
                print(f"[BATCH ERROR] Item {index + 1}: {e}")
                return ""
    
    tasks = [call_with_limit(p, i) for i, p in enumerate(prompts)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out exceptions
    valid_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"[BATCH] Item {i + 1} failed: {r}")
            valid_results.append("")
        else:
            valid_results.append(r)
    
    return valid_results
