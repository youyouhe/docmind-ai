"""
Migration Compatibility Tests
测试新旧算法的输出兼容性

运行方式:
    cd lib/docmind-ai
    pytest tests/test_migration_compatibility.py -v
"""

import os
import json
import pytest
from pathlib import Path

# Test data directory
TEST_DATA_DIR = Path(__file__).parent.parent / "pageindex_v2"
RESULTS_DIR = Path(__file__).parent / "migration_results"

# Sample PDFs for testing
TEST_PDFS = [
    TEST_DATA_DIR / "four-lectures.pdf",
    TEST_DATA_DIR / "2023-annual-report.pdf",
    # TEST_DATA_DIR / "q1-fy25-earnings.pdf",  # Add more as needed
]

# Filter to existing files only
TEST_PDFS = [p for p in TEST_PDFS if p.exists()]


@pytest.fixture(scope="session")
def setup_test_env():
    """Setup test environment"""
    # Create results directory
    RESULTS_DIR.mkdir(exist_ok=True, parents=True)
    yield
    # Cleanup after tests (optional)


@pytest.fixture
def default_config():
    """Default configuration for testing"""
    from pageindex_v2 import ConfigLoader
    
    # Use deepseek-chat (matches .env configuration)
    return ConfigLoader().load({
        "model": "deepseek-chat",  # Changed from gpt-4o to use DeepSeek API key
        "toc_check_page_num": 20,
        "max_page_num_each_node": 10,
        "max_token_num_each_node": 20000,
        "if_add_node_id": "yes",
        "if_add_node_summary": "no",  # Skip summary to speed up tests
        "if_add_node_text": "no",
        "if_add_doc_description": "no"
    })


def count_nodes(structure):
    """递归统计节点总数"""
    if not structure:
        return 0
    
    count = len(structure)
    for node in structure:
        if "nodes" in node and node["nodes"]:
            count += count_nodes(node["nodes"])
    
    return count


def max_depth(structure, current=1):
    """计算树的最大深度"""
    if not structure:
        return current - 1
    
    max_d = current
    for node in structure:
        if "nodes" in node and node["nodes"]:
            max_d = max(max_d, max_depth(node["nodes"], current + 1))
    
    return max_d


def collect_titles(structure):
    """收集所有节点标题（用于对比）"""
    titles = []
    for node in structure:
        titles.append(node.get("title", ""))
        if "nodes" in node and node["nodes"]:
            titles.extend(collect_titles(node["nodes"]))
    return titles


class TestOutputFormatCompatibility:
    """测试输出格式兼容性"""
    
    def test_import_compatibility(self):
        """测试导入兼容性 - 新算法应该能像老算法一样被导入"""
        # 应该能导入老API的所有接口
        from pageindex_v2 import page_index_main, config, ConfigLoader
        
        assert callable(page_index_main)
        assert callable(config)
        assert ConfigLoader is not None
        
        print("\n[OK] Import compatibility verified")
    
    def test_config_loader(self, default_config):
        """测试 ConfigLoader 兼容性"""
        assert hasattr(default_config, 'model')
        assert hasattr(default_config, 'toc_check_page_num')
        assert hasattr(default_config, 'if_add_node_id')
        
        print("\n[OK] ConfigLoader compatibility verified")
    
    @pytest.mark.parametrize("pdf_path", TEST_PDFS)
    def test_output_structure_format(self, pdf_path, default_config, setup_test_env):
        """测试输出格式 - 应该匹配老版本的结构"""
        from pageindex_v2 import page_index_main
        
        print(f"\n\n{'='*70}")
        print(f"Testing: {pdf_path.name}")
        print(f"{'='*70}")
        
        # 运行新算法
        result = page_index_main(str(pdf_path), default_config)
        
        # 验证顶层结构
        assert "result" in result, "Missing 'result' key in output"
        assert "performance" in result, "Missing 'performance' key in output"
        
        # 验证 result 内容
        result_data = result["result"]
        assert "doc_name" in result_data, "Missing 'doc_name' in result"
        assert "structure" in result_data, "Missing 'structure' in result"
        
        # 验证 performance 内容
        perf = result["performance"]
        assert "total_time" in perf, "Missing 'total_time' in performance"
        assert isinstance(perf["total_time"], (int, float)), "total_time should be numeric"
        
        # 保存结果用于检查
        output_file = RESULTS_DIR / f"{pdf_path.stem}_v2_output.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n[OK] Output format valid for {pdf_path.name}")
        print(f"  doc_name: {result_data['doc_name']}")
        print(f"  nodes: {count_nodes(result_data['structure'])}")
        print(f"  depth: {max_depth(result_data['structure'])}")
        print(f"  processing_time: {perf['total_time']:.2f}s")
        print(f"  saved to: {output_file}")


