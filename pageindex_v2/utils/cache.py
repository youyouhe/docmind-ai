"""
PDF Processing Cache System
Saves expensive operations (PDF parsing, TOC detection, structure extraction) to disk
"""
import json
import hashlib
import pickle
from pathlib import Path
from typing import Optional, Dict, Any, List


class ProcessingCache:
    """
    Cache system for PDF processing results
    
    Cache structure:
    .cache/
        {pdf_hash}/
            pdf_pages.pkl          # Phase 1: Parsed pages
            toc_detection.json     # Phase 2: TOC pages and info
            toc_structure.json     # Phase 3: Extracted structure
            metadata.json          # Cache metadata
    """
    
    def __init__(self, cache_dir: str = ".cache", enabled: bool = True):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        
        if self.enabled:
            self.cache_dir.mkdir(exist_ok=True)
    
    def _get_pdf_hash(self, pdf_path: str) -> str:
        """Get PDF file hash for cache key"""
        pdf_path_obj = Path(pdf_path)
        
        # Use file path + size + mtime for quick hash
        # (faster than hashing entire file content)
        stat = pdf_path_obj.stat()
        hash_input = f"{pdf_path_obj.absolute()}:{stat.st_size}:{stat.st_mtime}"
        
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def _get_cache_path(self, pdf_path: str) -> Path:
        """Get cache directory for a specific PDF"""
        pdf_hash = self._get_pdf_hash(pdf_path)
        cache_path = self.cache_dir / pdf_hash
        
        if self.enabled:
            cache_path.mkdir(exist_ok=True)
        
        return cache_path
    
    # Phase 1: PDF Pages Cache
    
    def get_pages(self, pdf_path: str) -> Optional[List]:
        """Load cached parsed pages"""
        if not self.enabled:
            return None
        
        cache_path = self._get_cache_path(pdf_path)
        pages_file = cache_path / "pdf_pages.pkl"
        
        if pages_file.exists():
            try:
                with open(pages_file, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"[CACHE] Failed to load pages cache: {e}")
                return None
        
        return None
    
    def save_pages(self, pdf_path: str, pages: List):
        """Save parsed pages to cache"""
        if not self.enabled:
            return
        
        cache_path = self._get_cache_path(pdf_path)
        pages_file = cache_path / "pdf_pages.pkl"
        
        try:
            with open(pages_file, 'wb') as f:
                pickle.dump(pages, f)
            print(f"[CACHE] Saved {len(pages)} pages to cache")
        except Exception as e:
            print(f"[CACHE] Failed to save pages: {e}")
    
    # Phase 2: TOC Detection Cache
    
    def get_toc_detection(self, pdf_path: str) -> Optional[Dict[str, Any]]:
        """Load cached TOC detection results"""
        if not self.enabled:
            return None
        
        cache_path = self._get_cache_path(pdf_path)
        toc_file = cache_path / "toc_detection.json"
        
        if toc_file.exists():
            try:
                with open(toc_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[CACHE] Failed to load TOC detection cache: {e}")
                return None
        
        return None
    
    def save_toc_detection(self, pdf_path: str, toc_detection: Dict[str, Any]):
        """Save TOC detection results to cache"""
        if not self.enabled:
            return
        
        cache_path = self._get_cache_path(pdf_path)
        toc_file = cache_path / "toc_detection.json"
        
        try:
            with open(toc_file, 'w', encoding='utf-8') as f:
                json.dump(toc_detection, f, indent=2, ensure_ascii=False)
            
            toc_pages = toc_detection.get('toc_pages', [])
            print(f"[CACHE] Saved TOC detection ({len(toc_pages)} pages) to cache")
        except Exception as e:
            print(f"[CACHE] Failed to save TOC detection: {e}")
    
    # Phase 3: Structure Cache
    
    def get_structure(self, pdf_path: str) -> Optional[List[Dict]]:
        """Load cached TOC structure"""
        if not self.enabled:
            return None
        
        cache_path = self._get_cache_path(pdf_path)
        structure_file = cache_path / "toc_structure.json"
        
        if structure_file.exists():
            try:
                with open(structure_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[CACHE] Failed to load structure cache: {e}")
                return None
        
        return None
    
    def save_structure(self, pdf_path: str, structure: List[Dict]):
        """Save TOC structure to cache"""
        if not self.enabled:
            return
        
        cache_path = self._get_cache_path(pdf_path)
        structure_file = cache_path / "toc_structure.json"
        
        try:
            with open(structure_file, 'w', encoding='utf-8') as f:
                json.dump(structure, f, indent=2, ensure_ascii=False)
            
            print(f"[CACHE] Saved structure ({len(structure)} items) to cache")
        except Exception as e:
            print(f"[CACHE] Failed to save structure: {e}")
    
    # Metadata
    
    def save_metadata(self, pdf_path: str, metadata: Dict[str, Any]):
        """Save processing metadata"""
        if not self.enabled:
            return
        
        cache_path = self._get_cache_path(pdf_path)
        meta_file = cache_path / "metadata.json"
        
        try:
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CACHE] Failed to save metadata: {e}")
    
    def get_metadata(self, pdf_path: str) -> Optional[Dict[str, Any]]:
        """Load processing metadata"""
        if not self.enabled:
            return None
        
        cache_path = self._get_cache_path(pdf_path)
        meta_file = cache_path / "metadata.json"
        
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return None
        
        return None
    
    # Utility
    
    def clear_cache(self, pdf_path: Optional[str] = None):
        """Clear cache for specific PDF or all PDFs"""
        if not self.enabled:
            return
        
        if pdf_path:
            # Clear specific PDF cache
            cache_path = self._get_cache_path(pdf_path)
            if cache_path.exists():
                import shutil
                shutil.rmtree(cache_path)
                print(f"[CACHE] Cleared cache for {pdf_path}")
        else:
            # Clear all caches
            if self.cache_dir.exists():
                import shutil
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(exist_ok=True)
                print("[CACHE] Cleared all caches")
    
    def get_cache_info(self, pdf_path: str) -> Dict[str, Any]:
        """Get information about cached data"""
        cache_path = self._get_cache_path(pdf_path)
        
        info = {
            'cache_exists': cache_path.exists(),
            'cache_path': str(cache_path),
            'cached_phases': []
        }
        
        if cache_path.exists():
            if (cache_path / "pdf_pages.pkl").exists():
                info['cached_phases'].append('Phase 1: PDF Parsing')
            if (cache_path / "toc_detection.json").exists():
                info['cached_phases'].append('Phase 2: TOC Detection')
            if (cache_path / "toc_structure.json").exists():
                info['cached_phases'].append('Phase 3: Structure Extraction')
        
        return info
