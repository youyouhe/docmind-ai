"""
文档类型智能分类器
Document Type Intelligent Classifier

基于文档内容和结构特征，准确识别文档类型
"""

import re
from typing import Dict, List, Any, Optional
from ..core.llm_client import LLMClient


class DocumentClassifier:
    """
    文档类型分类器
    
    支持的文档类型：
    - tender: 招标文件
    - bid: 投标文件
    - contract: 合同文件
    - academic: 学术论文
    - technical: 技术文档/API文档
    - news: 新闻稿/报道
    - report: 报告(年报/研究报告等)
    - manual: 使用手册/说明书
    - legal: 法律文件
    - general: 通用文档
    """
    
    DOCUMENT_TYPES = {
        "tender": {
            "name": "招标文件",
            "keywords": ["招标", "投标", "采购", "竞标", "评标", "开标"],
            "patterns": [r"招标公告", r"投标须知", r"评分标准", r"采购需求"],
            "structure_hints": ["第一章", "第二章", "附件", "评标办法"]
        },
        "bid": {
            "name": "投标文件",
            "keywords": ["投标函", "报价", "技术方案", "商务响应", "资质证明"],
            "patterns": [r"投标函", r"开标一览表", r"技术响应", r"商务响应"],
            "structure_hints": ["技术部分", "商务部分", "资格证明"]
        },
        "contract": {
            "name": "合同文件",
            "keywords": ["甲方", "乙方", "合同", "协议", "违约", "条款"],
            "patterns": [r"第[一二三四五六七八]条", r"甲乙双方", r"违约责任"],
            "structure_hints": ["总则", "权利义务", "违约责任", "争议解决"]
        },
        "academic": {
            "name": "学术论文",
            "keywords": ["abstract", "introduction", "methodology", "conclusion", "references", "摘要", "引言", "结论", "参考文献"],
            "patterns": [r"Abstract", r"Introduction", r"Chapter \d+", r"References"],
            "structure_hints": ["Abstract", "Introduction", "Methodology", "Results", "Discussion", "Conclusion"]
        },
        "technical": {
            "name": "技术文档",
            "keywords": ["api", "function", "class", "method", "parameter", "return", "接口", "函数"],
            "patterns": [r"API Reference", r"Class \w+", r"function \w+", r"\.get\(", r"\.post\("],
            "structure_hints": ["Getting Started", "API Reference", "Examples", "Configuration"]
        },
        "news": {
            "name": "新闻稿",
            "keywords": ["记者", "报道", "消息", "通讯员", "本报讯"],
            "patterns": [r"\d{4}年\d{1,2}月\d{1,2}日", r"记者\s+\w+\s+报道", r"本报讯"],
            "structure_hints": []
        },
        "report": {
            "name": "报告文件",
            "keywords": ["年度报告", "研究报告", "调查报告", "财务报告", "总结"],
            "patterns": [r"\d{4}年.*报告", r"Executive Summary", r"财务数据"],
            "structure_hints": ["概述", "背景", "分析", "结论", "建议"]
        },
        "manual": {
            "name": "使用手册",
            "keywords": ["使用说明", "操作指南", "用户手册", "安装", "配置"],
            "patterns": [r"安装步骤", r"操作流程", r"注意事项", r"常见问题"],
            "structure_hints": ["产品介绍", "安装", "使用", "维护", "故障排除"]
        },
        "legal": {
            "name": "法律文件",
            "keywords": ["法律", "法规", "条例", "规定", "办法"],
            "patterns": [r"第[一二三四五六七八九十]+章", r"第\d+条", r"中华人民共和国"],
            "structure_hints": ["总则", "分则", "附则"]
        }
    }
    
    def __init__(self, llm: Optional[LLMClient] = None, debug: bool = False):
        self.llm = llm
        self.debug = debug
    
    async def classify(
        self,
        tree: Dict[str, Any],
        pdf_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分类文档类型
        
        Returns:
            {
                "type": "tender",
                "confidence": 0.95,
                "name": "招标文件",
                "reasons": ["包含'招标公告'关键词", "结构符合招标文件特征"],
                "characteristics": {...}
            }
        """
        if self.debug:
            print("\n" + "="*60)
            print("[CLASSIFIER] Document Type Classification")
            print("="*60)
        
        # Step 1: 规则匹配（快速初步判断）
        rule_based_result = self._rule_based_classify(tree)
        
        # Step 2: LLM深度分类（更准确）
        if self.llm:
            llm_result = await self._llm_based_classify(tree, rule_based_result)
            final_result = llm_result
        else:
            final_result = rule_based_result
        
        if self.debug:
            print(f"\n✅ Classification result:")
            print(f"  Type: {final_result['type']} ({final_result['name']})")
            print(f"  Confidence: {final_result['confidence']:.2f}")
            print(f"  Reasons: {', '.join(final_result['reasons'][:3])}")
            print("="*60 + "\n")
        
        return final_result
    
    def _rule_based_classify(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        """基于规则的快速分类"""
        # 提取所有文本内容
        all_text = self._extract_text_from_tree(tree)
        titles = self._extract_titles_from_tree(tree)
        
        # 计算每种文档类型的匹配分数
        scores = {}
        
        for doc_type, config in self.DOCUMENT_TYPES.items():
            score = 0
            matched_reasons = []
            
            # 关键词匹配
            keyword_matches = sum(1 for kw in config["keywords"] if kw in all_text.lower())
            if keyword_matches > 0:
                score += keyword_matches * 10
                matched_reasons.append(f"包含{keyword_matches}个关键词")
            
            # 模式匹配
            pattern_matches = sum(1 for pattern in config["patterns"] if re.search(pattern, all_text))
            if pattern_matches > 0:
                score += pattern_matches * 15
                matched_reasons.append(f"匹配{pattern_matches}个特征模式")
            
            # 结构特征匹配
            structure_matches = sum(1 for hint in config["structure_hints"] if hint in " ".join(titles))
            if structure_matches > 0:
                score += structure_matches * 20
                matched_reasons.append(f"结构符合{structure_matches}个特征")
            
            scores[doc_type] = {
                "score": score,
                "reasons": matched_reasons
            }
        
        # 选择得分最高的类型
        if not scores or max(s["score"] for s in scores.values()) == 0:
            best_type = "general"
            confidence = 0.5
            reasons = ["未匹配到特定类型特征"]
        else:
            best_type = max(scores.keys(), key=lambda k: scores[k]["score"])
            max_score = scores[best_type]["score"]
            total_score = sum(s["score"] for s in scores.values())
            confidence = min(0.95, max_score / max(total_score, 1))
            reasons = scores[best_type]["reasons"]
        
        return {
            "type": best_type,
            "name": self.DOCUMENT_TYPES.get(best_type, {}).get("name", "通用文档"),
            "confidence": confidence,
            "reasons": reasons,
            "method": "rule_based"
        }
    
    async def _llm_based_classify(
        self,
        tree: Dict[str, Any],
        rule_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """基于LLM的深度分类"""
        
        # 提取前15个标题作为样本
        titles = self._extract_titles_from_tree(tree, limit=15)
        
        prompt = f"""你是一个专业的文档类型分类专家。请分析以下文档的标题结构，判断文档类型。

文档标题样本（前15个）：
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(titles))}

