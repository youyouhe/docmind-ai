"""
DeepSeek-OCR-2 Microservice
Runs as a separate process on a configurable port (default 8010) with GPU access.
"""
import os
import logging
import tempfile
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("ocr_service")

app = FastAPI(title="DeepSeek-OCR-2 Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine (loaded once at startup)
engine = None


@app.on_event("startup")
async def startup():
    global engine
    from ocr_engine import OCREngine

    logger.info("Loading DeepSeek-OCR-2 model...")
    engine = OCREngine(
        model_name=os.getenv("OCR_MODEL", "deepseek-ai/DeepSeek-OCR-2"),
        base_size=int(os.getenv("OCR_BASE_SIZE", "1024")),
        image_size=int(os.getenv("OCR_IMAGE_SIZE", "768")),
    )
    logger.info("Model loaded successfully.")


class OCRPageResponse(BaseModel):
    page_number: int
    markdown_text: str
    success: bool
    error: Optional[str] = None


@app.get("/health")
async def health():
    """Health check — confirms model is loaded and GPU is available."""
    return {
        "status": "healthy" if engine and engine.is_ready() else "unhealthy",
        "model": engine.model_name if engine else None,
        "gpu_available": engine.gpu_available if engine else False,
    }


@app.post("/ocr/page", response_model=OCRPageResponse)
async def ocr_page(
    image: UploadFile = File(..., description="Page image (JPEG/PNG)"),
    page_number: int = Form(1, description="Page number (1-based)"),
):
    """
    OCR a single page image and return markdown text.
    """
    if engine is None or not engine.is_ready():
        raise HTTPException(status_code=503, detail="OCR model not loaded")

    suffix = ".jpg" if "jpeg" in (image.content_type or "") else ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await image.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        markdown_text = engine.process_image(tmp_path)
        return OCRPageResponse(
            page_number=page_number,
            markdown_text=markdown_text,
            success=True,
        )
    except Exception as e:
        logger.error(f"OCR failed for page {page_number}: {e}")
        return OCRPageResponse(
            page_number=page_number,
            markdown_text="",
            success=False,
            error=str(e),
        )
    finally:
        os.unlink(tmp_path)


@app.post("/ocr/pdf")
async def ocr_pdf(
    pdf: UploadFile = File(..., description="PDF file to OCR"),
    page_start: int = Form(1),
    page_end: int = Form(-1, description="-1 means all pages"),
):
    """
    OCR multiple pages of a PDF. Converts each page to image internally,
    runs OCR, and returns a list of results.
    """
    if engine is None or not engine.is_ready():
        raise HTTPException(status_code=503, detail="OCR model not loaded")

    import fitz  # PyMuPDF

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await pdf.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc = fitz.open(tmp_path)
        total_pages = len(doc)
        end = total_pages if page_end == -1 else min(page_end, total_pages)

        results = []
        for page_idx in range(page_start - 1, end):
            page = doc.load_page(page_idx)
            pix = page.get_pixmap(dpi=300)
            img_path = tempfile.mktemp(suffix=".png")
            pix.save(img_path)

            try:
                md_text = engine.process_image(img_path)
                results.append({
                    "page_number": page_idx + 1,
                    "markdown_text": md_text,
                    "success": True,
                })
            except Exception as e:
                results.append({
                    "page_number": page_idx + 1,
                    "markdown_text": "",
                    "success": False,
                    "error": str(e),
                })
            finally:
                os.unlink(img_path)

        doc.close()
        return {"total_pages": total_pages, "pages": results}

    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("OCR_PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port)
