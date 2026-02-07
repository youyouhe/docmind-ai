"""
检查数据库中的审计备份记录管理情况
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
from sqlalchemy import inspect

def check_audit_backup_management():
    """检查审计备份的数据库管理情况"""
    print("=" * 70)
    print("审计备份数据库管理情况检查")
    print("=" * 70)
    
    # 初始化数据库
    db = DatabaseManager()
    db.init_db()
    
    # 检查表结构
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    
    print(f"\n📋 数据库表列表:")
    for table in tables:
        print(f"  - {table}")
    
    # 检查 audit_backups 表是否存在
    if 'audit_backups' in tables:
        print(f"\n✓ audit_backups 表存在")
        
        # 检查表结构
        print(f"\n📊 audit_backups 表结构:")
        columns = inspector.get_columns('audit_backups')
        for col in columns:
            print(f"  - {col['name']:20s} {col['type']}")
        
        # 检查外键约束
        print(f"\n🔗 audit_backups 外键约束:")
        foreign_keys = inspector.get_foreign_keys('audit_backups')
        for fk in foreign_keys:
            print(f"  - {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")
            print(f"    ondelete: {fk.get('ondelete', 'NO ACTION')}")
        
        # 检查现有备份记录
        print(f"\n📦 现有审计备份记录:")
        with db.get_session() as session:
            backup_count = session.query(AuditBackup).count()
            print(f"  总数: {backup_count}")
            
            if backup_count > 0:
                # 显示前 5 条记录
                backups = session.query(AuditBackup).limit(5).all()
                print(f"\n  最近的备份记录 (最多显示 5 条):")
                for backup in backups:
                    print(f"    - Backup ID: {backup.backup_id}")
                    print(f"      Document: {backup.doc_id}")
                    print(f"      Path: {backup.backup_path}")
                    print(f"      Created: {backup.created_at}")
                    print()
    else:
        print(f"\n✗ audit_backups 表不存在")
    
    print("=" * 70)
    print("级联删除分析:")
    print("=" * 70)
    
    # 分析级联删除机制
    if 'audit_backups' in tables:
        foreign_keys = inspector.get_foreign_keys('audit_backups')
        
        for fk in foreign_keys:
            col = fk['constrained_columns'][0]
            ref_table = fk['referred_table']
            ondelete = fk.get('ondelete', 'NO ACTION')
            
            print(f"\n{col} -> {ref_table}:")
            print(f"  ondelete: {ondelete}")
            
            if ondelete == 'CASCADE':
                print(f"  ✓ 删除 {ref_table} 时会自动删除 audit_backups 记录")
            else:
                print(f"  ⚠️  删除 {ref_table} 时需要手动删除 audit_backups 记录")
    
    print("\n" + "=" * 70)
    print("问题总结:")
    print("=" * 70)
    
    print("""
当前情况：
1. ✓ audit_backups 表存在，用于记录审计备份
2. ✓ 外键约束设置了 CASCADE 删除
3. ? 删除文档时，数据库记录是否被正确清理？

需要验证：
- 删除文档时，storage.delete_all_document_data() 会删除文件
- 删除文档时，db.delete_document() 会级联删除 audit_backups 记录（理论上）
- 但是否存在孤立记录（文件已删除但数据库记录仍存在）？
    """)

if __name__ == "__main__":
    check_audit_backup_management()
