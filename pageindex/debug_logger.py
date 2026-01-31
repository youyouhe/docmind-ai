"""
Debug logger for PDF parsing algorithm diagnostics.
Logs detailed information about each step of the processing pipeline.
"""
import os
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


class DebugLogger:
    """
    Detailed debug logger for PDF parsing algorithm.
    
    Logs all intermediate steps to help diagnose parsing issues:
    - TOC detection
    - Structure extraction  
    - Page index assignment
    - Content allocation
    - Title validation
    """
    
    def __init__(self, output_dir: str, document_id: str):
        """
        Initialize debug logger.
        
        Args:
            output_dir: Directory to save log files
            document_id: Unique document identifier
        """
        self.output_dir = output_dir
        self.document_id = document_id
        self.start_time = time.time()
        
        # Create output directory if needed
        os.makedirs(output_dir, exist_ok=True)
        
        # Log file paths
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(output_dir, f"{document_id}_debug_{timestamp}.log")
        self.json_file = os.path.join(output_dir, f"{document_id}_debug_{timestamp}.json")
        
        # Structured log data
        self.log_data = {
            "document_id": document_id,
            "timestamp": timestamp,
            "stages": {}
        }
        
        # Write initial log
        self._write_log(f"="*80)
        self._write_log(f"Debug Log Started: {timestamp}")
        self._write_log(f"Document ID: {document_id}")
        self._write_log(f"="*80 + "\n")
    
    def _write_log(self, message: str):
        """Write message to log file."""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{message}\n")
    
    def _elapsed_time(self) -> str:
        """Get elapsed time since logger creation."""
        elapsed = time.time() - self.start_time
        return f"{elapsed:.2f}s"
    
    def log_stage(self, stage_name: str, message: str, data: Optional[Dict] = None):
        """
        Log a processing stage.
        
        Args:
            stage_name: Name of the stage (e.g., "toc_detection")
            message: Human-readable message
            data: Optional structured data to log
        """
        timestamp = self._elapsed_time()
        
        # Write to text log
        self._write_log(f"\n[{timestamp}] {stage_name.upper()}")
        self._write_log(f"{'-'*80}")
        self._write_log(message)
        
        if data:
            self._write_log(f"\nData:")
            for key, value in data.items():
                if isinstance(value, (list, dict)):
                    self._write_log(f"  {key}: (see JSON log)")
                else:
                    self._write_log(f"  {key}: {value}")
        
        # Add to structured log
        if stage_name not in self.log_data["stages"]:
            self.log_data["stages"][stage_name] = []
        
        self.log_data["stages"][stage_name].append({
            "timestamp": timestamp,
            "message": message,
            "data": data
        })
    
    def log_toc_detection(self, page_list: List, toc_result: Dict):
        """Log TOC detection results."""
        has_toc = toc_result.get("toc_content") and toc_result.get("page_index_given_in_toc") == "yes"
        
        data = {
            "total_pages": len(page_list),
            "has_toc": has_toc,
            "toc_pages": toc_result.get("toc_page_list", []),
            "has_page_numbers": toc_result.get("page_index_given_in_toc") == "yes",
            "toc_content_length": len(toc_result.get("toc_content", "")) if toc_result.get("toc_content") else 0
        }
        
        if has_toc:
            message = f"TOC detected on pages {toc_result['toc_page_list']} with page numbers"
        else:
            message = "No TOC detected - will auto-generate structure"
        
        self.log_stage("toc_detection", message, data)
    
    def log_structure_extraction(self, toc_items: List[Dict], mode: str):
        """Log structure extraction results."""
        data = {
            "mode": mode,
            "total_items": len(toc_items),
            "items_with_page": sum(1 for item in toc_items if item.get('physical_index') is not None),
            "items_without_page": sum(1 for item in toc_items if item.get('physical_index') is None),
            "sample_items": toc_items[:5] if len(toc_items) > 0 else []
        }
        
        # Analyze structure distribution
        structures = {}
        for item in toc_items:
            struct = str(item.get('structure', 'None'))
            level = struct.count('.') + 1 if struct != 'None' else 0
            structures[level] = structures.get(level, 0) + 1
        
        data["structure_distribution"] = structures
        
        message = f"Extracted {len(toc_items)} structure items using mode: {mode}"
        self.log_stage("structure_extraction", message, data)
        
        # Log each item details
        self._write_log(f"\nAll extracted items:")
        for i, item in enumerate(toc_items, 1):
            self._write_log(f"  {i:3d}. [{item.get('structure', 'N/A'):8s}] {item.get('title', 'N/A')[:60]:60s} -> Page {item.get('physical_index', 'N/A')}")
    
    def log_title_validation(self, validation_results: List[Dict]):
        """Log title appearance validation results."""
        confirmed = sum(1 for r in validation_results if r.get('appear_start') == 'yes')
        total = len(validation_results)
        
        data = {
            "total_validated": total,
            "confirmed": confirmed,
            "rejected": total - confirmed,
            "confirmation_rate": f"{confirmed/total*100:.1f}%" if total > 0 else "0%"
        }
        
        message = f"Title validation: {confirmed}/{total} titles confirmed ({data['confirmation_rate']})"
        self.log_stage("title_validation", message, data)
        
        # Log failed validations
        failed = [r for r in validation_results if r.get('appear_start') != 'yes']
        if failed:
            self._write_log(f"\nFailed validations ({len(failed)}):")
            for item in failed[:20]:  # Show first 20
                self._write_log(f"  - {item.get('title', 'N/A')[:60]} @ Page {item.get('physical_index', 'N/A')}")
    
    def log_tree_building(self, tree: Dict, page_count: int):
        """Log tree structure building results."""
        from pageindex.utils import structure_to_list
        
        all_nodes = structure_to_list(tree)
        
        # Calculate depth
        def calc_depth(node, d=0):
            if not node.get('nodes'):
                return d
            return max(calc_depth(child, d+1) for child in node['nodes'])
        
        max_depth = max((calc_depth(node) for node in tree), default=0)
        
        # Analyze page ranges
        page_ranges = []
        content_issues = []
        
        for node in all_nodes:
            start = node.get('start_index')
            end = node.get('end_index')
            title = node.get('title', 'Unknown')[:40]
            
            if start and end:
                pages = end - start + 1
                page_ranges.append(pages)
                
                # Check for issues
                if start == end == page_count:
                    content_issues.append(f"'{title}' assigned to last page only")
                elif start > end:
                    content_issues.append(f"'{title}' has invalid range: {start}-{end}")
        
        data = {
            "total_nodes": len(all_nodes),
            "max_depth": max_depth,
            "total_pages": page_count,
            "avg_pages_per_node": sum(page_ranges)/len(page_ranges) if page_ranges else 0,
            "min_pages": min(page_ranges) if page_ranges else 0,
            "max_pages": max(page_ranges) if page_ranges else 0,
            "content_issues_count": len(content_issues)
        }
        
        message = f"Tree built: {len(all_nodes)} nodes, depth {max_depth}"
        self.log_stage("tree_building", message, data)
        
        # Log issues
        if content_issues:
            self._write_log(f"\n⚠️  Content Assignment Issues ({len(content_issues)}):")
            for issue in content_issues[:20]:
                self._write_log(f"  - {issue}")
        
        # Log node details
        self._write_log(f"\nNode details:")
        for i, node in enumerate(all_nodes[:30], 1):  # Show first 30
            start = node.get('start_index', 'N/A')
            end = node.get('end_index', 'N/A')
            title = node.get('title', 'Unknown')[:50]
            level = node.get('level', 0)
            
            indent = "  " * level
            self._write_log(f"  {i:3d}. {indent}[L{level}] {title:50s} Pages: {start}-{end}")
    
    def log_content_allocation(self, node: Dict, page_list: List):
        """Log content allocation for a specific node."""
        start = node.get('start_index')
        end = node.get('end_index')
        title = node.get('title', 'Unknown')
        content_length = len(node.get('content', ''))
        
        data = {
            "title": title[:60],
            "start_page": start,
            "end_page": end,
            "page_count": end - start + 1 if start and end else 0,
            "content_length": content_length,
            "has_content": content_length > 0
        }
        
        # Check if content is unique or duplicated
        if content_length > 100:
            content_snippet = node.get('content', '')[:100]
            data["content_snippet"] = content_snippet
        
        self.log_stage("content_allocation", f"Content allocated to: {title[:60]}", data)
    
    def log_issue(self, issue_type: str, message: str, details: Optional[Dict] = None):
        """Log a specific issue found during processing."""
        self._write_log(f"\n⚠️  ISSUE ({issue_type}):")
        self._write_log(f"  {message}")
        
        if details:
            for key, value in details.items():
                self._write_log(f"  {key}: {value}")
    
    def finalize(self):
        """Finalize and save debug log."""
        elapsed = self._elapsed_time()
        
        self._write_log(f"\n{'='*80}")
        self._write_log(f"Debug Log Completed")
        self._write_log(f"Total Time: {elapsed}")
        self._write_log(f"{'='*80}")
        
        # Save structured JSON log
        self.log_data["total_time"] = elapsed
        with open(self.json_file, 'w', encoding='utf-8') as f:
            json.dump(self.log_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[DEBUG] Log saved to: {self.log_file}")
        print(f"[DEBUG] JSON log saved to: {self.json_file}")


# Global logger instance
_debug_logger: Optional[DebugLogger] = None


def init_debug_logger(output_dir: str, document_id: str) -> DebugLogger:
    """Initialize global debug logger."""
    global _debug_logger
    _debug_logger = DebugLogger(output_dir, document_id)
    return _debug_logger


def get_debug_logger() -> Optional[DebugLogger]:
    """Get current debug logger instance."""
    return _debug_logger


def finalize_debug_logger():
    """Finalize and cleanup debug logger."""
    global _debug_logger
    if _debug_logger:
        _debug_logger.finalize()
        _debug_logger = None
