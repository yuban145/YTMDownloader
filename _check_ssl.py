"""SSL diagnostic script"""
import ssl, socket, os, sys

print("=== SSL Diagnostics ===")

# 1. Test raw SSL connection to Google
print("\n1. Raw SSL to google.com:443")
try:
    ctx = ssl.create_default_context()
    with socket.create_connection(("google.com", 443), timeout=8) as sock:
        with ctx.wrap_socket(sock, server_hostname="google.com") as ssock:
            print(f"   OK - version={ssock.version()}, cipher={ssock.cipher()[0]}")
except Exception as e:
    print(f"   FAILED - {type(e).__name__}: {e}")

# 2. Test SSL to music.youtube.com
print("\n2. Raw SSL to music.youtube.com:443")
try:
    ctx = ssl.create_default_context()
    with socket.create_connection(("music.youtube.com", 443), timeout=8) as sock:
        with ctx.wrap_socket(sock, server_hostname="music.youtube.com") as ssock:
            print(f"   OK - version={ssock.version()}, cipher={ssock.cipher()[0]}")
except Exception as e:
    print(f"   FAILED - {type(e).__name__}: {e}")

# 3. Check certifi
print("\n3. certifi package:")
try:
    import certifi
    print(f"   Installed: {certifi.__version__}")
    print(f"   Location: {certifi.where()}")
except ImportError:
    print("   NOT INSTALLED")

# 4. Check env vars
print("\n4. Environment:")
for var in ["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY"]:
    val = os.environ.get(var, "")
    print(f"   {var}={val if val else '(not set)'}")

# 5. Test requests
print("\n5. requests to music.youtube.com:")
try:
    import requests
    r = requests.get("https://music.youtube.com", timeout=8)
    print(f"   OK - status={r.status_code}")
except Exception as e:
    print(f"   FAILED - {type(e).__name__}: {e}")

# 6. Check Python SSL module
print("\n6. Python SSL module:")
print(f"   OPENSSL_VERSION: {ssl.OPENSSL_VERSION}")
print(f"   Default verify paths: {ssl.get_default_verify_paths()}")

print("\n=== DONE ===")
