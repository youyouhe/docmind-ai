"""
Bid writing routes for PageIndex API.

Provides endpoints for:
- Project CRUD operations
- Auto-save functionality
- AI content generation
- Text rewriting
"""

import os
import uuid
import json
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from api.database import get_db, DatabaseManager
from api.services import LLMProvider


router = APIRouter(
    prefix="/api/bid",
    tags=["bid-writing"],
)


# =============================================================================
# Data Models
# =============================================================================

class TenderSection(BaseModel):
    """A section in the bid document."""
    id: str
    title: str
    content: str
    summary: Optional[str] = None
    requirement_references: List[str] = []
    status: str = "pending"  # pending/in_progress/completed
    order: int
    word_count: int = 0


class TenderProject(BaseModel):
    """A bid writing project."""
    id: str
    title: str
    tender_document_id: str
    tender_document_tree: dict
    sections: List[TenderSection]
    status: str = "draft"  # draft/review/completed
    version: int = 1
    created_at: int
    updated_at: int


class CreateProjectRequest(BaseModel):
    """Request to create a new project."""
    title: str
    tender_document_id: str
    tender_document_tree: dict
    sections: List[TenderSection]


class GenerateContentRequest(BaseModel):
    """Request to generate section content."""
    section_id: str
    section_title: str
    section_description: str
    tender_tree: dict
    requirement_references: List[str] = []
    previous_context: Optional[str] = None
    user_prompt: Optional[str] = None
    attachments: Optional[List[str]] = None


class RewriteRequest(BaseModel):
    """Request to rewrite text."""
    text: str
    mode: str  # formal/concise/expand/clarify
    context: Optional[str] = None


class AutoSaveRequest(BaseModel):
    """Request to auto-save section content."""
    content: str


# =============================================================================
# Storage
# =============================================================================

PROJECTS_DIR = os.path.join("data", "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)


# =============================================================================
# Project Endpoints
# =============================================================================

@router.post("/projects")
async def create_project(
    request: CreateProjectRequest,
    db: DatabaseManager = Depends(get_db)
) -> TenderProject:
    """Create a new bid writing project."""
    project_id = f"project-{uuid.uuid4()}"
    now = int(datetime.now().timestamp() * 1000)

    project = TenderProject(
        id=project_id,
        title=request.title,
        tender_document_id=request.tender_document_id,
        tender_document_tree=request.tender_document_tree,
        sections=request.sections,
        status="draft",
        version=1,
        created_at=now,
        updated_at=now
    )

    # Save to file
    project_path = os.path.join(PROJECTS_DIR, f"{project_id}.json")
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(project.model_dump(), f, indent=2, ensure_ascii=False)

    return project


@router.get("/projects")
async def list_projects() -> List[TenderProject]:
    """List all bid writing projects."""
    projects = []

    for filename in os.listdir(PROJECTS_DIR):
        if filename.endswith(".json"):
            project_path = os.path.join(PROJECTS_DIR, filename)
            try:
                with open(project_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)
                    projects.append(TenderProject(**project_data))
            except Exception as e:
                print(f"Error loading project {filename}: {e}")

    # Sort by updated_at descending
    projects.sort(key=lambda p: p.updated_at, reverse=True)
    return projects


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> TenderProject:
    """Get a specific bid writing project."""
    project_path = os.path.join(PROJECTS_DIR, f"{project_id}.json")

    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    with open(project_path, 'r', encoding='utf-8') as f:
        project_data = json.load(f)
        return TenderProject(**project_data)


@router.put("/projects/{project_id}")
async def update_project(project_id: str, request: TenderProject) -> TenderProject:
    """Update a bid writing project."""
    project_path = os.path.join(PROJECTS_DIR, f"{project_id}.json")

    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    # Update timestamp
    request.updated_at = int(datetime.now().timestamp() * 1000)

    # Save to file
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(request.model_dump(), f, indent=2, ensure_ascii=False)

    return request


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str) -> dict:
    """Delete a bid writing project."""
    project_path = os.path.join(PROJECTS_DIR, f"{project_id}.json")

    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    os.remove(project_path)

    return {
        "id": project_id,
        "deleted": True
    }


@router.post("/projects/{project_id}/sections/{section_id}/auto-save")
async def auto_save_section(
    project_id: str,
    section_id: str,
    request: AutoSaveRequest
) -> dict:
    """Auto-save a section's content."""
    project_path = os.path.join(PROJECTS_DIR, f"{project_id}.json")

    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    # Load project
    with open(project_path, 'r', encoding='utf-8') as f:
        project_data = json.load(f)
        project = TenderProject(**project_data)

    # Find and update section
    section_found = False
    for section in project.sections:
        if section.id == section_id:
            section.content = request.content
            section.word_count = len(request.content)
            section_found = True
            break

    if not section_found:
        raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")

    # Update project timestamp
    project.updated_at = int(datetime.now().timestamp() * 1000)

    # Save to file
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(project.model_dump(), f, indent=2, ensure_ascii=False)

    return {
        "success": True,
        "saved_at": project.updated_at
    }


# =============================================================================
# Content Generation Endpoints
# =============================================================================

