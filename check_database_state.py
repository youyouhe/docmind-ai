"""
检查当前数据库中的文档和审计备份记录
"""
import sys
from pathlib import Path

# Fix Unicode encoding on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, str(Path(__file__).parent))

from api.database import DatabaseManager, Document, AuditBackup

def check_database_state():
    """检查数据库当前状态"""
    print("=" * 70)
    print("数据库当前状态")
    print("=" * 70)
    
    db = DatabaseManager()
    db.init_db()
    
    with db.get_session() as session:
        # 检查文档
        documents = session.query(Document).all()
        print(f"\n📄 文档总数: {len(documents)}")
        
        if documents:
            print("\n文档列表 (最多显示 5 个):")
            for doc in documents[:5]:
                print(f"  - ID: {doc.id}")
                print(f"    文件名: {doc.filename}")
                print(f"    状态: {doc.status}")
                print(f"    创建时间: {doc.created_at}")
                print()
        
        # 检查审计备份
        backups = session.query(AuditBackup).all()
        print(f"\n📦 审计备份记录总数: {len(backups)}")
        
        if backups:
            # 按文档分组
            backups_by_doc = {}
            for backup in backups:
                if backup.doc_id not in backups_by_doc:
                    backups_by_doc[backup.doc_id] = []
                backups_by_doc[backup.doc_id].append(backup)
            
            print(f"\n按文档分组:")
            for doc_id, doc_backups in backups_by_doc.items():
                print(f"  - {doc_id}: {len(doc_backups)} 条备份")
    
    print("\n" + "=" * 70)
    print("测试建议:")
    print("=" * 70)
    
    if len(documents) > 0 and len(backups) > 0:
        # 找到有备份的文档
        with db.get_session() as session:
            for doc in documents:
                backup_count = session.query(AuditBackup).filter(
                    AuditBackup.doc_id == doc.id
                ).count()
                if backup_count > 0:
                    print(f"""
找到可用于测试的文档：
  文档ID: {doc.id}
  文件名: {doc.filename}
  备份数: {backup_count}

测试命令：
  python test_delete_document.py {doc.id}

这将测试：
  1. 删除所有文件（上传文件、解析结果、审计备份、调试日志）
  2. 删除数据库记录（文档记录和 {backup_count} 条审计备份记录）
  3. 验证没有孤立记录
                    """)
                    break
    elif len(documents) > 0:
        doc = documents[0]
        print(f"""
找到文档但没有审计备份：
  文档ID: {doc.id}
  文件名: {doc.filename}

测试命令：
  python test_delete_document.py {doc.id}

建议：
  先上传新文档并进行审计，生成审计备份后再测试删除功能
        """)
    else:
        print("""
数据库中没有文档记录。

建议：
  1. 上传一个文档
  2. 进行解析和审计（生成审计备份）
  3. 然后测试删除功能
        """)

if __name__ == "__main__":
    check_database_state()
