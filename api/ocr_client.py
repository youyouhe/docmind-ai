"""
OCR Service Client for docmind-ai.
Communicates with the standalone DeepSeek-OCR-2 service via HTTP.
Handles scanned PDF detection, page-to-image conversion, and result caching.
"""
import os
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Callable

import fitz  # PyMuPDF
import requests

logger = logging.getLogger("pageindex.api.ocr_client")


class OCRClient:
    """Client for the DeepSeek-OCR-2 microservice."""

    def __init__(self, service_url: Optional[str] = None, cache_dir: Optional[Path] = None):
        self.service_url = (
            service_url or os.getenv("OCR_SERVICE_URL", "")
        ).rstrip("/")
        self.enabled = bool(self.service_url)

        # Cache directory: data/ocr_cache/
        if cache_dir is None:
            data_dir = Path(__file__).resolve().parent.parent / "data"
            cache_dir = data_dir / "ocr_cache"
        self.cache_dir = cache_dir
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        """Check if OCR service is configured and healthy."""
        if not self.enabled:
            return False
        try:
            resp = requests.get(f"{self.service_url}/health", timeout=5)
            return resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception:
            return False

    # -----------------------------------------------------------------
    # Scanned PDF Detection
    # -----------------------------------------------------------------

    def is_scanned_pdf(self, pdf_path: str, sample_pages: int = 5) -> bool:
        """
        Detect whether a PDF is scanned (image-based) vs. text-based.

        Strategy: sample up to `sample_pages` pages. If ALL sampled pages
        have <50 chars of text AND have embedded images, classify as scanned.
        """
        doc = fitz.open(pdf_path)
        total = len(doc)
        check_count = min(sample_pages, total)

        scanned_count = 0
        for i in range(check_count):
            page = doc.load_page(i)
            text = page.get_text("text").strip()
            images = page.get_images(full=True)

            if len(text) < 50 and len(images) > 0:
                scanned_count += 1

        doc.close()
        return scanned_count == check_count and check_count > 0

    # -----------------------------------------------------------------
    # OCR Processing
    # -----------------------------------------------------------------

    def ocr_page(self, pdf_path: str, page_number: int) -> str:
        """
        OCR a single page. Returns markdown text.
        Uses cache if available; otherwise calls the OCR service.
        """
        # Check cache first
        cached = self._get_cached_page(pdf_path, page_number)
        if cached is not None:
            return cached

        # Convert page to image (300 DPI for quality)
        doc = fitz.open(pdf_path)
        page = doc.load_page(page_number - 1)  # 0-indexed
        pix = page.get_pixmap(dpi=300)
        img_path = tempfile.mktemp(suffix=".png")
        pix.save(img_path)
        doc.close()

        try:
            with open(img_path, "rb") as f:
                resp = requests.post(
                    f"{self.service_url}/ocr/page",
                    files={"image": ("page.png", f, "image/png")},
                    data={"page_number": page_number},
                    timeout=120,
                )

            if resp.status_code != 200:
                logger.error(f"OCR service returned {resp.status_code}: {resp.text}")
                return ""

            result = resp.json()
            if not result.get("success", False):
                logger.error(f"OCR failed for page {page_number}: {result.get('error')}")
                return ""

            md_text = result.get("markdown_text", "")
            self._cache_page(pdf_path, page_number, md_text)
            return md_text

        except requests.exceptions.Timeout:
            logger.error(f"OCR request timed out for page {page_number}")
            return ""
        except Exception as e:
            logger.error(f"OCR request failed for page {page_number}: {e}")
            return ""
        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)

    def ocr_pages(
        self,
        pdf_path: str,
        page_start: int,
        page_end: int,
        progress_callback: Optional[Callable[[int, float], None]] = None,
    ) -> List[Tuple[int, str]]:
        """
        OCR a range of pages. Returns list of (page_number, markdown_text).
        """
        results = []
        total = page_end - page_start + 1

        for i, page_num in enumerate(range(page_start, page_end + 1)):
            md_text = self.ocr_page(pdf_path, page_num)
            results.append((page_num, md_text))

            if progress_callback:
                progress = (i + 1) / total * 100
                progress_callback(page_num, progress)

        return results

    # -----------------------------------------------------------------
    # Cache Management
    # -----------------------------------------------------------------

    def _get_cache_key(self, pdf_path: str) -> str:
        """
        Generate cache key from PDF content hash (size + first 8KB SHA256).

        Uses content-based hashing so that the same PDF re-uploaded under a
        different filename / document-ID still hits the cache.
        """
        stat = os.stat(pdf_path)
        with open(pdf_path, "rb") as f:
            head = f.read(8192)
        content_hash = hashlib.sha256(head).hexdigest()
        raw = f"{stat.st_size}_{content_hash}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cache_path(self, pdf_path: str) -> Path:
        """Get cache directory for a specific PDF."""
        key = self._get_cache_key(pdf_path)
        return self.cache_dir / key

    def _get_cached_page(self, pdf_path: str, page_number: int) -> Optional[str]:
        """Get cached OCR result for a page. Returns None if not cached."""
        cache_file = self._get_cache_path(pdf_path) / f"page_{page_number}.md"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
        return None

    def _cache_page(self, pdf_path: str, page_number: int, text: str):
        """Cache OCR result for a page."""
        cache_dir = self._get_cache_path(pdf_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"page_{page_number}.md"
        cache_file.write_text(text, encoding="utf-8")

    def has_cached_ocr(self, pdf_path: str) -> bool:
        """Check if any OCR cache exists for this PDF."""
        cache_dir = self._get_cache_path(pdf_path)
        return cache_dir.exists() and any(cache_dir.glob("page_*.md"))

    def get_cached_page_count(self, pdf_path: str) -> int:
        """Return the number of cached OCR pages for this PDF."""
        cache_dir = self._get_cache_path(pdf_path)
        if not cache_dir.exists():
            return 0
        return len(list(cache_dir.glob("page_*.md")))

    def clear_cache(self, pdf_path: str):
        """Clear OCR cache for a specific PDF."""
        import shutil

        cache_dir = self._get_cache_path(pdf_path)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
