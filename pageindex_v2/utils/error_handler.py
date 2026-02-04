"""
Error handling utilities for PageIndex V2
Distinguishes between fatal and recoverable errors
"""


def is_fatal_llm_error(error: Exception) -> bool:
    """
    Check if an LLM error is fatal and should stop execution
    
    Fatal errors include:
    - Insufficient balance (402)
    - Authentication failures (401, 403)
    - Invalid API keys
    - Authorization errors
    
    Args:
        error: Exception from LLM call
        
    Returns:
        True if error is fatal and execution should stop
    """
    error_msg = str(error).lower()
    
    fatal_patterns = [
        'insufficient balance',      # Payment/balance issues
        'error code: 402',           # Payment required (HTTP 402)
        'invalid api key',           # API key problems
        'invalid_api_key',           
        'error code: 401',           # Unauthorized (HTTP 401)
        'unauthorized',              
        'authentication failed',     # Auth failures
        'authentication error',
        'error code: 403',           # Forbidden (HTTP 403)
        'forbidden',
        'api key not valid',         # Key validation
        'invalid authentication',    # Auth validation
        'account deactivated',       # Account issues
        'account suspended',
        'rate limit exceeded',       # Hard rate limits (different from soft throttling)
        'quota exceeded',            # Quota exhausted
    ]
    
    return any(pattern in error_msg for pattern in fatal_patterns)


def handle_fatal_error(error: Exception, context: str = "LLM operation") -> None:
    """
    Print helpful error message and raise RuntimeError for fatal errors
    
    Args:
        error: The fatal exception
        context: Description of what operation failed
    """
    import sys
    
    # Helper to safely print Unicode characters on Windows
    def safe_print(msg: str):
        try:
            print(msg)
        except UnicodeEncodeError:
            # Fallback for Windows console
            safe_msg = msg.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')
            print(safe_msg)
    
    safe_print(f"\n{'='*70}")
    safe_print(f"❌ FATAL ERROR during {context}")
    safe_print(f"{'='*70}")
    safe_print(f"Error: {error}")
    safe_print("\n🔧 Common solutions:")
    
    error_msg = str(error).lower()
    
    if 'insufficient balance' in error_msg or '402' in error_msg:
        safe_print("  💰 Insufficient Balance:")
        safe_print("     - Recharge your DeepSeek account at: https://platform.deepseek.com/")
        safe_print("     - Or switch to OpenAI: --provider openai")
        
    elif 'invalid api key' in error_msg or '401' in error_msg or 'unauthorized' in error_msg:
        safe_print("  🔑 Invalid API Key:")
        safe_print("     - Check your .env file has the correct API key")
        safe_print("     - For DeepSeek: DEEPSEEK_API_KEY=sk-...")
        safe_print("     - For OpenAI: OPENAI_API_KEY=sk-...")
        
    elif '403' in error_msg or 'forbidden' in error_msg:
        safe_print("  🚫 Access Forbidden:")
        safe_print("     - Verify your API key has proper permissions")
        safe_print("     - Check if your account is active")
        
    elif 'rate limit' in error_msg or 'quota exceeded' in error_msg:
        safe_print("  ⏱️  Rate Limit/Quota Exceeded:")
        safe_print("     - Wait before trying again")
        safe_print("     - Reduce --verification-concurrency (currently high)")
        safe_print("     - Or upgrade your API plan")
    
    else:
        safe_print("  ❓ Unknown Fatal Error:")
        safe_print("     - Check your API service status")
        safe_print("     - Verify your .env configuration")
        safe_print("     - Try with --provider openai if using DeepSeek")
    
    safe_print(f"{'='*70}\n")
    
    raise RuntimeError(f"Fatal error in {context}: {error}") from error


def should_continue_on_error(error: Exception) -> bool:
    """
    Determine if processing should continue after an error
    
    Returns:
        True if error is recoverable and processing can continue
        False if error is fatal and processing should stop
    """
    return not is_fatal_llm_error(error)
