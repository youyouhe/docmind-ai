#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script to debug Phase 1 structure analysis
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pageindex.utils import ChatGPT_API
from pageindex.prompts.structure_extraction_prompts import ANALYZE_DOCUMENT_STRUCTURE_PROMPT

# Sample document text
sample_text = """<physical_index_1>
吉利学院语音实验室软件系统采购项目招标公告
1. 项目名称：吉利学院语音实验室软件系统采购项目
项目编号：GL26011943
2. 项目概况与招标范围
2.1 采购内容：语言学习系统控制软件等，详见公告附件。
2.2 项目地点：四川省成都市东部新区成简大道二段123 号。
2.3 供货周期：合同签订后15 日内，完成服务内容及整体验收。
3. 投标人资格要求
3.1 供应商必须是具有独立法人资格的单位，注册资金≥100 万，成立时间3
年以上，且具备销售实验室设备或计算机软件及辅助设备或信息系统集成等相关
经营范围
3.2 提供语音实验室项目业绩不少于2 个（须提供业绩证明，合同及发票复
印件等）；
"""

def test_phase1_analysis():
    print("="*70)
    print("Testing Phase 1 Structure Analysis")
    print("="*70)
    
    # Build prompt
    prompt = ANALYZE_DOCUMENT_STRUCTURE_PROMPT.format(document_text=sample_text)
    
    print("\n[1] Calling LLM...")
    print(f"Prompt length: {len(prompt)} chars")
    
    # Call LLM
    model = "deepseek-chat"
    response = ChatGPT_API(model=model, prompt=prompt)
    
    print(f"\n[2] LLM Response:")
    print("-"*70)
    print(response)
    print("-"*70)
    
    print(f"\n[3] Response length: {len(response)} chars")
    print(f"Response type: {type(response)}")
    
    # Try to parse
    import json
    from pageindex.utils import extract_json_markdown_block, extract_json_bracket_matching
    
    print("\n[4] Attempting to parse JSON...")
    
    # Method 1: Markdown block
    result = extract_json_markdown_block(response)
    if result:
        print(f"✓ Markdown block extraction: SUCCESS")
        print(f"  Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return result
    else:
        print(f"✗ Markdown block extraction: FAILED")
    
    # Method 2: Bracket matching
    result = extract_json_bracket_matching(response)
    if result:
        print(f"✓ Bracket matching extraction: SUCCESS")
        print(f"  Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return result
    else:
        print(f"✗ Bracket matching extraction: FAILED")
    
    # Method 3: Direct parsing
    try:
        result = json.loads(response.strip())
        print(f"✓ Direct JSON parsing: SUCCESS")
        print(f"  Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return result
    except Exception as e:
        print(f"✗ Direct JSON parsing: FAILED - {e}")
    
    print("\n[5] All parsing methods failed!")
    return None

if __name__ == "__main__":
    result = test_phase1_analysis()
    
    if result:
        print("\n" + "="*70)
        print("ANALYSIS RESULT:")
        print("="*70)
        print(f"Structure Type: {result.get('structure_type')}")
        print(f"Strategy: {result.get('extraction_strategy')}")
        print(f"Confidence: {result.get('confidence')}")
        print(f"Patterns: {result.get('numbering_patterns_found')}")
        print(f"Estimated Count: {result.get('estimated_section_count')}")
    else:
        print("\n❌ Failed to parse LLM response")