规则初步判断：{rule_result['type']} ({rule_result['name']})，置信度 {rule_result['confidence']:.2f}

支持的文档类型：
1. tender (招标文件)
2. bid (投标文件)
3. contract (合同文件)
4. academic (学术论文)
5. technical (技术文档)
6. news (新闻稿)
7. report (报告)
8. manual (使用手册)
9. legal (法律文件)
10. general (通用文档)

请返回JSON格式：
{{
  "type": "文档类型代码",
  "confidence": 0.0-1.0,
  "reasons": ["判断理由1", "判断理由2", "判断理由3"],
  "characteristics": {{
    "title_style": "标题风格描述",
    "structure_pattern": "结构特征描述",
    "content_domain": "内容领域描述"
  }}
}}

要求：
1. 如果规则判断的置信度 >= 0.8，优先采纳
2. 仔细分析标题的编号方式、用词特征、结构层次
3. 置信度要客观反映判断的确定性
4. 基于你的知识和对标题的理解判断文档类型，不要依赖我提供的特征规则"""

        try:
            response = await self.llm.chat_json(
                prompt,
                temperature=0.1
            )
            
            # 验证LLM结果
            if response.get("type") not in self.DOCUMENT_TYPES:
                if self.debug:
                    print(f"  ⚠ LLM returned invalid type: {response.get('type')}, using rule-based result")
                return rule_result
            
            # 合并LLM和规则结果
            return {
                "type": response.get("type", rule_result["type"]),
                "name": self.DOCUMENT_TYPES[response["type"]]["name"],
                "confidence": response.get("confidence", rule_result["confidence"]),
                "reasons": response.get("reasons", rule_result["reasons"]),
                "characteristics": response.get("characteristics", {}),
                "method": "llm_enhanced"
            }
            
        except Exception as e:
            if self.debug:
                print(f"  ⚠ LLM classification failed: {e}")
            return rule_result
    
    def _extract_text_from_tree(self, tree: Dict[str, Any], limit: int = 5000) -> str:
        """提取树中的所有文本内容（用于关键词匹配）"""
        texts = []
        
        def traverse(node):
            if len("".join(texts)) > limit:
                return
            
            if "title" in node:
                texts.append(node["title"])
            if "content" in node:
                texts.append(node.get("content", "")[:500])  # 只取前500字符
            
            for child in node.get("children", node.get("nodes", [])):
                traverse(child)
        
        # 从根节点或children开始
        if "children" in tree:
            for child in tree["children"]:
                traverse(child)
        elif "structure" in tree:
            for child in tree["structure"]:
                traverse(child)
        
        return " ".join(texts)[:limit]
    
    def _extract_titles_from_tree(self, tree: Dict[str, Any], limit: int = 20) -> List[str]:
        """提取树中的标题列表"""
        titles = []
        
        def traverse(node, level=0):
            if len(titles) >= limit or level > 3:  # 只看前3层
                return
            
            if "title" in node and node["title"]:
                titles.append(node["title"])
            
            for child in node.get("children", node.get("nodes", [])):
                traverse(child, level + 1)
        
        # 从根节点或children开始
        if "children" in tree:
            for child in tree["children"]:
                traverse(child)
        elif "structure" in tree:
            for child in tree["structure"]:
                traverse(child)
        
        return titles[:limit]
