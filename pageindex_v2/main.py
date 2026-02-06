"""
PageIndex V2 - Main Entry Point
Integrates all phases with 5 key advantages:
1. DeepSeek support
2. Chinese optimization  
3. 4-level depth constraint
4. Table structure preservation
5. Detailed debug output
"""
import os
import sys
import asyncio
import json
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .core.llm_client import LLMClient
from .core.pdf_parser import PDFParser, PDFPage
from .phases.toc_detector import TOCDetector
from .phases.toc_extractor import TOCExtractor
from .phases.page_mapper import PageMapper
from .phases.verifier import Verifier
from .phases.tree_builder import TreeBuilder


@dataclass
class ProcessingOptions:
    """Configuration options for PageIndex V2"""
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    max_depth: int = 4
    toc_check_pages: int = 20
    debug: bool = True
    progress: bool = True  # Show progress even in quiet mode
    output_dir: str = "./results"
    enable_recursive_processing: bool = True
    skip_verification_for_large_pdf: bool = True
    large_pdf_threshold: int = 200
    max_pages_per_node: int = 15  # For recursive processing
    max_tokens_per_node: int = 25000  # Token limit for nodes
    max_verify_count: int = 100  # Maximum nodes to verify (reduced from 200 for speed)
    verification_concurrency: int = 20  # Concurrent LLM calls during verification
    normalize_titles: bool = True  # Normalize titles with hierarchical numbering (1, 1.1, 1.1.1)