class TestTreeStructureValidation:
    """测试树结构有效性"""
    
    @pytest.mark.parametrize("pdf_path", TEST_PDFS)
    def test_node_fields_completeness(self, pdf_path, default_config, setup_test_env):
        """验证节点字段完整性"""
        from pageindex_v2 import page_index_main
        
        result = page_index_main(str(pdf_path), default_config)
        structure = result["result"]["structure"]
        
        def check_node(node, path="root"):
            """递归检查节点字段"""
            # 必需字段
            assert "title" in node, f"Missing 'title' in {path}"
            assert "start_index" in node, f"Missing 'start_index' in {path}"
            assert "end_index" in node, f"Missing 'end_index' in {path}"
            assert "node_id" in node, f"Missing 'node_id' in {path}"
            
            # 字段类型验证
            assert isinstance(node["title"], str), f"title should be str in {path}"
            assert isinstance(node["start_index"], int), f"start_index should be int in {path}"
            assert isinstance(node["end_index"], int), f"end_index should be int in {path}"
            assert isinstance(node["node_id"], str), f"node_id should be str in {path}"
            
            # 逻辑验证
            assert node["start_index"] > 0, f"start_index should be > 0 in {path}"
            assert node["end_index"] >= node["start_index"], \
                f"end_index should >= start_index in {path}"
            
            # 递归检查子节点
            if "nodes" in node and node["nodes"]:
                for i, child in enumerate(node["nodes"]):
                    check_node(child, f"{path}.{i}")
        
        # 检查所有根节点
        for i, root in enumerate(structure):
            check_node(root, f"root[{i}]")
        
        print(f"\n[OK] Node fields validation passed for {pdf_path.name}")
    
    @pytest.mark.parametrize("pdf_path", TEST_PDFS)
    def test_tree_depth_constraint(self, pdf_path, default_config, setup_test_env):
        """验证树深度约束（新算法限制为4层）"""
        from pageindex_v2 import page_index_main
        
        result = page_index_main(str(pdf_path), default_config)
        structure = result["result"]["structure"]
        
        depth = max_depth(structure)
        
        # 新算法应该限制在4层以内
        assert depth <= 4, f"Tree depth {depth} exceeds maximum 4 levels"
        
        print(f"\n[OK] Tree depth constraint verified for {pdf_path.name}: {depth} levels")


class TestNodeIDGeneration:
    """测试 node_id 生成"""
    
    @pytest.mark.parametrize("pdf_path", TEST_PDFS[:1])  # Just test one file
    def test_node_id_format(self, pdf_path, default_config, setup_test_env):
        """验证 node_id 格式（应该是 0000, 0001, 0002...）"""
        from pageindex_v2 import page_index_main
        
        result = page_index_main(str(pdf_path), default_config)
        structure = result["result"]["structure"]
        
        def collect_node_ids(nodes):
            """收集所有 node_id"""
            ids = []
            for node in nodes:
                ids.append(node.get("node_id"))
                if "nodes" in node and node["nodes"]:
                    ids.extend(collect_node_ids(node["nodes"]))
            return ids
        
        node_ids = collect_node_ids(structure)
        
        # 验证格式
        for nid in node_ids:
            assert len(nid) == 4, f"node_id should be 4 digits: {nid}"
            assert nid.isdigit(), f"node_id should be numeric: {nid}"
        
        # 验证唯一性
        assert len(node_ids) == len(set(node_ids)), "node_id should be unique"
        
        print(f"\n[OK] node_id format verified for {pdf_path.name}")
        print(f"  total nodes: {len(node_ids)}")
        print(f"  sample ids: {node_ids[:5]}...")


class TestPerformanceData:
    """测试性能数据"""
    
    @pytest.mark.parametrize("pdf_path", TEST_PDFS[:1])
    def test_performance_metrics(self, pdf_path, default_config, setup_test_env):
        """验证性能指标存在"""
        from pageindex_v2 import page_index_main
        
        result = page_index_main(str(pdf_path), default_config)
        perf = result["performance"]
        
        # 验证关键指标
        assert "total_time" in perf
        assert "tree_building" in perf
        assert "summary" in perf
        
        # 验证数值合理性
        assert perf["total_time"] > 0
        assert perf["summary"]["total_nodes"] > 0
        
        print(f"\n[OK] Performance metrics verified for {pdf_path.name}")
        print(f"  total_time: {perf['total_time']:.2f}s")
        print(f"  total_nodes: {perf['summary']['total_nodes']}")


# ============================================================================
# 运行测试
# ============================================================================

if __name__ == "__main__":
    # 检查测试文件是否存在
    print("\n" + "="*70)
    print("Migration Compatibility Test Suite")
    print("="*70)
    print(f"\nTest PDFs found: {len(TEST_PDFS)}")
    for pdf in TEST_PDFS:
        print(f"  - {pdf.name}")
    
    if not TEST_PDFS:
        print("\n[WARNING] No test PDF files found!")
        print(f"Expected location: {TEST_DATA_DIR}")
        print("Please add PDF files to pageindex_v2/ directory")
    else:
        print(f"\nRun tests with: pytest {__file__} -v")
