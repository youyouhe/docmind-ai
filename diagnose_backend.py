"""
Quick diagnostic script to check backend health
"""
import sys
import time
import requests

# Fix Windows console encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

API_URLS = [
    "http://localhost:8003",
    "http://127.0.0.1:8003",
    "http://192.168.8.107:8003"
]

def check_health(base_url: str, timeout: int = 3):
    """Check health endpoint"""
    url = f"{base_url}/health"
    print(f"\n{'='*60}")
    print(f"Testing: {url}")
    print(f"{'='*60}")
    
    try:
        start = time.time()
        response = requests.get(url, timeout=timeout)
        elapsed = time.time() - start
        
        print(f"✓ Status: {response.status_code}")
        print(f"✓ Response time: {elapsed:.2f}s")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Service status: {data.get('status', 'unknown')}")
            print(f"✓ Version: {data.get('version', 'unknown')}")
            print(f"✓ Provider: {data.get('provider', 'unknown')}")
            print(f"✓ Model: {data.get('model', 'unknown')}")
            return True
        else:
            print(f"✗ Error: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"✗ Timeout after {timeout}s - backend is not responding")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"✗ Connection error: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    print("BidSmart Backend Health Check")
    print("=" * 60)
    
    success_count = 0
    for url in API_URLS:
        if check_health(url, timeout=5):
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"Summary: {success_count}/{len(API_URLS)} endpoints working")
    print(f"{'='*60}")
    
    if success_count == 0:
        print("\n⚠ PROBLEM DETECTED:")
        print("  - Backend is not responding")
        print("  - Please check:")
        print("    1. Is the backend service running?")
        print("       Run: cd lib/docmind-ai && bash start_server.sh")
        print("    2. Check .env file has valid API keys")
        print("    3. Check lib/docmind-ai/data/documents.db exists")
        print("    4. Check for errors in backend console")
        sys.exit(1)
    elif success_count < len(API_URLS):
        print("\n⚠ PARTIAL SUCCESS:")
        print("  - Some endpoints are not accessible")
        print("  - Check firewall/network settings")
    else:
        print("\n✓ ALL ENDPOINTS WORKING")
        sys.exit(0)
