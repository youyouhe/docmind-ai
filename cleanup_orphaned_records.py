"""
清理孤立的审计备份数据库记录
这个脚本会删除那些文件已经不存在但数据库记录仍然存在的审计备份记录
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

def cleanup_orphaned_records():
    """清理孤立的审计备份记录"""
    print("=" * 70)
    print("孤立记录清理工具")
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
        
        if not orphaned:
            print("\n✓ 没有孤立记录，数据库状态良好！")
            return
        
        # 按文档ID分组显示
        orphaned_by_doc = {}
        for backup in orphaned:
            if backup.doc_id not in orphaned_by_doc:
                orphaned_by_doc[backup.doc_id] = []
            orphaned_by_doc[backup.doc_id].append(backup)
        
        print(f"\n孤立记录按文档分组:")
        for doc_id, doc_backups in orphaned_by_doc.items():
            print(f"  - {doc_id}: {len(doc_backups)} 条记录")
        
        # 询问是否清理
        print("\n" + "=" * 70)
        print("⚠️  警告：即将删除这些孤立的数据库记录")
        print("=" * 70)
        
        response = input(f"\n是否删除 {len(orphaned)} 条孤立记录？ (y/n): ")
        
        if response.lower() not in ['y', 'yes']:
            print("\n取消操作")
            return
        
        # 执行删除
        print(f"\n开始删除 {len(orphaned)} 条孤立记录...")
        
        deleted_count = 0
        for backup in orphaned:
            session.delete(backup)
            deleted_count += 1
        
        session.commit()
        
        print(f"✓ 成功删除 {deleted_count} 条孤立记录")
        
        # 验证清理结果
        remaining_backups = session.query(AuditBackup).all()
        print(f"\n清理后剩余记录数: {len(remaining_backups)}")
        
        # 验证剩余的都是有效记录
        remaining_orphaned = 0
        for backup in remaining_backups:
            file_path = data_dir / backup.backup_path
            if not file_path.exists():
                remaining_orphaned += 1
        
        if remaining_orphaned == 0:
            print("✓ 所有剩余记录都有对应的文件，清理完成！")
        else:
            print(f"⚠️  仍有 {remaining_orphaned} 条孤立记录")

if __name__ == "__main__":
    cleanup_orphaned_records()
