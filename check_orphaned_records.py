"""
检查孤立的数据库记录（文件不存在但数据库记录仍存在）
"""
import sys
from pathlib import Path

# Fix Unicode encoding on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, str(Path(__file__).parent))

from api.database import DatabaseManager, AuditBackup

def check_orphaned_records():
    """检查孤立的审计备份记录"""
    print("=" * 70)
    print("孤立记录检查")
    print("=" * 70)
    
    # 初始化数据库
    db = DatabaseManager()
    db.init_db()
    
    data_dir = Path(__file__).parent / "data"
    
    print(f"\n数据目录: {data_dir}")
    print(f"存在: {data_dir.exists()}")
    
    with db.get_session() as session:
        backups = session.query(AuditBackup).all()
        
        print(f"\n总备份记录数: {len(backups)}")
        
        orphaned = []
        valid = []
        
        for backup in backups:
            # 检查文件是否存在
            file_path = data_dir / backup.backup_path
            
            if file_path.exists():
                valid.append(backup)
            else:
                orphaned.append(backup)
        
        print(f"\n✓ 有效记录（文件存在）: {len(valid)}")
        print(f"✗ 孤立记录（文件不存在）: {len(orphaned)}")
        
        if orphaned:
            print(f"\n孤立记录详情:")
            print("-" * 70)
            
            # 按文档ID分组
            orphaned_by_doc = {}
            for backup in orphaned:
                if backup.doc_id not in orphaned_by_doc:
                    orphaned_by_doc[backup.doc_id] = []
                orphaned_by_doc[backup.doc_id].append(backup)
            
            for doc_id, doc_backups in orphaned_by_doc.items():
                print(f"\n文档: {doc_id}")
                print(f"  孤立备份数: {len(doc_backups)}")
                for backup in doc_backups:
                    print(f"    - Backup ID: {backup.backup_id}")
                    print(f"      Path: {backup.backup_path}")
                    print(f"      Created: {backup.created_at}")
        
        if len(orphaned) > 0:
            print("\n" + "=" * 70)
            print("问题说明:")
            print("=" * 70)
            print("""
这些孤立记录表明：
1. 文件已被删除（通过 storage.delete_all_document_data()）
2. 但数据库记录仍然存在
3. 原因：外键约束是 NO ACTION 而不是 CASCADE

解决方案：
1. 修复数据库约束为 CASCADE（需要重新创建表或迁移）
2. 在删除时显式删除 audit_backup 记录（临时方案）

推荐做法：
- 添加显式删除 audit_backup 记录到 delete_document 流程
- 这样即使数据库约束有问题，也能保证清理干净
            """)

if __name__ == "__main__":
    check_orphaned_records()
