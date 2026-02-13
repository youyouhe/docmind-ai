"""
OCR field extraction routes for CompanyDataManager auto-fill.

Endpoint: POST /api/ocr/extract
Accepts OCR markdown text + extraction_type, uses LLM to extract structured fields.
"""

import os
import json
import re
import logging
import traceback
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services import LLMProvider

logger = logging.getLogger("pageindex.api.ocr")

router = APIRouter(
    prefix="/api/ocr",
    tags=["ocr-extraction"],
)


# ─── Request / Response Models ───────────────────────────────

class ExtractionRequest(BaseModel):
    """Request to extract structured fields from OCR text."""
    text: str = Field(..., min_length=1, description="OCR markdown text")
    extraction_type: str = Field(
        ...,
        description="Type of extraction: company_profile | team_member | past_project | qualification",
    )


class ExtractionResponse(BaseModel):
    """Structured extraction result."""
    success: bool
    data: dict = Field(default_factory=dict)
    extraction_type: str
    error: Optional[str] = None


# ─── Prompt Templates ────────────────────────────────────────

EXTRACTION_PROMPTS = {
    "company_profile": """你是一个专业的文档信息提取助手。请从以下营业执照或公司文档的OCR识别文本中，提取公司信息。

=== OCR识别文本 ===
{ocr_text}

=== 提取要求 ===
请提取以下字段，并以JSON格式返回。如果某个字段在文本中找不到，请返回空字符串""。
不要添加任何解释，只返回JSON。

返回格式：
{{
  "company_name": "公司全称",
  "legal_representative": "法定代表人姓名",
  "registration_number": "统一社会信用代码",
  "address": "注册地址",
  "registered_capital": "注册资本（含单位，如: 5000万元）",
  "established_date": "成立日期（格式: YYYY-MM-DD）",
  "business_scope": "经营范围",
  "phone": "联系电话",
  "email": "电子邮箱",
  "website": "公司网站",
  "qualifications": ["资质1", "资质2"]
}}

只返回JSON，不要有任何其他文字。""",

    "team_member": """你是一个专业的文档信息提取助手。请从以下证书、简历或人员资料的OCR识别文本中，提取团队成员信息。

=== OCR识别文本 ===
{ocr_text}

=== 提取要求 ===
请提取以下字段，并以JSON格式返回。如果某个字段在文本中找不到，请返回空字符串""或0。
不要添加任何解释，只返回JSON。

返回格式：
{{
  "name": "姓名",
  "title": "职称（如: 高级工程师、教授级高工）",
  "certifications": ["证书名称1", "证书名称2"],
  "education": "学历/学位和专业（如: 硕士/计算机科学）",
  "years_experience": 0,
  "description": "简要描述或专业方向"
}}

只返回JSON，不要有任何其他文字。""",

    "past_project": """你是一个专业的文档信息提取助手。请从以下合同或项目文档的OCR识别文本中，提取项目信息。

=== OCR识别文本 ===
{ocr_text}

=== 提取要求 ===
请提取以下字段，并以JSON格式返回。如果某个字段在文本中找不到，请返回空字符串""或0。
金额请提取数字部分，单位默认为"万元"。日期格式为YYYY-MM-DD。
不要添加任何解释，只返回JSON。

返回格式：
{{
  "project_name": "项目名称",
  "client": "甲方/业主单位名称",
  "contract_value": 0,
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "description": "项目简要描述",
  "domain": "项目所属领域（如: IT、工程、咨询）",
  "technologies": ["技术1", "技术2"]
}}

只返回JSON，不要有任何其他文字。""",

    "qualification": """你是一个专业的文档信息提取助手。请从以下资质证书或认证文件的OCR识别文本中，提取资质信息。

=== OCR识别文本 ===
{ocr_text}

=== 提取要求 ===
请提取以下字段，并以JSON格式返回。如果某个字段在文本中找不到，请返回空字符串""。
不要添加任何解释，只返回JSON。

返回格式：
{{
  "qualification_name": "资质/认证名称（如: ISO 9001、CMMI 5级）",
  "issuing_authority": "颁发机构",
  "certificate_number": "证书编号",
  "issue_date": "颁发日期（YYYY-MM-DD）",
  "expiry_date": "有效期至（YYYY-MM-DD）",
  "scope": "认证范围/适用范围",
  "holder": "持有单位/个人"
}}

只返回JSON，不要有任何其他文字。""",
}


# ─── JSON Parsing Helper ─────────────────────────────────────

def _parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling ```json blocks."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try markdown code block
    match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if match:
        return json.loads(match.group(1))

    # Try finding first { to last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise json.JSONDecodeError("No JSON object found in LLM response", text, 0)


# ─── Endpoint ────────────────────────────────────────────────

@router.post("/extract", response_model=ExtractionResponse)
async def extract_fields(request: ExtractionRequest) -> ExtractionResponse:
    """Extract structured fields from OCR text using LLM."""

    if request.extraction_type not in EXTRACTION_PROMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown extraction_type: {request.extraction_type}. "
                   f"Valid types: {list(EXTRACTION_PROMPTS.keys())}",
        )

    # Initialize LLM (follows bid/routes.py pattern)
    provider = os.getenv("LLM_PROVIDER", "deepseek")
    api_key = os.getenv(f"{provider.upper()}_API_KEY")
    model = os.getenv("LLM_MODEL", None)

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"LLM API key not configured for provider '{provider}'",
        )

    try:
        llm = LLMProvider(provider=provider, api_key=api_key, model=model)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=f"LLM not available: {e}")

    # Build prompt
    prompt = EXTRACTION_PROMPTS[request.extraction_type].format(ocr_text=request.text)

    try:
        raw_response = await llm.chat(
            prompt,
            operation_type="ocr_extraction",
            metadata={"extraction_type": request.extraction_type},
        )

        data = _parse_json_response(raw_response)

        logger.info(
            "OCR extraction succeeded: type=%s, fields=%d",
            request.extraction_type,
            len(data),
        )

        return ExtractionResponse(
            success=True,
            data=data,
            extraction_type=request.extraction_type,
        )

    except json.JSONDecodeError as e:
        logger.error("JSON parse failed for OCR extraction: %s", e)
        return ExtractionResponse(
            success=False,
            data={},
            extraction_type=request.extraction_type,
            error=f"AI 返回格式不正确，无法解析 JSON: {str(e)}",
        )
    except Exception as e:
        logger.error("OCR extraction failed: %s", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"字段提取失败: {str(e)}")
