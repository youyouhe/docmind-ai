"""
PageIndex FastAPI Backend Service

A vectorless, reasoning-based RAG system that builds hierarchical
tree structures from long documents (PDFs and Markdown) and uses
LLM reasoning for human-like document retrieval.
"""

from .index import app

__all__ = ["app"]
__version__ = "0.2.0"
