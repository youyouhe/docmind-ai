"""
智能文档结构审核系统 V2
Intelligent Tree Structure Auditor V2

基于您的建议重新设计的审核系统：
1. 文档类型智能识别
2. 基于文档类型和LLM知识生成审核建议
3. PDF核实验证
4. 执行高置信度建议

核心原则：
- 标题内容不能修改（避免影响基于目录的搜索）
- 只调整格式/编号/页码
- 所有建议必须经过PDF核实
"""

from typing import Dict, List, Any, Optional, Tuple, Callable, Awaitable
import json
from ..core.llm_client import LLMClient
from .document_classifier import DocumentClassifier
from .tree_audit_advisor import TreeAuditAdvisor
from .progressive_audit_advisor import ProgressiveAuditAdvisor
from .pdf_verifier import PDFVerifier
from .advice_executor import AdviceExecutor


class TreeAuditorV2:
    """
    智能文档结构审核系统 V2
    
    支持两种审核模式：
    - standard: 一次性审核（快速）
    - progressive: 渐进式5轮审核（更准确，支持ADD操作）
    """
    
    def __init__(
        self,
        llm: LLMClient,
        pdf_path: Optional[str] = None,
        mode: str = "progressive",  # "standard" or "progressive"
        debug: bool = True,
        progress_callback: Optional[Callable[[str, int, int, str, float, Optional[dict]], Awaitable[None]]] = None
    ):
        self.llm = llm
        self.pdf_path = pdf_path
        self.mode = mode
        self.debug = debug
        self.progress_callback = progress_callback
        
        # 初始化各个组件
        self.classifier = DocumentClassifier(llm=llm, debug=debug)
        
        # 根据模式选择审核顾问
        if mode == "progressive":
            self.advisor = ProgressiveAuditAdvisor(llm=llm, debug=debug)
        else:
            self.advisor = TreeAuditAdvisor(llm=llm, debug=debug)
        
        self.verifier = PDFVerifier(pdf_path=pdf_path, debug=debug) if pdf_path else None
        self.executor = AdviceExecutor(debug=debug)
    
    async def audit_and_optimize(
        self,
        tree: Dict[str, Any],
        confidence_threshold: float = 0.7
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        审核并优化树结构
        
        Args:
            tree: PageIndex生成的树结构
            confidence_threshold: 执行建议的置信度阈值
        
        Returns:
            (优化后的tree, 审核报告)
        """
        if self.debug:
            print("\n" + "="*70)
            print("🔍 INTELLIGENT TREE AUDITOR V2")
            print("="*70)
        
        audit_report = {
            "phases": {},
            "summary": {},
            "final_tree": None
        }
        
        # Determine total phases
        total_phases = 5 if self.verifier else 4
        
        # ======== Phase 1: 文档分类 ========
        if self.debug:
            print("\n📋 Phase 1: Document Classification")
        
        # Send progress update
        if self.progress_callback:
            await self.progress_callback(
                "classification",
                1,
                total_phases,
                "正在识别文档类型...",
                10.0,
                None
            )
        
        classification = await self.classifier.classify(tree, self.pdf_path)
        audit_report["phases"]["classification"] = classification
        
        document_type = classification["type"]
        
        if self.debug:
            print(f"  ✅ Type: {document_type} ({classification['name']})")
            print(f"  Confidence: {classification['confidence']:.2%}")
        
        # Send phase 1 completion
        if self.progress_callback:
            await self.progress_callback(
                "classification",
                1,
                total_phases,
                f"文档类型识别完成: {classification.get('name', document_type)}",
                20.0,
                {"document_type": document_type, "confidence": classification['confidence']}
            )
        
        # ======== Phase 2: 生成审核建议 ========
        if self.debug:
            mode_name = "Progressive (5 rounds)" if self.mode == "progressive" else "Standard (1 round)"
            print(f"\n💡 Phase 2: Generate Audit Advice ({mode_name})")
        
        # Send progress update
        if self.progress_callback:
            mode_desc = "渐进式5轮审核" if self.mode == "progressive" else "标准审核"
            await self.progress_callback(
                "advice_generation",
                2,
                total_phases,
                f"正在生成审核建议 ({mode_desc})...",
                30.0,
                {"mode": self.mode}
            )
        
        if self.mode == "progressive":
            # 渐进式审核
            advice_result = await self.advisor.generate_progressive_advice(
                tree,
                document_type,
                classification
            )
            advice_list = advice_result.get("final_advice", [])
            audit_report["phases"]["advice_generation"] = {
                "mode": "progressive",
                "rounds": advice_result.get("rounds", []),
                "total_advice": len(advice_list),
                "summary": advice_result.get("summary", {}),
                "advice": advice_list
            }
            
            if self.debug:
                summary = advice_result.get("summary", {})
                by_action = summary.get("by_action", {})
                print(f"  ✅ Completed 5 rounds")
                print(f"  Total advice: {len(advice_list)}")
                print(f"  DELETE: {by_action.get('DELETE', 0)}, "
                      f"MODIFY_FORMAT: {by_action.get('MODIFY_FORMAT', 0)}, "
                      f"ADD: {by_action.get('ADD', 0)}, "
                      f"MODIFY_PAGE: {by_action.get('MODIFY_PAGE', 0)}")
            
            # Send phase 2 completion for progressive mode
            if self.progress_callback:
                summary = advice_result.get("summary", {})
                by_action = summary.get("by_action", {})
                await self.progress_callback(
                    "advice_generation",
                    2,
                    total_phases,
                    f"审核建议生成完成: 共 {len(advice_list)} 条建议",
                    50.0,
                    {"total_advice": len(advice_list), "by_action": by_action}
                )
        else:
            # 标准一次性审核
            advice_result = await self.advisor.generate_audit_advice(
                tree,
                document_type,
                classification
            )
            advice_list = advice_result.get("advice", [])
            audit_report["phases"]["advice_generation"] = {
                "mode": "standard",
                "total_advice": len(advice_list),
                "summary": advice_result.get("summary", {}),
                "advice": advice_list
            }
            
            if self.debug:
                summary = advice_result.get("summary", {})
                print(f"  ✅ Generated {len(advice_list)} pieces of advice")
                print(f"  DELETE: {summary.get('to_delete', 0)}, "
                      f"MODIFY_FORMAT: {summary.get('to_modify_format', 0)}, "
                      f"MODIFY_PAGE: {summary.get('to_modify_page', 0)}, "
                      f"ADD: {summary.get('to_add', 0)}")
            
            # Send phase 2 completion for standard mode
            if self.progress_callback:
                summary = advice_result.get("summary", {})
                await self.progress_callback(
                    "advice_generation",
                    2,
                    total_phases,
                    f"审核建议生成完成: 共 {len(advice_list)} 条建议",
                    50.0,
                    {"total_advice": len(advice_list), "summary": summary}
                )
        
        # ======== Phase 3: PDF核实验证 ========
        if self.verifier and advice_list:
            if self.debug:
                print("\n🔎 Phase 3: PDF Verification")
            
            # Send progress update
            if self.progress_callback:
                await self.progress_callback(
                    "verification",
                    3,
                    total_phases,
                    f"正在通过PDF验证建议 ({len(advice_list)} 条)...",
                    60.0,
                    None
                )
            
            verification_result = await self.verifier.verify_advice(advice_list, tree)
            verified_advice = verification_result["verified_advice"]
            
            audit_report["phases"]["verification"] = {
                "total": len(advice_list),
                "verified": verification_result["summary"]["verified"],
                "rejected": verification_result["summary"]["rejected"],
                "rate": verification_result["summary"]["verification_rate"]
            }
            
            if self.debug:
                print(f"  ✅ Verified: {verification_result['summary']['verified']}/{len(advice_list)}")
                print(f"  Rate: {verification_result['summary']['verification_rate']:.1%}")
            
            # Send phase 3 completion
            if self.progress_callback:
                await self.progress_callback(
                    "verification",
                    3,
                    total_phases,
                    f"PDF验证完成: {verification_result['summary']['verified']}/{len(advice_list)} 条通过",
                    70.0,
                    {
                        "verified": verification_result['summary']['verified'],
                        "rejected": verification_result['summary']['rejected'],
                        "rate": verification_result['summary']['verification_rate']
                    }
                )
        else:
            if self.debug:
                print("\n⏭️  Phase 3: Skipped (no PDF verifier)")
            verified_advice = advice_list
            audit_report["phases"]["verification"] = {
                "skipped": True,
                "reason": "No PDF path provided"
            }
            
            # Send phase 3 skipped
            if self.progress_callback:
                await self.progress_callback(
                    "verification",
                    3,
                    total_phases,
                    "PDF验证已跳过 (无PDF文件)",
                    70.0,
                    {"skipped": True}
                )
        
        # ======== Phase 4: 执行建议 ========
        if self.debug:
            print("\n⚙️  Phase 4: Execute Advice")
        
        # Send progress update
        phase_num = 4 if self.verifier else 3
        if self.progress_callback:
            await self.progress_callback(
                "execution",
                phase_num,
                total_phases,
                f"正在执行高置信度建议...",
                80.0,
                {"confidence_threshold": confidence_threshold}
            )
        
        execution_result = self.executor.execute_advice(
            tree,
            verified_advice,
            confidence_threshold
        )
        
        optimized_tree = execution_result["tree"]
        audit_report["phases"]["execution"] = {
            "summary": execution_result["summary"],
            "log": execution_result["execution_log"]
        }
        
        if self.debug:
            stats = execution_result["summary"]
            print(f"  ✅ Executed: {stats['executed']}/{stats['total_advice']}")
            print(f"  Changes: {stats['deleted_nodes']} deleted, "
                  f"{stats['modified_formats']} formats modified, "
                  f"{stats['modified_pages']} pages corrected")
        
        # Send phase 4 completion
        phase_num_final = 5 if self.verifier else 4
        if self.progress_callback:
            stats = execution_result["summary"]
            await self.progress_callback(
                "execution",
                phase_num,
                total_phases,
                f"建议执行完成: {stats['executed']}/{stats['total_advice']} 条已应用",
                90.0,
                {
                    "executed": stats['executed'],
                    "deleted_nodes": stats['deleted_nodes'],
                    "modified_formats": stats['modified_formats'],
                    "modified_pages": stats['modified_pages']
                }
            )
        
        # ======== Phase 5: 生成总结报告 ========
        if self.progress_callback:
            await self.progress_callback(
                "summary",
                phase_num_final,
                total_phases,
                "正在生成审核报告...",
                95.0,
                None
            )
        
        audit_report["summary"] = self._generate_summary(audit_report, tree, optimized_tree)
        audit_report["final_tree"] = optimized_tree
        
        if self.debug:
            print("\n" + "="*70)
            print("✅ AUDIT COMPLETE")
            print(f"Quality Score: {audit_report['summary'].get('quality_score', 0):.1f}/100")
            print("="*70 + "\n")
        
        # Send final completion
        if self.progress_callback:
            await self.progress_callback(
                "complete",
                phase_num_final,
                total_phases,
                "审核完成!",
                100.0,
                {
                    "quality_score": audit_report['summary'].get('quality_score', 0),
                    "total_suggestions": audit_report['summary'].get('total_suggestions', 0)
                }
            )
        
        return optimized_tree, audit_report
    
    def _generate_summary(
        self,
        audit_report: Dict,
        original_tree: Dict,
        optimized_tree: Dict
    ) -> Dict:
        """生成总结报告"""
        # 统计节点数量
        def count_nodes(tree):
            count = 0
            def traverse(node):
                nonlocal count
                count += 1
                for child in node.get("children", node.get("nodes", [])):
                    traverse(child)
            
            for root in tree.get("children", tree.get("structure", [])):
                traverse(root)
            return count
        
        original_count = count_nodes(original_tree)
        optimized_count = count_nodes(optimized_tree)
        
        execution = audit_report["phases"].get("execution", {}).get("summary", {})
        
        # 计算质量得分
        # 基础分60分，删除无效节点+20，修改格式+10，修正页码+10
        quality_score = 60
        if execution.get("deleted_nodes", 0) > 0:
            quality_score += min(20, execution["deleted_nodes"] * 4)
        if execution.get("modified_formats", 0) > 0:
            quality_score += min(10, execution["modified_formats"] * 3)
        if execution.get("modified_pages", 0) > 0:
            quality_score += min(10, execution["modified_pages"] * 5)
        
        return {
            "document_type": audit_report["phases"]["classification"]["type"],
            "document_type_confidence": audit_report["phases"]["classification"]["confidence"],
            "original_nodes": original_count,
            "optimized_nodes": optimized_count,
            "nodes_removed": original_count - optimized_count,
            "removal_rate": (original_count - optimized_count) / original_count if original_count > 0 else 0,
            "quality_score": min(100, quality_score),
            "changes_applied": {
                "deleted": execution.get("deleted_nodes", 0),
                "modified_format": execution.get("modified_formats", 0),
                "modified_page": execution.get("modified_pages", 0)
            },
            "recommendations": self._generate_recommendations(audit_report)
        }
    
    def _generate_recommendations(self, audit_report: Dict) -> List[str]:
        """生成改进建议"""
        recommendations = []
        
        execution = audit_report["phases"].get("execution", {}).get("summary", {})
        verification = audit_report["phases"].get("verification", {})
        
        # 基于执行结果生成建议
        if execution.get("deleted_nodes", 0) > 5:
            recommendations.append(
                "检测到大量无效节点被删除，建议优化TOC提取阶段以减少误识别"
            )
        
        if execution.get("modified_pages", 0) > 3:
            recommendations.append(
                "多个节点的页码范围需要修正，建议改进页面映射算法"
            )
        
        if verification.get("rejected", 0) > verification.get("verified", 0):
            recommendations.append(
                "较多建议未通过PDF验证，可能需要提高建议生成的准确性"
            )
        
        if not recommendations:
            recommendations.append("文档结构质量良好，无重大问题")
        
        return recommendations


# ========== 便捷函数 ==========

async def audit_tree_file_v2(
    tree_file_path: str,
    pdf_path: str,
    llm: LLMClient,
    output_path: Optional[str] = None,
    report_path: Optional[str] = None,
    mode: str = "progressive",  # "standard" or "progressive"
    confidence_threshold: float = 0.7,
    debug: bool = True
) -> Tuple[str, str]:
    """
    审核tree.json文件（V2版本）
    
    Args:
        tree_file_path: tree.json文件路径
        pdf_path: PDF文件路径
        llm: LLM客户端
        output_path: 输出文件路径（可选）
        report_path: 报告文件路径（可选）
        mode: 审核模式 - "progressive"(渐进式5轮) 或 "standard"(一次性)
        confidence_threshold: 置信度阈值
        debug: 是否打印调试信息
    
    Returns:
        (优化后的tree文件路径, 审核报告文件路径)
    """
    import os
    
    # 读取树文件
    with open(tree_file_path, 'r', encoding='utf-8') as f:
        tree = json.load(f)
    
    # 创建审核器
    auditor = TreeAuditorV2(llm=llm, pdf_path=pdf_path, mode=mode, debug=debug)
    
    # 执行审核
    optimized_tree, audit_report = await auditor.audit_and_optimize(
        tree,
        confidence_threshold=confidence_threshold
    )
    
    # 保存结果
    if output_path is None:
        base = tree_file_path.replace('.json', '')
        suffix = "_progressive" if mode == "progressive" else "_optimized"
        output_path = f"{base}{suffix}.json"
    
    if report_path is None:
        base = tree_file_path.replace('.json', '')
        suffix = "_progressive" if mode == "progressive" else "_v2"
        report_path = f"{base}_audit_report{suffix}.json"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(optimized_tree, f, ensure_ascii=False, indent=2)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(audit_report, f, ensure_ascii=False, indent=2)
    
    if debug:
        print(f"\n📄 Optimized tree: {output_path}")
        print(f"📊 Audit report: {report_path}")
    
    return output_path, report_path