@router.post("/content/generate")
async def generate_content(request: GenerateContentRequest) -> dict:
    """Generate bid section content using AI."""
    from api.services import ParseService

    # Get LLM provider
    provider = os.getenv("LLM_PROVIDER", "deepseek")
    api_key = os.getenv(f"{provider.upper()}_API_KEY")
    model = os.getenv("LLM_MODEL", None)

    llm = LLMProvider(provider=provider, api_key=api_key, model=model)

    # Build prompt
    prompt = build_content_generation_prompt(
        request.section_title,
        request.section_description,
        request.tender_tree,
        request.requirement_references,
        request.previous_context,
        request.user_prompt,
        request.attachments
    )

    # Generate content
    content = await llm.chat(prompt)

    return {
        "content": content,
        "provider": provider,
        "model": model or llm.get_default_model(),
        "generated_at": int(datetime.now().timestamp() * 1000)
    }


@router.post("/content/rewrite")
async def rewrite_text(request: RewriteRequest) -> dict:
    """Rewrite text using AI."""
    from api.services import ParseService

    # Get LLM provider
    provider = os.getenv("LLM_PROVIDER", "deepseek")
    api_key = os.getenv(f"{provider.upper()}_API_KEY")
    model = os.getenv("LLM_MODEL", None)

    llm = LLMProvider(provider=provider, api_key=api_key, model=model)

    # Build prompt
    prompt = build_rewrite_prompt(request.text, request.mode, request.context)

    # Rewrite text
    rewritten_text = await llm.chat(prompt)

    return {
        "rewritten_text": rewritten_text,
        "provider": provider,
        "model": model or llm.get_default_model()
    }


# =============================================================================
# Helper Functions
# =============================================================================

def build_content_generation_prompt(
    section_title: str,
    section_description: str,
    tender_tree: dict,
    requirement_references: List[str],
    previous_context: Optional[str],
    user_prompt: Optional[str],
    attachments: Optional[List[str]]
) -> str:
    """Build prompt for AI content generation."""

    # Extract relevant content from tender tree
    def extract_tree_content(node: dict, depth: int = 0, max_depth: int = 2) -> List[str]:
        if depth > max_depth:
            return []

        content_parts = []

        title = node.get("title", "")
        summary = node.get("summary", "")

        node_text = f"【{title}】"
        if summary:
            node_text += f"\n{summary}"

        content_parts.append(node_text)

        for child in node.get("children", []):
            content_parts.extend(extract_tree_content(child, depth + 1, max_depth))

        return content_parts

    # Build tender requirements context
    tender_context = ""
    if requirement_references:
        context_parts = extract_tree_content(tender_tree)
        tender_context = "\n\n".join(context_parts[:10])

    prompt = f"""你是一个专业的投标文件编写专家。请根据招标要求编写投标文件章节。

=== 当前章节 ===
标题：{section_title}
描述：{section_description}

"""

    if tender_context:
        prompt += f"=== 招标文档相关章节 ===\n{tender_context}\n\n"

    if requirement_references:
        prompt += f"=== 对应招标要求节点 ===\n"
        prompt += f"引用: {', '.join(requirement_references)}\n\n"

    if previous_context:
        prompt += f"=== 前文上下文 ===\n{previous_context[:1000]}...\n\n"

    if user_prompt:
        prompt += f"=== 用户补充说明 ===\n{user_prompt}\n\n"

    if attachments:
        prompt += f"=== 参考附件 ===\n{', '.join(attachments)}\n\n"

    prompt += """=== 编写要求 ===
1. 严格按照招标要求编写
2. 使用专业、规范的商务语言
3. 突出公司优势和符合性
4. 结构清晰，逻辑严密
5. 语言简练，避免冗余

请生成该章节的完整内容。直接返回内容，不要包含任何解释或元信息。"""

    return prompt


def build_rewrite_prompt(
    original_text: str,
    mode: str,
    context: Optional[str]
) -> str:
    """Build prompt for text rewriting."""

    mode_descriptions = {
        'formal': '正式化 - 使语言更加正式、规范，符合商务文件要求',
        'concise': '精简 - 去除冗余，保留核心信息，使表达更加简洁',
        'expand': '扩充 - 在原有内容基础上增加详细说明和补充信息',
        'clarify': '澄清 - 使表达更加清晰明确，避免歧义'
    }

    mode_instructions = {
        'formal': '使用商务正式用语，适当使用被动语态，增加专业术语',
        'concise': '删除重复和不必要的词语，保留关键信息，使用更直接的表达',
        'expand': '在原有内容基础上增加详细说明、具体例子和补充信息',
        'clarify': '重新组织句子结构，使用更明确的词汇，消除模糊表达'
    }

    description = mode_descriptions.get(mode, 'formal')
    instruction = mode_instructions.get(mode, '使用商务正式用语')

    prompt = f"""请对以下投标文件文本进行改写。

=== 改写模式 ===
{description}

=== 原文 ===
{original_text}

"""

    if context:
        prompt += f"=== 上下文 ===\n{context}\n\n"

    prompt += f"""=== 改写要求 ===
{instruction}

请直接返回改写后的文本，不要解释或添加其他内容。"""

    return prompt
