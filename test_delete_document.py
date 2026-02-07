"""
测试文档删除功能 - 验证是否清理所有相关文件

运行方式：
    python test_delete_document.py <document_id>

示例：
    python test_delete_document.py d258c641-3ab6-4ae9-b8b4-71126669cdbc
"""

import sys
import os
from pathlib import Path

# 设置输出编码
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from api.storage import StorageService


def test_delete_document(document_id: str):
    """
    测试删除文档功能
    
    Args:
        document_id: 文档 UUID
    """
    print(f"=" * 70)
    print(f"测试删除文档: {document_id}")
    print(f"=" * 70)
    
    storage = StorageService()
    
    # 查找所有相关文件
    print("\n📋 删除前检查文件:")
    
    files_before = {
        "upload_pdf": storage.uploads_dir / f"{document_id}.pdf",
        "upload_md": storage.uploads_dir / f"{document_id}.md",
        "tree": storage.parsed_dir / f"{document_id}_tree.json",
        "stats": storage.parsed_dir / f"{document_id}_stats.json",
        "audit_report": storage.parsed_dir / f"{document_id}_audit_report.json",
        "debug_log": storage.data_dir.parent / "debug_logs" / f"{document_id}.log",
    }
    
    # 查找所有 audit backup 文件
    audit_backups = list(storage.parsed_dir.glob(f"{document_id}_audit_backup_*.json"))
    
    print("\n检查的文件:")
    for name, path in files_before.items():
        exists = "✓ 存在" if path.exists() else "✗ 不存在"
        print(f"  {name:20s}: {exists:10s} - {path.name}")
    
    if audit_backups:
        print(f"\n  找到 {len(audit_backups)} 个审计备份文件:")
        for backup in audit_backups:
            print(f"    - {backup.name}")
    
    # 执行删除
    print(f"\n🗑️  执行删除操作...")
    results = storage.delete_all_document_data(document_id)
    
    print(f"\n删除结果:")
    for key, value in results.items():
        status = "✓ 成功" if value else "✗ 无文件"
        print(f"  {key:30s}: {status}")
    
    # 验证删除后状态
    print(f"\n📋 删除后验证:")
    
    remaining_files = []
    for name, path in files_before.items():
        if path.exists():
            remaining_files.append(f"{name}: {path.name}")
            print(f"  ⚠️  {name:20s}: 仍然存在 - {path.name}")
    
    # 检查是否还有 audit backup 文件
    audit_backups_after = list(storage.parsed_dir.glob(f"{document_id}_audit_backup_*.json"))
    if audit_backups_after:
        print(f"\n  ⚠️  仍有 {len(audit_backups_after)} 个审计备份文件未删除:")
        for backup in audit_backups_after:
            print(f"    - {backup.name}")
            remaining_files.append(f"audit_backup: {backup.name}")
    
    # 总结
    print(f"\n" + "=" * 70)
    if remaining_files:
        print(f"❌ 测试失败 - 以下文件未被删除:")
        for file in remaining_files:
            print(f"  - {file}")
    else:
        print(f"✅ 测试成功 - 所有相关文件已删除")
    print(f"=" * 70)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python test_delete_document.py <document_id>")
        print("示例: python test_delete_document.py d258c641-3ab6-4ae9-b8b4-71126669cdbc")
        sys.exit(1)
    
    document_id = sys.argv[1]
    test_delete_document(document_id)