class PageIndexV2:
    """
    Main orchestrator for PDF index generation
    """
    
    def __init__(self, options: Optional[ProcessingOptions] = None, document_id: Optional[str] = None):
        self.opt = options or ProcessingOptions()
        self.llm: Optional[LLMClient] = None
        self.debug = self.opt.debug
        self.progress = self.opt.progress
        self.document_id = document_id
        
        # Setup logger
        if document_id:
            # Use file logger for API calls
            try:
                # Import logger_utils (relative to project root)
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                from api.logger_utils import create_document_logger
                self.logger = create_document_logger(document_id, "pageindex_v2")
            except Exception:
                # Fallback to standard logger
                self.logger = logging.getLogger(f"pageindex_v2.{document_id}")
        else:
            # Use standard console logger for standalone usage
            self.logger = logging.getLogger("pageindex_v2")
        
        if self.debug:
            self.logger.info("=" * 70)
            self.logger.info("PageIndex V2 - Document Structure Extractor")
            self.logger.info("=" * 70)
            self.logger.info(f"Provider: {self.opt.provider}")
            self.logger.info(f"Model: {self.opt.model}")
            self.logger.info(f"Max Depth: {self.opt.max_depth}")
            self.logger.info(f"Debug Mode: {self.opt.debug}")
            self.logger.info("=" * 70)
            
            print("=" * 70)
            print("PageIndex V2 - Document Structure Extractor")
            print("=" * 70)
            print(f"Provider: {self.opt.provider}")
            print(f"Model: {self.opt.model}")
            print(f"Max Depth: {self.opt.max_depth}")
            print(f"Debug Mode: {self.opt.debug}")
            print("=" * 70)
    
    def log_progress(self, message: str, force: bool = False):
        """Print progress message (shown even in quiet mode unless force=False)"""
        if self.progress or force:
            import sys
            # Log to file if document_id is set
            if self.document_id:
                self.logger.info(message)
            
            # Handle Unicode characters on Windows (gbk encoding)
            try:
                print(message, flush=True)
            except UnicodeEncodeError:
                # Fallback: encode with error handling for terminals that don't support UTF-8
                safe_message = message.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')
                print(safe_message, flush=True)
            sys.stdout.flush()
    
    async def process_pdf(self, pdf_path: str) -> dict:
        """
        Main processing pipeline
        
        Returns:
            Document structure tree with metadata
        """
        import time
        start_time = time.time()
        
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        self.log_progress(f"\n{'='*70}")
        self.log_progress(f"📚 Processing: {os.path.basename(pdf_path)}")
        self.log_progress(f"{'='*70}")
        
        # Initialize LLM client
        self.llm = LLMClient(
            provider=self.opt.provider,
            model=self.opt.model,
            debug=self.debug
        )
        
        if not self.llm.client:
            raise RuntimeError("Failed to initialize LLM client. Check API key.")
        
        # Phase 1: Parse PDF (LAZY MODE - only parse first 30 pages initially)
        self.log_progress("\n📄 [1/6] PDF Parsing - Initial pages...")
        if self.debug:
            print("\n📄 PHASE 1A: PDF Parsing (Initial Pages Only)")
        parser = PDFParser(debug=self.debug)
        
        # Get total page count first
        import fitz
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()
        
        initial_parse_pages = 30  # Parse first 30 pages for TOC detection
        pages = await parser.parse(pdf_path, max_pages=initial_parse_pages)
        
        if not pages:
            raise ValueError("No pages extracted from PDF")
        
        if self.debug:
            print(f"[PHASE 1A] Parsed {len(pages)}/{total_pages} pages initially")
            print(f"[PHASE 1A] Deferred parsing of remaining {total_pages - len(pages)} pages")
        
        self.log_progress(f"   ✓ Parsed {len(pages)}/{total_pages} pages initially")
        
        # Phase 2: TOC Detection
        self.log_progress("\n📑 [2/6] TOC Detection...")
        if self.debug:
            print("\n📑 PHASE 2: TOC Detection")
        
        # OPTIMIZATION: Check for embedded PDF TOC first (instant extraction)
        doc = fitz.open(pdf_path)
        embedded_toc = doc.get_toc()
        doc.close()
        
        if embedded_toc and len(embedded_toc) >= 5:
            # PDF has embedded TOC with sufficient entries
            if self.debug:
                print(f"[PHASE 2] ✓ Found embedded PDF TOC with {len(embedded_toc)} entries")
                print(f"[PHASE 2] → Using embedded TOC (instant extraction)")
                print("="*70)
            
            # Convert embedded TOC to our structure format (with quality filtering)
            structure = self._convert_embedded_toc_to_structure(embedded_toc)
            
            # Quality threshold check: if too many entries were filtered, fall back to text-based detection
            quality_ratio = len(structure) / len(embedded_toc) if len(embedded_toc) > 0 else 0
            
            if quality_ratio < 0.5 and len(structure) < 5:
                # More than 50% filtered OR too few valid entries remain
                if self.debug:
                    print(f"[PHASE 2] ⚠ Embedded TOC quality too poor ({quality_ratio:.1%} valid entries)")
                    print(f"[PHASE 2] → Only {len(structure)}/{len(embedded_toc)} entries survived filtering")
                    print(f"[PHASE 2] → Falling back to text-based TOC detection")
                
                # Clear structure and fall through to text-based detection
                structure = []
                embedded_toc = []
            else:
                # Quality is acceptable, use embedded TOC
                has_page_numbers = True
                toc_pages = []  # No text-based TOC pages
                toc_info = {}
                
                if self.debug:
                    print(f"[PHASE 2] Converted {len(structure)} items from embedded TOC")
                    print(f"[PHASE 2] Quality: {quality_ratio:.1%} ({len(structure)}/{len(embedded_toc)} entries valid)")
                    print(f"[PHASE 2] Sample entries:")
                    for i, item in enumerate(structure[:5]):
                        print(f"  {i+1}. [{item['level']}] {item['title']} → Page {item['page']}")
                
                self.log_progress(f"   ✓ Extracted {len(structure)} items from embedded TOC")
                
                # Skip text-based TOC detection
                candidate_pages_for_parsing = []
        
        # If embedded TOC was not used (either missing, insufficient, or poor quality), use text-based detection
        if not embedded_toc or len(embedded_toc) < 5:
            # No embedded TOC or too few entries - use text-based detection
            if self.debug:
                if embedded_toc:
                    print(f"[PHASE 2] ⚠ Embedded TOC has only {len(embedded_toc)} entries (need ≥5)")
                else:
                    print(f"[PHASE 2] ⚠ No embedded TOC found")
                print("[PHASE 2] → Using text-based TOC detection (Lazy Mode)")
            
            detector = TOCDetector(self.llm, debug=self.debug)
            
            # Use lazy detection - only parse candidate pages
            toc_detection = await detector.detect_all_toc_pages_lazy(
                pdf_path=pdf_path,
                total_pages=total_pages,
                initial_pages=pages,
                check_first_n=initial_parse_pages
            )
            toc_pages = toc_detection['toc_pages']
            toc_info = toc_detection['toc_info']
            candidate_pages_for_parsing = toc_detection.get('candidate_pages_for_parsing', [])
        
        # Phase 1B: Parse candidate pages if needed
        if candidate_pages_for_parsing:
            if self.debug:
                print(f"\n📄 PHASE 1B: Parsing {len(candidate_pages_for_parsing)} candidate pages for nested TOC verification")
                print(f"  Candidate pages: {candidate_pages_for_parsing}")
            
            # Parse candidate pages one by one and verify
            for page_num in candidate_pages_for_parsing:
                # Parse single page
                page_idx = page_num - 1
                single_page = await parser.parse(pdf_path, max_pages=page_num)
                if page_idx < len(single_page):
                    # Verify if it's actually a TOC
                    is_toc = await detector._check_single_page(single_page[page_idx])
                    
                    if is_toc:
                        if self.debug:
                            print(f"  ✓ Page {page_num}: Confirmed as nested TOC")
                        toc_info[page_num]['type'] = 'nested'
                        toc_info[page_num]['needs_verification'] = False
                    else:
                        if self.debug:
                            print(f"  ✗ Page {page_num}: Not a TOC, removing from list")
                        # Remove from TOC pages
                        if page_num in toc_pages:
                            toc_pages.remove(page_num)
                        if page_num in toc_info:
                            del toc_info[page_num]
        
        # Phase 3: Extract Structure
        self.log_progress("\n📋 [3/6] Structure Extraction...")
        if self.debug:
            print("\n📋 PHASE 3: Structure Extraction")
            print("="*70)
        
        # Check if structure was already extracted from embedded TOC
        if 'structure' not in locals():
            # Structure not yet extracted - need to extract from text-based TOC
            extractor = TOCExtractor(self.llm, debug=self.debug)
        
        if 'structure' in locals() and 'has_page_numbers' in locals():
            # Already extracted from embedded TOC - skip to Phase 4
            if self.debug:
                print(f"[PHASE 3] ✓ Skipping extraction (already extracted from embedded TOC)")
                print(f"[PHASE 3] Structure has {len(structure)} items")
            self.log_progress(f"   ✓ Using {len(structure)} items from embedded TOC")
        elif toc_pages:
            # Convert 1-indexed to 0-indexed for internal use
            toc_pages_0indexed = [p - 1 for p in toc_pages]
            
            # Check if main TOC has page numbers
            main_toc_pages = [p for p in toc_pages if toc_info[p]['type'] == 'main']
            if main_toc_pages:
                main_toc_0indexed = [p - 1 for p in main_toc_pages]
                has_page_numbers, toc_content = await detector.detect_page_numbers_in_toc(
                    main_toc_0indexed, pages
                )
            else:
                # No main TOC, all are nested - no page numbers
                has_page_numbers = False
                toc_content = ""
            
            if self.debug:
                print(f"[PHASE 3] TOC detected on pages: {toc_pages}")
                print(f"[PHASE 3] TOC types: {[toc_info[p]['type'] for p in toc_pages]}")
                print(f"[PHASE 3] Main TOC has page numbers: {has_page_numbers}")
            
            if has_page_numbers and main_toc_pages:
                # Main TOC with page numbers - use it
                if self.debug:
                    print("[PHASE 3] ✓ Strategy: Using TOC structure (has page numbers)")
                    print(f"[PHASE 3] TOC content length: {len(toc_content)} chars")
                structure = await extractor.extract_structure(toc_content, has_page_numbers)
                
                # Phase 1B: Parse pages referenced by TOC (with margin for verification)
                if structure and len(pages) < total_pages:
                    # Collect all pages referenced by TOC
                    referenced_pages = set()
                    for item in structure:
                        page_num = item.get('page')
                        if page_num and isinstance(page_num, int):
                            referenced_pages.add(page_num)
                    
                    if referenced_pages:
                        # Find max page needed
                        max_page_needed = max(referenced_pages)
                        
                        # Expand range: add ±1 page for verification margin
                        margin = 1
                        max_page_with_margin = min(max_page_needed + margin, total_pages)
                        
                        if max_page_with_margin > len(pages):
                            if self.debug:
                                print(f"\n📄 PHASE 1B: Parsing additional pages for TOC verification")
                                print(f"[PHASE 1B] TOC references {len(referenced_pages)} unique pages (max: {max_page_needed})")
                                print(f"[PHASE 1B] With ±{margin} page margin: parsing up to page {max_page_with_margin}")
                                print(f"[PHASE 1B] Will parse {max_page_with_margin - len(pages)} additional pages")
                            
                            # Parse up to max page with margin
                            import time
                            parse_start = time.time()
                            
                            pages = await parser.parse(pdf_path, max_pages=max_page_with_margin)
                            
                            parse_time = time.time() - parse_start
                            
                            if self.debug:
                                print(f"[PHASE 1B] Parsed {max_page_with_margin} pages total in {parse_time:.1f}s")
                                print(f"[PHASE 1B] Coverage: {len(pages)}/{total_pages} pages ({len(pages)/total_pages*100:.1f}%)")
                        else:
                            if self.debug:
                                print(f"[PHASE 1B] All TOC-referenced pages already parsed (max: {max_page_needed})")
                
                
            else:
                # No main TOC with page numbers - use content analysis
                # (this will extract from ALL pages including nested TOCs)
                if self.debug:
                    if main_toc_pages:
                        print("[PHASE 3] ⚠ Strategy: TOC has no page numbers")
                    else:
                        print("[PHASE 3] ⚠ Strategy: Only nested TOCs detected")
                    print("[PHASE 3] → Using content-based analysis (includes nested TOCs)")
                    print("="*70)
                
                # For content-based analysis, we need all pages
                if len(pages) < total_pages:
                    if self.debug:
                        print(f"\n📄 PHASE 1B: Parsing remaining pages for content analysis")
                        print(f"[PHASE 1B] Need to parse {total_pages - len(pages)} more pages...")
                    
                    # Parse all remaining pages
                    all_pages = await parser.parse(pdf_path)
                    pages = all_pages
                
                structure = await self._generate_structure_from_content(pages)
                has_page_numbers = False
        else:
            # No TOC - generate from content
            if self.debug:
                print("[PHASE 3] ⚠ No TOC detected")
                print("[PHASE 3] → Using content-based analysis")
                print("="*70)
            
            # Need all pages for content analysis
            if len(pages) < total_pages:
                if self.debug:
                    print(f"\n📄 PHASE 1B: Parsing all pages for content analysis")
                all_pages = await parser.parse(pdf_path)
                pages = all_pages
            
            has_page_numbers = False
            structure = await self._generate_structure_from_content(pages)
        
        # Phase 4: Map Pages
        if self.debug:
            print("\n🗺️  PHASE 4: Page Mapping")
        
        # Check if we used embedded TOC (which already has accurate page numbers)
        if embedded_toc and len(embedded_toc) >= 5:
            # Embedded TOC has accurate page numbers - skip mapping
            # Convert 'page' field to 'physical_index' format for compatibility
            mapped = []
            for i, item in enumerate(structure):
                mapped_item = item.copy()
                page_num = item.get('page')
                if page_num:
                    mapped_item['physical_index'] = page_num
                    mapped_item['list_index'] = i
                    mapped_item['validation_passed'] = True  # Embedded TOC is accurate
                mapped.append(mapped_item)
            
            if self.debug:
                print(f"[PHASE 4] ✓ Skipping LLM-based mapping (embedded TOC has accurate page numbers)")
                print(f"[PHASE 4] Converted {len(mapped)} items with physical_index field")
            
            mapping_validation_accuracy = 1.0  # 100% accurate by definition
            self.log_progress(f"\n🗺️  [4/6] Page Mapping... ({len(mapped)} items)")
            self.log_progress(f"   ✓ Using embedded TOC pages (100% accurate)")
        else:
            # Use LLM-based page mapping for text-based TOC
            mapper = PageMapper(self.llm, debug=self.debug)
            mapped = await mapper.map_pages(structure, pages, has_page_numbers)
            
            # Calculate mapping validation accuracy
            mapping_validation_count = sum(1 for m in mapped if m.get('validation_passed'))
            mapping_validation_accuracy = mapping_validation_count / len(mapped) if mapped else 0
            self.log_progress(f"\n🗺️  [4/6] Page Mapping... ({len(mapped)} items)")
            self.log_progress(f"   ✓ Mapped to physical pages")
        
        # Phase 5: Verification
        self.log_progress(f"\n✅ [5/6] Verification... (up to {self.opt.max_verify_count} nodes)")
        if self.debug:
            print("\n✅ PHASE 5: Verification")
        
        # 优化验证策略：只验证叶子节点，最多200个
        from .utils.helpers import get_leaf_nodes, count_leaf_nodes
        
        leaf_nodes = get_leaf_nodes(mapped)
        leaf_count = len(leaf_nodes)
        total_count = len(mapped)
        
        if self.debug:
            print(f"[VERIFY] Total TOC items: {total_count}")
            print(f"[VERIFY] Leaf nodes: {leaf_count} ({leaf_count/total_count*100:.1f}%)")
        
        # 决策：限制验证数量（使用可配置参数）
        is_large_pdf = len(pages) > self.opt.large_pdf_threshold
        max_verify_count = self.opt.max_verify_count  # 默认 100 个节点
        
        if leaf_count > max_verify_count:
            # 按层级深度排序，优先验证深层节点（level越大越优先）
            # level = structure中点的数量，例如 "1.2.3" -> level 3
            def get_level(item):
                structure = item.get('structure', '0')
                return structure.count('.') if structure else 0
            
            # 按level降序排序（level大的在前）
            sorted_leaf_nodes = sorted(leaf_nodes, key=get_level, reverse=True)
            
            nodes_to_verify = sorted_leaf_nodes[:max_verify_count]
            nodes_skipped = sorted_leaf_nodes[max_verify_count:]
            
            if self.debug:
                print(f"[VERIFY] Too many leaf nodes ({leaf_count})")
                print(f"[VERIFY] Prioritizing by level (deeper nodes first)")
                # 显示level分布
                level_counts = {}
                for node in nodes_to_verify:
                    level = get_level(node)
                    level_counts[level] = level_counts.get(level, 0) + 1
                level_summary = ', '.join([f"L{k}:{v}" for k, v in sorted(level_counts.items(), reverse=True)])
                print(f"[VERIFY] Will verify {max_verify_count} nodes: {level_summary}")
                print(f"[VERIFY] Will skip {len(nodes_skipped)} nodes")
        elif is_large_pdf and self.opt.skip_verification_for_large_pdf:
            # 大PDF且设置了跳过标志
            nodes_to_verify = []
            nodes_skipped = leaf_nodes
            if self.debug:
                print(f"[VERIFY] Large PDF detected ({len(pages)} pages)")
                print("[VERIFY] Skipping verification for performance")
        else:
            # 全部验证
            nodes_to_verify = leaf_nodes
            nodes_skipped = []
            if self.debug:
                print(f"[VERIFY] Verifying {leaf_count} leaf nodes (skipping {total_count - leaf_count} parent nodes)")
        
        if nodes_to_verify:
            # 执行验证（使用可配置的并发参数）
            verifier = Verifier(
                self.llm, 
                debug=self.debug,
                concurrency=self.opt.verification_concurrency
            )
            verified_leaves, accuracy = await verifier.verify_structure(nodes_to_verify, pages)
            
            # 合并结果：叶子节点使用验证结果，父节点和未验证的叶子节点标记
            verified = []
            leaf_map = {item.get('list_index'): item for item in verified_leaves}
            skipped_map = {item.get('list_index'): item for item in nodes_skipped}
            
            for item in mapped:
                idx = item.get('list_index')
                if idx in leaf_map:
                    # 使用验证后的叶子节点
                    verified.append(leaf_map[idx])
                elif idx in skipped_map:
                    # 未验证的叶子节点：标记为未验证，但保留mapping结果
                    verified.append({
                        **item,
                        'verification_passed': item.get('validation_passed', False),  # 使用Phase 4的结果
                        'verified_existence': False,
                        'verification_skipped': True  # 标记为跳过验证
                    })
                else:
                    # 父节点：标记为已验证（因为子节点验证通过）
                    verified.append({
                        **item,
                        'verification_passed': True,
                        'verified_existence': True,
                        'verified_as_parent': True  # 标记为父节点
                    })
            
            # Fix incorrect items if needed (只修复已验证的项)
            if accuracy < 0.8:
                incorrect = [v for v in verified if not v.get('verification_passed') and not v.get('verification_skipped')]
                if incorrect and self.debug:
                    print(f"\n🔧 Fixing {len(incorrect)} incorrect items...")
                # Pass full structure for smart range search
                fixed = await verifier.fix_incorrect_items(verified, incorrect, pages)
                
                # Replace incorrect with fixed
                verified_map = {v['list_index']: v for v in verified}
                for f in fixed:
                    verified_map[f['list_index']] = f
                verified = list(verified_map.values())
        else:
            # 完全跳过验证
            verified = []
            for item in mapped:
                verified.append({
                    **item,
                    'verification_passed': item.get('validation_passed', False),  # 使用Phase 4的结果
                    'verified_existence': False,
                    'verification_skipped': True
                })
            accuracy = 1.0  # 假设正确（因为跳过了验证）
        
        # Phase 6: Build Tree
        self.log_progress(f"\n🌳 [6/6] Tree Building... ({len(structure)} items)")
        if self.debug:
            print("\n🌳 PHASE 6: Tree Building")
        builder = TreeBuilder(max_depth=self.opt.max_depth, debug=self.debug)
        tree = builder.build_tree(verified, pages)
        
        # Add preface if needed
        tree = builder.add_preface_if_needed(tree, pages)
        
        # Phase 6a: Recursive Large Node Processing
        if self.opt.enable_recursive_processing:
            self.log_progress(f"\n🔄 [6a/6] Recursive Large Node Processing...")
            if self.debug:
                print("\n🔄 PHASE 6a: Recursive Large Node Processing")
                print(f"[RECURSIVE] Checking {len(tree)} top-level nodes for large nodes")
            
            tasks = [
                self._process_large_node_recursively(node, pages)
                for node in tree
            ]
            tree = await asyncio.gather(*tasks)
            
            if self.debug:
                print(f"[RECURSIVE] Recursive processing complete")
        
        # Get statistics
        stats = builder.get_tree_statistics(tree)
        
        # Phase 6.5: Title Normalization (NEW!)
        if self.opt.normalize_titles:
            self.log_progress(f"\n🔤 [6.5/7] Title Normalization...")
            if self.debug:
                print("\n🔤 PHASE 6.5: Title Normalization")
            
            from .utils.title_normalizer import normalize_tree_list
            
            # Normalize all root nodes (tree is a List[Dict])
            tree = normalize_tree_list(tree, debug=self.debug)
            
            if self.debug:
                print("✓ Title normalization complete")
        
        elapsed_time = time.time() - start_time
        self.log_progress(f"\n{'='*70}")
        self.log_progress(f"✅ Processing Complete!")
        self.log_progress(f"   Total time: {elapsed_time:.1f}s ({elapsed_time/60:.1f} minutes)")
        self.log_progress(f"   Nodes extracted: {stats['total_nodes']} ({stats['root_nodes']} root)")
        self.log_progress(f"   Max depth: {stats['max_depth']}")
        self.log_progress(f"{'='*70}\n")
        
        # Calculate verification statistics
        verified_count = len(nodes_to_verify) if nodes_to_verify else 0
        skipped_count = len(nodes_skipped) if nodes_skipped else 0
        
        # Prepare result
        result = {
            "source_file": os.path.basename(pdf_path),
            "total_pages": total_pages,  # Use total_pages from PDF, not len(pages)
            "processing_options": {
                "provider": self.opt.provider,
                "model": self.opt.model,
                "max_depth": self.opt.max_depth
            },
            "statistics": stats,
            "mapping_validation_accuracy": mapping_validation_accuracy,
            "verification_accuracy": accuracy,
            "verification_stats": {
                "total_leaf_nodes": leaf_count,
                "verified_nodes": verified_count,
                "skipped_nodes": skipped_count
            },
            "structure": tree
        }
        
        # Phase 7: Gap Filling (Post-processing)
        if self.debug:
            print("\n🔧 PHASE 7: Gap Filling (Post-processing)")
        self.log_progress(f"\n🔧 [7/7] Gap Filling... (Analyzing coverage)")
        
        from .utils.gap_filler import fill_structure_gaps
        
        result = await fill_structure_gaps(
            structure_data=result,
            pdf_path=pdf_path,
            llm=self.llm,
            parser=parser,
            debug=self.debug
        )
        
        if 'gap_fill_info' in result:
            gap_info = result['gap_fill_info']
            if gap_info['gaps_found'] > 0:
                self.log_progress(f"   ⚠ Found {gap_info['gaps_found']} page gap(s)")
                self.log_progress(f"   ✓ Added supplementary TOC for missing pages")
            else:
                self.log_progress(f"   ✓ No gaps found - structure is complete")
        
        # Save results
        os.makedirs(self.opt.output_dir, exist_ok=True)
        pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        output_file = os.path.join(self.opt.output_dir, f"{pdf_name}_structure.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        if self.debug:
            print(f"\n✨ COMPLETE!")
            print(f"📁 Results saved to: {output_file}")
            print(f"📊 Tree statistics: {stats}")
            print(f"🗺️  Mapping validation accuracy: {mapping_validation_accuracy:.1%}")
            print(f"🎯 Verification accuracy: {accuracy:.1%}")
            print(f"📋 Verification stats: {verified_count}/{leaf_count} leaf nodes verified, {skipped_count} skipped")
            if 'gap_fill_info' in result:
                gap_info = result['gap_fill_info']
                print(f"🔧 Gap Fill: {gap_info['original_coverage']} pages covered ({gap_info['coverage_percentage']:.1f}%)")
                if gap_info['gaps_found'] > 0:
                    print(f"   ⚠ Filled {gap_info['gaps_found']} gap(s): {gap_info['gaps_filled']}")
        
        # Clean up LLM client
        if self.llm:
            await self.llm.close()
        
        return result
    
    async def _generate_structure_from_content(
        self, 
        pages: List[PDFPage], 
        parent_context: dict = None
    ) -> list:
        """
        Generate TOC structure from document content analysis
        Used when:
        1. No TOC page is detected, OR
        2. TOC exists but has no page numbers
        
        Strategy:
        - Scan entire document in segments
        - Extract hierarchical structure up to max_depth
        - Assign physical page indices
        
        Args:
            pages: List of PDFPage objects to analyze
            parent_context: Optional dict with 'structure' and 'title' of parent node
                           (used during recursive processing to maintain numbering context)
        """
        if self.debug:
            print("\n" + "="*70)
            print("[CONTENT ANALYSIS] Starting full document analysis")
            print("="*70)
            print(f"[CONTENT ANALYSIS] Total pages: {len(pages)}")
            print(f"[CONTENT ANALYSIS] Total tokens: {sum(p.tokens for p in pages)}")
            print(f"[CONTENT ANALYSIS] Max depth: {self.opt.max_depth}")
        
        # Prepare labeled content for entire document
        labeled_pages = []
        for page in pages:
            labeled_pages.append(page.labeled_content)
        
        # Divide into segments (similar to page_mapper's segmentation)
        segments = self._prepare_content_segments(pages, max_tokens=30000)
        
        if self.debug:
            print(f"[CONTENT ANALYSIS] Document divided into {len(segments)} segments")
            for i, seg in enumerate(segments, 1):
                print(f"  Segment {i}: pages {seg['start_page']}-{seg['end_page']}")
            print("="*70)
        
        # Initialize structure
        all_structure = []
        
        # Process each segment
        for seg_idx, segment in enumerate(segments):
            if self.debug:
                print(f"\n[CONTENT ANALYSIS] Processing segment {seg_idx + 1}/{len(segments)}")
                print(f"  Pages: {segment['start_page']}-{segment['end_page']}")
                print(f"  Content length: {len(segment['content'])} chars")
            
            segment_structure = await self._extract_structure_from_segment(
                segment, 
                existing_structure=all_structure,
                parent_context=parent_context,
                segment_index=seg_idx + 1
            )
            
            if self.debug:
                print(f"  Extracted {len(segment_structure)} items from this segment")
            
            # Merge with existing structure
            before_count = len(all_structure)
            all_structure = self._merge_structure_items(all_structure, segment_structure)
            added = len(all_structure) - before_count
            
            if self.debug:
                print(f"  Total structure items: {len(all_structure)} (+{added} new)")
        
        if self.debug:
            print("\n" + "="*70)
            print(f"[CONTENT ANALYSIS] Extraction complete: {len(all_structure)} items")
            print("="*70)
            print("[CONTENT ANALYSIS] Structure preview:")
            for i, item in enumerate(all_structure[:10], 1):
                struct = item.get('structure', '?')
                title = item.get('title', '')
                phys_idx = item.get('physical_index', 'N/A')
                print(f"  {i}. [{struct}] {title[:50]}... (page: {phys_idx})")
            if len(all_structure) > 10:
                print(f"  ... and {len(all_structure) - 10} more items")
            print("="*70)
        
        return all_structure
    
    def _prepare_content_segments(
        self, 
        pages: List[PDFPage], 
        max_tokens: int = 30000
    ) -> list:
        """Divide document into segments for content analysis"""
        segments = []
        current_pages = []
        current_tokens = 0
        
        for page in pages:
            if current_tokens + page.tokens > max_tokens and current_pages:
                # Save current segment
                content = "\n\n".join([p.labeled_content for p in current_pages])
                segments.append({
                    'content': content,
                    'start_page': current_pages[0].page_number,
                    'end_page': current_pages[-1].page_number
                })
                current_pages = [page]
                current_tokens = page.tokens
            else:
                current_pages.append(page)
                current_tokens += page.tokens
        
        # Add final segment
        if current_pages:
            content = "\n\n".join([p.labeled_content for p in current_pages])
            segments.append({
                'content': content,
                'start_page': current_pages[0].page_number,
                'end_page': current_pages[-1].page_number
            })
        
        return segments
    
    async def _extract_structure_from_segment(
        self, 
        segment: dict,
        existing_structure: list,
        segment_index: int = 1,
        parent_context: dict = None
    ) -> list:
        """Extract structure from a content segment"""
        
        if self.debug:
            print(f"  [LLM] Calling structure extraction for segment {segment_index}...")
        
        # Build context-aware prompt for parent subsection
        context_instruction = ""
        if parent_context and parent_context.get('structure'):
            parent_struct = parent_context['structure']
            parent_title = parent_context.get('title', 'parent section')
            context_instruction = f"""
        
        IMPORTANT CONTEXT - You are analyzing a subsection:
        - Parent section: "{parent_title}"
        - Parent structure code: "{parent_struct}"
        
        When extracting child sections within this subsection:
        1. If the document shows EXPLICIT numbering (e.g., "3.1", "3.2"), follow it EXACTLY
        2. If there's NO explicit numbering in the document, use: "{parent_struct}.1", "{parent_struct}.2", "{parent_struct}.3", etc.
        3. For nested children, continue the pattern: "{parent_struct}.1.1", "{parent_struct}.1.2", etc.
        
        Example: If parent is "3" and you see unnumbered sections "Introduction", "Methods", "Results":
        - Extract as: "{parent_struct}.1" Introduction, "{parent_struct}.2" Methods, "{parent_struct}.3" Results
        """
        
        system_prompt = f"""
        Analyze the document content and extract its hierarchical structure.
        {context_instruction}
        
        ⚠️ **CRITICAL RULE - Title Text Integrity**:
        ALL title text MUST be copied EXACTLY as it appears in the PDF.
        DO NOT modify, translate, rewrite, standardize, or correct any heading text.
        Preserve original language, punctuation, typos, and special characters.
        
        IMPORTANT - Only extract section/chapter headings that are:
        1. **Clearly identifiable** as major structural divisions
        2. **Explicitly present** in the text (no inference or guessing)
        3. **Visually prominent** (larger font, bold, numbered, etc.)
        4. **Structural markers** like:
           - Chapter titles (第一章, 第一部分, Chapter 1, Part 1)
           - Major sections (一、二、三 or 1. 2. 3.)
           - Numbered subsections (1.1, 1.2, (1), (2))
        
        CRITICAL PATTERN - Chapter opening pages with subsection lists:
        
        **Pattern Recognition**: If you see a page with this structure:
        1. A chapter/section title at the top (e.g., "第五部分", "Chapter 3", "Part A")
        2. Immediately followed by a compact list with consistent numbering
        3. List items use ANY of these formats:
           - Chinese numbers: 一、二、三、 or （一）（二）（三）
           - Arabic numbers: 1. 2. 3. or 1) 2) 3)
           - Letters: A. B. C. or (a) (b) (c)
           - Roman numerals: I. II. III. or i. ii. iii.
           - Hierarchical: 2.1, 2.2, 2.3
           - Bullets: • ● ○ (if consistently used with section titles)
        4. Minimal or no content between list items (just titles)
        
        **Action**: You MUST extract ALL items in that list as separate structural nodes.
        
        **Example 1** (Chinese numbering):
        ```
        第五部分 投标文件格式
        一、 自查表
        二、 资格文件
        三、 符合性文件
        ```
        → Extract: "5" parent + "5.1" "5.2" "5.3" children
        
        **Example 2** (Arabic numbering):
        ```
        Chapter 3 Requirements
        1. General Scope
        2. Technical Specifications
        3. Quality Standards
        ```
        → Extract: "3" parent + "3.1" "3.2" "3.3" children
        
        **Example 3** (Letter numbering):
        ```
        Appendix B Methods
        A. Data Collection
        B. Analysis Procedure
        C. Validation Process
        ```
        → Extract: "B" parent + "B.1" "B.2" "B.3" children
        
        **Why**: These lists define the document's organizational structure, NOT decorative content.
        Even if all items appear on one page, they are real section headings that will have content later.
        
        **Key principle**: When a parent section explicitly lists its children in a structured format,
        treat each child as a first-class structural node, regardless of numbering style or language.
        
        DO NOT extract:
        - Generic standalone words like "说明" or "内容" without clear context
        - Descriptive paragraph text that is not a heading
        - Data table headers (column names in tables)
        - Repetitive minor clauses or bullet points within content
        
        The content is labeled with <physical_index_X> tags showing page numbers.
        
        Structure code rules:
        - Level 1: "1", "2", "3" (major chapters/parts)
        - Level 2: "1.1", "1.2", "2.1" (sections within chapters)
        - Level 3: "1.1.1", "1.1.2", "2.1.1" (subsections)
        - Level 4: "1.1.1.1", "1.1.1.2" (sub-subsections)
        
        Maximum depth: {self.opt.max_depth}
        
        Return JSON with ONLY clear, significant structural items:
        {{
            "table_of_contents": [
                {{
                    "structure": "1",
                    "title": "Chapter Title",
                    "physical_index": "<physical_index_5>"
                }}
            ]
        }}
        
        Rules:
        - Only extract items that CLEARLY appear in THIS segment
        - ⚠️ **Use exact title text** - copy character-by-character from the PDF without ANY modifications
        - Assign physical_index based on <physical_index_X> tags
        - When you see a parent heading with a structured list of children (any numbering format), ALWAYS extract ALL children
        - Be conservative for paragraph content, but NOT for structured lists following section titles
        """
        
        prompt = f"""
        Extract document structure from this segment:
        
        Document segment (pages {segment['start_page']}-{segment['end_page']}):
        ---
        {segment['content'][:60000]}
        ---
        
        Extract ONLY major sections/subsections that are clearly identifiable as structural headings.
        
        CRITICAL: If you see a section title followed by a structured list (with ANY consistent numbering: 
        一二三, 1.2.3, A.B.C, I.II.III, or bullets), those ARE subsections - extract ALL of them with their full titles.
        
        Be conservative for paragraph text, but aggressive for structured lists under section headings.
        """
        
        try:
            result = await self.llm.chat_json(prompt, system=system_prompt, max_tokens=4000)
            structure = result.get("table_of_contents", [])
            
            if self.debug:
                print(f"  [LLM] Response received: {len(structure)} items")
            
            # Filter by max_depth
            filtered = []
            for item in structure:
                struct_code = item.get('structure', '')
                depth = struct_code.count('.') + 1 if struct_code else 1
                if depth <= self.opt.max_depth:
                    filtered.append(item)
                elif self.debug:
                    print(f"  [FILTER] Skipping '{item.get('title', '')}' (depth {depth} > max {self.opt.max_depth})")
            
            if self.debug and len(filtered) < len(structure):
                print(f"  [FILTER] Filtered to {len(filtered)} items (removed {len(structure) - len(filtered)} too deep)")
            
            return filtered
            
        except Exception as e:
            if self.debug:
                print(f"  [ERROR] Segment structure extraction failed: {e}")
            return []
    
    def _merge_structure_items(self, existing: list, new_items: list) -> list:
        """Merge structure items, avoiding duplicates"""
        # Create lookup by (structure, title)
        existing_keys = {(item.get('structure'), item.get('title')) for item in existing}
        
        merged = existing.copy()
        duplicates = 0
        for item in new_items:
            key = (item.get('structure'), item.get('title'))
            if key not in existing_keys:
                merged.append(item)
                existing_keys.add(key)
            else:
                duplicates += 1
        
        if self.debug and duplicates > 0:
            print(f"  [MERGE] Skipped {duplicates} duplicate items")
        
        return merged
    
    def _convert_embedded_toc_to_structure(self, embedded_toc: List) -> List[Dict[str, Any]]:
        """
        Convert PyMuPDF's get_toc() result to internal structure format with quality filtering.
        
        Improvements:
        - Smart chapter detection: recognize "第X章" patterns as top-level
        - Hierarchy normalization: fix incorrect level assignments
        - Title validation: filter out garbage entries
        
        Args:
            embedded_toc: PyMuPDF TOC list [(level, title, page), ...]
        
        Returns:
            List of structured items (filtered for quality)
        """
        import re
        
        structure = []
        level_counters = {}  # Track counter for each level
        filtered_count = 0
        chapter_counter = 0  # Track chapters separately
        
        for level, title, page in embedded_toc:
            title = title.strip()
            
            # Quality filtering: skip invalid TOC titles
            if not self._is_valid_toc_title(title):
                if self.debug:
                    preview = title[:50] + "..." if len(title) > 50 else title
                    print(f"  [FILTER] Skipping invalid TOC entry: '{preview}'")
                filtered_count += 1
                continue
            
            # OPTIMIZATION 1: Smart chapter detection
            # Recognize common chapter patterns and force them to level 1
            is_chapter = self._is_chapter_title(title)
            
            if is_chapter:
                # Force chapters to be level 1, regardless of embedded level
                original_level = level
                level = 1
                chapter_counter += 1
                
                if self.debug and original_level != 1:
                    print(f"  [NORMALIZE] Promoted '{title}' from L{original_level} to L1 (chapter)")
            
            # Update counters: increment current level, reset deeper levels
            if level not in level_counters:
                level_counters[level] = 0
            level_counters[level] += 1
            
            # Reset deeper level counters
            keys_to_delete = [k for k in level_counters if k > level]
            for k in keys_to_delete:
                del level_counters[k]
            
            # Build structure code (e.g., "1.2.3")
            structure_code_parts = []
            for lv in sorted([k for k in level_counters if k <= level]):
                structure_code_parts.append(str(level_counters[lv]))
            structure_code = ".".join(structure_code_parts)
            
            # Note: Use 'page' field for compatibility with PageMapper
            # Tree builder will convert 'page' to 'start_index'/'end_index'
            structure.append({
                "structure": structure_code,
                "title": title,
                "page": page,  # Physical page number from PDF metadata
                "level": level,  # Keep level for debugging
                "is_chapter": is_chapter  # Mark chapters for post-processing
            })
        
        if self.debug:
            if filtered_count > 0:
                print(f"  [FILTER] Filtered out {filtered_count} invalid TOC entries")
            if chapter_counter > 0:
                print(f"  [CHAPTER] Detected {chapter_counter} chapter(s)")
        
        return structure
    
    def _is_chapter_title(self, title: str) -> bool:
        """
        Detect if a title represents a chapter/main section.
        
        Common Chinese tender document chapter patterns:
        - "第一章 xxx", "第二章 xxx", etc.
        - "第1章 xxx", "第2章 xxx", etc.
        - "Chapter X", "CHAPTER X"
        - Sometimes just "第X章" without following text
        
        Returns:
            True if title is a chapter, False otherwise
        """
        import re
        
        # Pattern 1: 第X章 (Chinese numeral or digit)
        if re.match(r'^第[一二三四五六七八九十0-9]+章', title):
            return True
        
        # Pattern 2: Chapter X / CHAPTER X (English)
        if re.match(r'^(?:chapter|CHAPTER)\s*[0-9IVX]+', title, re.IGNORECASE):
            return True
        
        return False
    
    def _is_valid_toc_title(self, title: str) -> bool:
        """
        Validate if a TOC title looks reasonable and not content fragments.
        
        Filters out:
        - Single characters or very short strings (likely parsing errors)
        - Very long strings (>100 chars, likely content not titles)
        - Sentences with punctuation (content fragments)
        - Form-like entries (e.g., "地    址：", "供应商全称（公章）：")
        - Known garbage patterns
        
        Args:
            title: The TOC title to validate
            
        Returns:
            True if title appears valid, False otherwise
        """
        title = title.strip()
        
        # 1. Length check
        if len(title) <= 1:
            # Single character titles are usually parsing errors
            return False
        
        if len(title) > 80:
            # Titles over 80 characters are likely content fragments
            return False
        
        # 2. Sentence pattern check - content usually has mid-sentence punctuation
        # Chinese punctuation that indicates content (not titles)
        content_indicators = ['。', '，', '！', '？']
        if any(p in title for p in content_indicators):
            # Exception: Some legitimate title formats exist like "（一）适用范围"
            # These typically start with specific patterns
            legitimate_prefixes = ['第', '（', '(', '附件', '表', '图']
            if not any(title.startswith(prefix) for prefix in legitimate_prefixes):
                return False
        
        # 3. Check for known garbage patterns (single repeated characters)
        single_char_words = ['报', '价', '文', '件', '供', '应', '商', '称', '章']
        if title in single_char_words:
            return False
        
        # 4. Check if title is just punctuation or special characters
        if all(not c.isalnum() for c in title):
            return False
        
        # 5. Filter out form-like entries (lines with colons and spaces indicating form fields)
        # Examples: "地    址：", "供应商全称（公章）：", "时    间："
        # These have colon at end and multiple spaces or look like form labels
        if title.endswith('：') or title.endswith(':'):
            # Check if it looks like a form field label (has multiple spaces or contains form keywords)
            form_keywords = ['地址', '时间', '日期', '名称', '公章', '签字', '盖章', '电话', '传真', '邮编']
            has_form_keyword = any(kw in title for kw in form_keywords)
            has_multiple_spaces = '  ' in title  # Two or more consecutive spaces
            
            if has_form_keyword or has_multiple_spaces:
                return False
        
        # 6. Filter entries that start with single letters (usually list markers from content)
        # Examples: "G.存在共同直接或间接投资..."
        if len(title) > 2 and title[0].isalpha() and title[1] == '.':
            # Exception: legitimate chapter formats like "A.附录"
            if not any(title[2:].strip().startswith(prefix) for prefix in ['附', '补', '表', '图']):
                return False
        
        return True
    
    async def _process_large_node_recursively(
        self,
        node: Dict,
        all_pages: List[PDFPage]
    ) -> Dict:
        """
        Recursively process large nodes by extracting sub-structure.
        
        If a node covers too many pages or tokens, re-extract its internal structure
        and attach as child nodes. This follows the PageIndex v1 strategy for large PDFs.
        
        Args:
            node: Node dictionary with start_index, end_index, title
            all_pages: All PDF pages (for reference)
        
        Returns:
            Updated node with 'nodes' field containing children
        """
        start = node.get('start_index')
        end = node.get('end_index')
        
        if not start or not end:
            return node
        
        # Get pages for this node
        node_pages = all_pages[start-1:end]
        page_count = len(node_pages)
        token_count = sum(p.tokens for p in node_pages)
        
        # Check if node is large enough to warrant recursive processing
        # Use OR logic: trigger if EITHER condition is met
        is_large = (
            page_count > self.opt.max_pages_per_node or
            token_count > self.opt.max_tokens_per_node
        )
        
        if not is_large:
            # Node is small enough, process children if any
            if 'nodes' in node and node['nodes']:
                tasks = [
                    self._process_large_node_recursively(child, all_pages)
                    for child in node['nodes']
                ]
                node['nodes'] = await asyncio.gather(*tasks)
            return node
        
        # Node is large - extract sub-structure
        if self.debug:
            print(f"\n[RECURSIVE] Processing large node:")
            print(f"  Title: {node['title'][:60]}...")
            print(f"  Pages: {start}-{end} ({page_count} pages)")
            print(f"  Tokens: {token_count:,}")
        
        # Extract sub-structure from this node's pages
        # Pass parent context to maintain structure numbering continuity
        parent_context = {
            'structure': node.get('structure', ''),
            'title': node.get('title', '')
        }
        sub_structure = await self._generate_structure_from_content(node_pages, parent_context=parent_context)
        
        if not sub_structure:
            if self.debug:
                print(f"  ⚠ No sub-structure extracted")
            return node
        
        # Map pages for sub-structure
        # The sub_structure has <physical_index_X> tags, need to convert to integers
        from .utils.helpers import convert_physical_index_to_int
        sub_structure = convert_physical_index_to_int(sub_structure)
        
        if self.debug:
            converted_count = sum(1 for item in sub_structure if isinstance(item.get('physical_index'), int))
            print(f"  [RECURSIVE] Converted {converted_count}/{len(sub_structure)} physical_index tags to integers")
        
        # Verify sub-structure (limited to this node's pages)
        if self.debug:
            print(f"  [RECURSIVE] Verifying {len(sub_structure)} sub-items...")
        
        # Calculate page offset: node_pages is a subset starting at global page 'start'
        page_offset = start - 1  # start is 1-indexed, offset is for 0-indexed array
        
        verifier = Verifier(self.llm, debug=self.debug)  # Use same debug setting
        verified_sub, accuracy = await verifier.verify_structure(sub_structure, node_pages, page_offset)
        
        if self.debug:
            print(f"  [RECURSIVE] Verification accuracy: {accuracy:.1%}")
        
        # Fix incorrect items if needed
        if accuracy < 0.8:
            incorrect = [v for v in verified_sub if not v.get('verification_passed')]
            if incorrect:
                if self.debug:
                    print(f"  [RECURSIVE] Fixing {len(incorrect)} incorrect sub-items...")
                fixed = await verifier.fix_incorrect_items(verified_sub, incorrect, node_pages, page_offset=page_offset)
                verified_sub = fixed
        
        # Build tree for sub-structure
        builder = TreeBuilder(debug=self.debug)  # Use same debug setting
        sub_tree = builder.build_tree(verified_sub, node_pages)
        
        if self.debug:
            print(f"  ✓ Extracted {len(sub_tree)} child nodes")
        
        # Handle title duplication: if first child has same title as parent, skip it
        # This happens when LLM extracts the parent's title page as a separate child node
        if sub_tree and len(sub_tree) > 0:
            parent_title = node.get('title', '').strip().lower()
            first_child_title = sub_tree[0].get('title', '').strip().lower()
            
            # Case insensitive comparison for better matching
            if parent_title and first_child_title and parent_title == first_child_title:
                if self.debug:
                    print(f"  [DEDUP] Removing duplicate child with same title as parent: '{sub_tree[0].get('title', '')[:50]}...'")
                # Skip first child and use only remaining children
                sub_tree = sub_tree[1:]
                if self.debug:
                    print(f"  [DEDUP] Remaining children: {len(sub_tree)}")
        
        # If no children remain after deduplication, don't attach empty list
        if not sub_tree:
            if self.debug:
                print(f"  [DEDUP] No children remain after deduplication, keeping node as leaf")
            return node
        
        # Attach sub-tree as children
        node['nodes'] = sub_tree
        
        # Recursively process children first
        tasks = [
            self._process_large_node_recursively(child, all_pages)
            for child in node['nodes']
        ]
        node['nodes'] = await asyncio.gather(*tasks)
        
        # Update node's end_index to last child's end (parent contains all children)
        # Do this AFTER recursive processing, as children may have updated their end_index
        if node['nodes'] and node['nodes'][-1].get('end_index'):
            node['end_index'] = node['nodes'][-1]['end_index']
        
        return node


async def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='PageIndex V2 - Document Structure Extractor')
    parser.add_argument('pdf_path', help='Path to PDF file')
    parser.add_argument('--provider', default='deepseek', choices=['deepseek', 'openai'],
                        help='LLM provider')
    parser.add_argument('--model', default='deepseek-chat', help='Model name')
    parser.add_argument('--max-depth', type=int, default=4, help='Maximum tree depth')
    parser.add_argument('--toc-check-pages', type=int, default=20, 
                        help='Pages to check for TOC')
    parser.add_argument('--output-dir', default='./results', help='Output directory')
    parser.add_argument('--quiet', action='store_true', help='Disable debug output')
    parser.add_argument('--no-progress', action='store_true', help='Disable progress output (only show final result)')
    
    # Large PDF optimization parameters
    parser.add_argument('--no-recursive', action='store_true',
                        help='Disable recursive large node processing')
    parser.add_argument('--force-verification', action='store_true',
                        help='Force verification even for large PDFs')
    parser.add_argument('--large-pdf-threshold', type=int, default=200,
                        help='Page threshold to consider as large PDF (default: 200)')
    parser.add_argument('--max-pages-per-node', type=int, default=15,
                        help='Max pages per node before recursive processing (default: 15)')
    
    # Phase 5 verification optimization parameters
    parser.add_argument('--max-verify-count', type=int, default=100,
                        help='Maximum nodes to verify (default: 100, lower=faster)')
    parser.add_argument('--verification-concurrency', type=int, default=20,
                        help='Concurrent LLM calls during verification (default: 20, higher=faster but more API load)')
    
    args = parser.parse_args()
    
    options = ProcessingOptions(
        provider=args.provider,
        model=args.model,
        max_depth=args.max_depth,
        toc_check_pages=args.toc_check_pages,
        debug=not args.quiet,
        progress=not args.no_progress,
        output_dir=args.output_dir,
        enable_recursive_processing=not args.no_recursive,
        skip_verification_for_large_pdf=not args.force_verification,
        large_pdf_threshold=args.large_pdf_threshold,
        max_pages_per_node=args.max_pages_per_node,
        max_verify_count=args.max_verify_count,
        verification_concurrency=args.verification_concurrency
    )
    
    try:
        processor = PageIndexV2(options)
        result = await processor.process_pdf(args.pdf_path)
        
        if not options.debug:
            # Print minimal output in quiet mode
            print(json.dumps(result['statistics'], indent=2))
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
