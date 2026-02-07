"""
检查并安装缺失的PDF解析库
"""
import sys
import subprocess

# Fix Unicode encoding on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def check_library(name, import_name=None):
    """检查库是否已安装"""
    import_name = import_name or name
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False

def install_library(name):
    """安装库"""
    print(f"\n正在安装 {name}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", name])
        print(f"✓ {name} 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {name} 安装失败: {e}")
        return False

def main():
    print("=" * 70)
    print("PDF解析库依赖检查")
    print("=" * 70)
    
    # 定义需要的库
    libraries = [
        ("pdfplumber", "pdfplumber"),
        ("pdfminer.six", "pdfminer"),
        ("pypdfium2", "pypdfium2"),
        ("PyMuPDF", "fitz"),
        ("PyPDF2", "PyPDF2"),
    ]
    
    missing = []
    installed = []
    
    print("\n检查已安装的库:")
    print("-" * 70)
    
    for pkg_name, import_name in libraries:
        if check_library(pkg_name, import_name):
            print(f"✓ {pkg_name:20s} - 已安装")
            installed.append(pkg_name)
        else:
            print(f"✗ {pkg_name:20s} - 未安装")
            missing.append(pkg_name)
    
    if not missing:
        print("\n" + "=" * 70)
        print("✓ 所有PDF解析库都已安装！")
        print("=" * 70)
        
        print("\nPDF解析优先级:")
        print("  1️⃣  pdfplumber (表格检测最佳)")
        print("  2️⃣  pdfminer.six (文本质量最佳)")
        print("  3️⃣  pypdfium2 (Chrome引擎)")
        print("  最终回退: PyMuPDF (总是可用)")
        return
    
    print("\n" + "=" * 70)
    print(f"发现 {len(missing)} 个缺失的库")
    print("=" * 70)
    
    # 询问是否安装
    response = input(f"\n是否安装缺失的库? (y/n): ")
    
    if response.lower() not in ['y', 'yes']:
        print("\n取消安装")
        return
    
    # 安装缺失的库
    print("\n开始安装...")
    success_count = 0
    
    for pkg_name in missing:
        if install_library(pkg_name):
            success_count += 1
    
    print("\n" + "=" * 70)
    print("安装完成")
    print("=" * 70)
    print(f"✓ 成功: {success_count}/{len(missing)}")
    print(f"✗ 失败: {len(missing) - success_count}/{len(missing)}")
    
    if success_count == len(missing):
        print("\n✓ 所有库都已成功安装！")
        print("\nPDF解析优先级:")
        print("  1️⃣  pdfplumber (表格检测最佳)")
        print("  2️⃣  pdfminer.six (文本质量最佳)")
        print("  3️⃣  pypdfium2 (Chrome引擎)")
        print("  最终回退: PyMuPDF (总是可用)")
    else:
        print("\n⚠️  部分库安装失败，但系统仍可使用回退策略")

if __name__ == "__main__":
    main()
