"""
DeepSeek-OCR-2 inference engine.
Manages model loading and per-image inference.
"""
import os
import re
import logging
import tempfile
import torch
from typing import Optional

logger = logging.getLogger("ocr_engine")


class OCREngine:
    def __init__(
        self,
        model_name: str = "deepseek-ai/DeepSeek-OCR-2",
        base_size: int = 1024,
        image_size: int = 768,
    ):
        self.model_name = model_name
        self.base_size = base_size
        self.image_size = image_size
        self.model = None
        self.tokenizer = None
        self.gpu_available = torch.cuda.is_available()
        self._load_model()

    def _load_model(self):
        from transformers import AutoModel, AutoTokenizer

        logger.info(f"Loading model: {self.model_name}")
        logger.info(f"GPU available: {self.gpu_available}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, trust_remote_code=True
        )

        # Prefer flash_attention_2 but fall back to eager if not installed
        # Note: DeepseekOCR2ForCausalLM does not support sdpa, so we use eager
        attn_impl = "flash_attention_2"
        try:
            import flash_attn  # noqa: F401
            logger.info("flash-attn available, using flash_attention_2")
        except ImportError:
            attn_impl = "eager"
            logger.warning(
                "flash-attn not installed, falling back to '%s'. "
                "Install flash-attn for better performance: pip install flash-attn",
                attn_impl,
            )

        self.model = AutoModel.from_pretrained(
            self.model_name,
            _attn_implementation=attn_impl,
            trust_remote_code=True,
            use_safetensors=True,
        )
        self.model = self.model.eval().cuda().to(torch.bfloat16)

        # Ensure pad_token_id is set to suppress generation warnings
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
        if self.model.config.pad_token_id is None:
            self.model.config.pad_token_id = self.tokenizer.eos_token_id

        logger.info("Model loaded and moved to GPU (BF16), attn=%s.", attn_impl)

    def is_ready(self) -> bool:
        return self.model is not None and self.tokenizer is not None

    @staticmethod
    def _clean_grounding_tags(text: str) -> str:
        """Strip grounding coordinate tags from model output."""
        # Remove <|ref|>...<|/ref|> and <|det|>...<|/det|> tags
        text = re.sub(r'<\|ref\|>.*?<\|/ref\|>', '', text)
        text = re.sub(r'<\|det\|>.*?<\|/det\|>', '', text)
        # Collapse multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def process_image(self, image_path: str) -> str:
        """
        Run OCR on a single image, returning markdown text.
        Uses crop_mode=True for document-to-markdown conversion.
        """
        # Use plain OCR prompt without <|grounding|> to avoid coordinate tags in output
        prompt = "<image>\nConvert the document to markdown. "
        # model.infer() requires a valid output_path (it calls os.makedirs unconditionally)
        tmp_output = tempfile.mkdtemp(prefix="ocr_out_")
        try:
            result = self.model.infer(
                self.tokenizer,
                prompt=prompt,
                image_file=image_path,
                output_path=tmp_output,
                base_size=self.base_size,
                image_size=self.image_size,
                crop_mode=True,
                save_results=False,
                eval_mode=True,
            )
            if isinstance(result, list):
                text = "\n".join(str(r) for r in result)
            else:
                text = str(result)
            # Clean any remaining grounding tags (defensive)
            return self._clean_grounding_tags(text)
        finally:
            import shutil
            shutil.rmtree(tmp_output, ignore_errors=True)
