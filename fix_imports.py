"""
Fix absolute imports to relative imports in pageindex_v2
将 pageindex_v2 中的绝对导入改为相对导入，以便作为 package 使用
"""

import os
import re

PAGEINDEX_V2_DIR = r"D:\BidSmart-Index\lib\docmind-ai\pageindex_v2"

# 导入替换规则
REPLACEMENTS = [
    # core imports
    (r'^from core\.', 'from ..core.'),
    (r'^import core\.', 'from .. import core.'),
    
    # phases imports  
    (r'^from phases\.', 'from ..phases.'),
    (r'^import phases\.', 'from .. import phases.'),
    
    # utils imports
    (r'^from utils\.', 'from ..utils.'),
    (r'^import utils\.', 'from .. import utils.'),
]

# main.py 特殊处理（它在根目录，不需要 ..）
MAIN_PY_REPLACEMENTS = [
    (r'^from core\.', 'from .core.'),
    (r'^from phases\.', 'from .phases.'),
    (r'^from utils\.', 'from .utils.'),
]


def fix_file(file_path, is_main=False):
    """修复单个文件的导入"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    replacements = MAIN_PY_REPLACEMENTS if is_main else REPLACEMENTS
    
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    if content != original:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False


def main():
    """批量修复所有Python文件"""
    fixed_count = 0
    
    # 修复 phases/ 目录
    phases_dir = os.path.join(PAGEINDEX_V2_DIR, 'phases')
    for filename in os.listdir(phases_dir):
        if filename.endswith('.py') and filename != '__init__.py':
            file_path = os.path.join(phases_dir, filename)
            if fix_file(file_path):
                print(f"[OK] Fixed: {filename}")
                fixed_count += 1
    
    # 修复 utils/ 目录
    utils_dir = os.path.join(PAGEINDEX_V2_DIR, 'utils')
    if os.path.exists(utils_dir):
        for filename in os.listdir(utils_dir):
            if filename.endswith('.py') and filename != '__init__.py':
                file_path = os.path.join(utils_dir, filename)
                if fix_file(file_path):
                    print(f"[OK] Fixed: {filename}")
                    fixed_count += 1
    
    # 修复 main.py（特殊处理）
    main_py = os.path.join(PAGEINDEX_V2_DIR, 'main.py')
    if fix_file(main_py, is_main=True):
        print(f"[OK] Fixed: main.py")
        fixed_count += 1
    
    print(f"\n[DONE] Total fixed: {fixed_count} files")


if __name__ == '__main__':
    main()
