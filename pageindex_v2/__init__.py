"""
PageIndex V2 - Enhanced Document Structure Extraction

Features:
- DeepSeek support (cost-effective)
- Chinese document optimization
- 4-level hierarchical constraint
- Table structure preservation
- Detailed debug output
- Async processing

Modules:
- core: LLM client, PDF parser
- phases: TOC detection, extraction, mapping, verification, tree building
- utils: Helpers, JSON parsing, tree operations
"""

__version__ = "2.0.0"
__author__ = "Enhanced PageIndex"

from .core.llm_client import LLMClient
from .core.pdf_parser import PDFParser, PDFPage
from .phases.toc_detector import TOCDetector
from .phases.toc_extractor import TOCExtractor
from .phases.page_mapper import PageMapper
from .phases.verifier import Verifier
from .phases.tree_builder import TreeBuilder
from .main import PageIndexV2, ProcessingOptions

# Legacy compatibility layer
from .legacy_adapter import page_index_main, config, ConfigLoader

__all__ = [
    # Core modules
    'LLMClient',
    'PDFParser',
    'PDFPage', 
    'TOCDetector',
    'TOCExtractor',
    'PageMapper',
    'Verifier',
    'TreeBuilder',
    'PageIndexV2',
    'ProcessingOptions',
    
    # Legacy compatibility (for drop-in replacement of old pageindex)
    'page_index_main',
    'config',
    'ConfigLoader',
]
