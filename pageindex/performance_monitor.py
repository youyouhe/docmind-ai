"""
Performance monitoring utilities for PageIndex.

Tracks LLM API calls, timing, and resource usage.
"""

import time
import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import asynccontextmanager

logger = logging.getLogger("pageindex.perf")


class PerformanceMonitor:
    """Monitor and track performance metrics."""

    def __init__(self):
        self.metrics = {
            "stages": {},
            "llm_calls": {
                "total": 0,
                "by_stage": {},
                "errors": 0,
                "retries": 0
            },
            "tokens": {
                "total_input": 0,
                "total_output": 0,
                "by_stage": {}
            },
            "timing": {
                "total": 0,
                "by_stage": {},
                "llm_total": 0
            }
        }
        self._current_stage: Optional[str] = None
        self._stage_start_time: Optional[float] = None

    @asynccontextmanager
    async def stage(self, stage_name: str):
        """Context manager for tracking a processing stage."""
        self._current_stage = stage_name
        start_time = time.time()

        logger.info(f"[PERF] >>> Stage started: {stage_name}")

        try:
            yield
        finally:
            duration = time.time() - start_time
            self.metrics["stages"][stage_name] = self.metrics["stages"].get(stage_name, {})
            self.metrics["stages"][stage_name]["duration"] = \
                self.metrics["stages"][stage_name].get("duration", 0) + duration
            self.metrics["timing"]["by_stage"][stage_name] = \
                self.metrics["timing"]["by_stage"].get(stage_name, 0) + duration
            self.metrics["timing"]["total"] += duration

            calls = self.metrics["llm_calls"]["by_stage"].get(stage_name, 0)
            logger.info(f"[PERF] <<< Stage completed: {stage_name} "
                       f"duration={duration:.2f}s llm_calls={calls}")

    def track_llm_call(self, stage: str, model: str, input_tokens: int = 0,
                       output_tokens: int = 0, success: bool = True,
                       retry: bool = False) -> None:
        """Record an LLM API call."""
        self.metrics["llm_calls"]["total"] += 1
        self.metrics["llm_calls"]["by_stage"][stage] = \
            self.metrics["llm_calls"]["by_stage"].get(stage, 0) + 1

        if not success:
            self.metrics["llm_calls"]["errors"] += 1
        if retry:
            self.metrics["llm_calls"]["retries"] += 1

        self.metrics["tokens"]["total_input"] += input_tokens
        self.metrics["tokens"]["total_output"] += output_tokens
        self.metrics["tokens"]["by_stage"][stage] = self.metrics["tokens"]["by_stage"].get(stage, {})
        self.metrics["tokens"]["by_stage"][stage]["input"] = \
            self.metrics["tokens"]["by_stage"][stage].get("input", 0) + input_tokens
        self.metrics["tokens"]["by_stage"][stage]["output"] = \
            self.metrics["tokens"]["by_stage"][stage].get("output", 0) + output_tokens

        logger.debug(f"[PERF] LLM call: stage={stage} model={model} "
                    f"input={input_tokens} output={output_tokens} "
                    f"success={success} retry={retry}")

    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary."""
        return {
            "total_duration_seconds": self.metrics["timing"]["total"],
            "llm_total_duration": self.metrics["timing"]["llm_total"],
            "total_llm_calls": self.metrics["llm_calls"]["total"],
            "llm_errors": self.metrics["llm_calls"]["errors"],
            "llm_retries": self.metrics["llm_calls"]["retries"],
            "total_input_tokens": self.metrics["tokens"]["total_input"],
            "total_output_tokens": self.metrics["tokens"]["total_output"],
            "stages": dict(self.metrics["stages"]),
            "llm_calls_by_stage": dict(self.metrics["llm_calls"]["by_stage"])
        }

    def print_summary(self) -> None:
        """Print formatted performance summary."""
        summary = self.get_summary()

        print("\n" + "=" * 60)
        print("PERFORMANCE SUMMARY")
        print("=" * 60)

        print(f"\nTotal Duration: {summary['total_duration_seconds']:.2f}s")
        print(f"LLM Duration: {summary['llm_total_duration']:.2f}s")
        print(f"\nTotal LLM Calls: {summary['total_llm_calls']}")
        print(f"  - Errors: {summary['llm_errors']}")
        print(f"  - Retries: {summary['llm_retries']}")

        print(f"\nTokens:")
        print(f"  - Input: {summary['total_input_tokens']:,}")
        print(f"  - Output: {summary['total_output_tokens']:,}")

        print("\nStages:")
        for stage, data in summary['stages'].items():
            duration = data.get('duration', 0)
            calls = summary['llm_calls_by_stage'].get(stage, 0)
            print(f"  - {stage}: {duration:.2f}s, {calls} calls")

        print("\n" + "=" * 60 + "\n")


# Global instance
_monitor: Optional[PerformanceMonitor] = None


def get_monitor() -> PerformanceMonitor:
    """Get or create the global performance monitor."""
    global _monitor
    if _monitor is None:
        _monitor = PerformanceMonitor()
    return _monitor


def reset_monitor() -> None:
    """Reset the global performance monitor."""
    global _monitor
    _monitor = None


def track_llm_sync(stage: str, model_param: str = "model"):
    """Decorator for tracking synchronous LLM calls."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            monitor = get_monitor()
            model = kwargs.get(model_param, args[1] if len(args) > 1 else "unknown")

            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                # Estimate tokens (rough approximation)
                input_tokens = len(str(kwargs.get('prompt', args[0]))) // 4
                output_tokens = len(str(result)) // 4

                monitor.track_llm_call(
                    stage=stage,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=True
                )

                monitor.metrics["timing"]["llm_total"] += duration
                return result

            except Exception as e:
                duration = time.time() - start_time
                monitor.metrics["timing"]["llm_total"] += duration
                monitor.track_llm_call(stage, model, success=False, retry=False)
                raise

        return wrapper
    return decorator


def track_llm_async(stage: str, model_param: str = "model"):
    """Decorator for tracking async LLM calls."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            monitor = get_monitor()
            model = kwargs.get(model_param, args[1] if len(args) > 1 else "unknown")

            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time

                # Estimate tokens
                input_tokens = len(str(kwargs.get('prompt', args[0]))) // 4
                output_tokens = len(str(result)) // 4

                monitor.track_llm_call(
                    stage=stage,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=True
                )

                monitor.metrics["timing"]["llm_total"] += duration
                return result

            except Exception as e:
                duration = time.time() - start_time
                monitor.metrics["timing"]["llm_total"] += duration
                monitor.track_llm_call(stage, model, success=False, retry=False)
                raise

        return wrapper
    return decorator
