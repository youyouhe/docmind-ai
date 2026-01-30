"""
Bid API 内部测试脚本
测试所有 bid 端点的功能正确性

运行方式:
    cd lib/docmind-ai
    python tests/test_bid_api.py
"""

import requests
import json
import time
from typing import Dict, Any

API_BASE = "http://localhost:8003"

def print_test(name: str, passed: bool, details: str = ""):
    """打印测试结果"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status} - {name}")
    if details:
        print(f"    {details}")


# =============================================================================
# 测试数据
# =============================================================================

SAMPLE_PROJECT = {
    "title": "测试投标项目",
    "tender_document_id": "test-doc-001",
    "tender_document_tree": {
        "id": "root",
        "title": "测试招标文档",
        "level": 0,
        "content": "测试内容",
        "children": []
    },
    "sections": [
        {
            "id": "section-1",
            "title": "技术方案",
            "content": "",
            "summary": "技术方案描述",
            "requirement_references": ["req-1"],
            "status": "pending",
            "order": 1,
            "word_count": 0
        },
        {
            "id": "section-2",
            "title": "商务方案",
            "content": "",
            "summary": "商务方案描述",
            "requirement_references": ["req-2"],
            "status": "pending",
            "order": 2,
            "word_count": 0
        }
    ]
}

SAMPLE_TREE = {
    "id": "root",
    "title": "招标文件",
    "level": 0,
    "content": "完整内容",
    "summary": "文档摘要",
    "children": [
        {
            "id": "child-1",
            "title": "第一章",
            "level": 1,
            "content": "第一章内容",
            "summary": "第一章摘要",
            "children": []
        }
    ]
}


# =============================================================================
# 测试用例
# =============================================================================

def test_create_project():
    """测试创建项目"""
    try:
        response = requests.post(f"{API_BASE}/api/bid/projects", json=SAMPLE_PROJECT)
        if response.status_code == 200:
            data = response.json()
            print_test("创建项目", True, f"项目ID: {data['id']}")
            return data['id']
        else:
            print_test("创建项目", False, f"状态码: {response.status_code}")
            return None
    except Exception as e:
        print_test("创建项目", False, str(e))
        return None


def test_list_projects():
    """测试列出项目"""
    try:
        response = requests.get(f"{API_BASE}/api/bid/projects")
        if response.status_code == 200:
            projects = response.json()
            print_test("列出项目", True, f"找到 {len(projects)} 个项目")
            return projects
        else:
            print_test("列出项目", False, f"状态码: {response.status_code}")
            return []
    except Exception as e:
        print_test("列出项目", False, str(e))
        return []


def test_get_project(project_id: str):
    """测试获取项目详情"""
    try:
        response = requests.get(f"{API_BASE}/api/bid/projects/{project_id}")
        if response.status_code == 200:
            data = response.json()
            print_test("获取项目", True, f"标题: {data['title']}, 章节数: {len(data['sections'])}")
            return data
        else:
            print_test("获取项目", False, f"状态码: {response.status_code}")
            return None
    except Exception as e:
        print_test("获取项目", False, str(e))
        return None


def test_update_project(project_id: str):
    """测试更新项目"""
    try:
        # 先获取项目
        get_response = requests.get(f"{API_BASE}/api/bid/projects/{project_id}")
        project = get_response.json()

        # 修改标题
        project['title'] = "更新后的测试项目"

        response = requests.put(f"{API_BASE}/api/bid/projects/{project_id}", json=project)
        if response.status_code == 200:
            print_test("更新项目", True, f"新标题: {project['title']}")
        else:
            print_test("更新项目", False, f"状态码: {response.status_code}")
    except Exception as e:
        print_test("更新项目", False, str(e))


def test_auto_save(project_id: str):
    """测试自动保存"""
    try:
        content = "这是自动保存的测试内容"
        response = requests.post(
            f"{API_BASE}/api/bid/projects/{project_id}/sections/section-1/auto-save",
            json={"content": content}
        )
        if response.status_code == 200:
            data = response.json()
            print_test("自动保存", True, f"保存时间: {data['saved_at']}")
        else:
            print_test("自动保存", False, f"状态码: {response.status_code}")
    except Exception as e:
        print_test("自动保存", False, str(e))


def test_generate_content():
    """测试 AI 内容生成"""
    try:
        request = {
            "section_id": "test-section",
            "section_title": "技术方案",
            "section_description": "详细的技术方案说明",
            "tender_tree": SAMPLE_TREE,
            "requirement_references": ["req-1"],
            "user_prompt": "突出技术创新"
        }

        response = requests.post(f"{API_BASE}/api/bid/content/generate", json=request)
        if response.status_code == 200:
            data = response.json()
            content_length = len(data.get('content', ''))
            print_test("AI 内容生成", True, f"提供商: {data['provider']}, 内容长度: {content_length}")
        else:
            print_test("AI 内容生成", False, f"状态码: {response.status_code}")
    except Exception as e:
        print_test("AI 内容生成", False, str(e))


def test_rewrite_text():
    """测试 AI 文本改写"""
    try:
        request = {
            "text": "这是一个测试文本，需要进行正式化处理。",
            "mode": "formal"
        }

        response = requests.post(f"{API_BASE}/api/bid/content/rewrite", json=request)
        if response.status_code == 200:
            data = response.json()
            print_test("AI 文本改写", True, f"改写后: {data['rewritten_text'][:50]}...")
        else:
            print_test("AI 文本改写", False, f"状态码: {response.status_code}")
    except Exception as e:
        print_test("AI 文本改写", False, str(e))


def test_delete_project(project_id: str):
    """测试删除项目"""
    try:
        response = requests.delete(f"{API_BASE}/api/bid/projects/{project_id}")
        if response.status_code == 200:
            print_test("删除项目", True, f"删除的项目ID: {project_id}")
        else:
            print_test("删除项目", False, f"状态码: {response.status_code}")
    except Exception as e:
        print_test("删除项目", False, str(e))


def test_error_handling():
    """测试错误处理"""
    # 测试不存在的项目
    try:
        response = requests.get(f"{API_BASE}/api/bid/projects/non-existent-id")
        if response.status_code == 404:
            print_test("错误处理-404", True, "正确返回 404")
        else:
            print_test("错误处理-404", False, f"状态码: {response.status_code}")
    except Exception as e:
        print_test("错误处理-404", False, str(e))


# =============================================================================
# 主测试流程
# =============================================================================

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Bid API 内部测试")
    print("=" * 60)
    print()

    # 0. 检查服务器连接
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            print_test("服务器连接", True, "服务器运行正常")
        else:
            print_test("服务器连接", False, f"状态码: {response.status_code}")
            print("\n[ERROR] 服务器未运行，请先启动服务器:")
            print("   cd lib/docmind-ai")
            print("   uvicorn api.index:app --host 0.0.0.0 --port 8003")
            return
    except Exception as e:
        print_test("服务器连接", False, f"无法连接到服务器: {str(e)}")
        print("\n[ERROR] 服务器未运行，请先启动服务器:")
        print("   cd lib/docmind-ai")
        print("   uvicorn api.index:app --host 0.0.0.0 --port 8003")
        return

    print()

    # 1. 创建项目
    project_id = test_create_project()
    if not project_id:
        print("\n[ERROR] 创建项目失败，终止测试")
        return

    time.sleep(0.5)

    # 2. 列出项目
    test_list_projects()
    time.sleep(0.5)

    # 3. 获取项目
    test_get_project(project_id)
    time.sleep(0.5)

    # 4. 更新项目
    test_update_project(project_id)
    time.sleep(0.5)

    # 5. 自动保存
    test_auto_save(project_id)
    time.sleep(0.5)

    # 6. AI 内容生成
    test_generate_content()
    time.sleep(0.5)

    # 7. AI 文本改写
    test_rewrite_text()
    time.sleep(0.5)

    # 8. 错误处理
    test_error_handling()
    time.sleep(0.5)

    # 9. 删除项目
    test_delete_project(project_id)

    print()
    print("=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
