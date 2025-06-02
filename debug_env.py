#!/usr/bin/env python3
"""
Debug script to test environment variable loading
"""
import os
import sys
from pathlib import Path

print("🔍 Environment Variable Debug Script")
print("=" * 50)

# Check current working directory
print(f"📂 Current working directory: {os.getcwd()}")

# Check if .env file exists
env_file = Path(".env")
print(f"📄 .env file exists: {env_file.exists()}")

if env_file.exists():
    print(f"📍 .env file location: {env_file.absolute()}")
    print(f"📏 .env file size: {env_file.stat().st_size} bytes")
    
    # Read and display .env file content (without showing sensitive values)
    try:
        with open(".env", "r") as f:
            content = f.read()
            lines = content.strip().split('\n')
            print(f"📝 .env file has {len(lines)} lines")
            
            for i, line in enumerate(lines, 1):
                if line.strip() and not line.startswith('#'):
                    if '=' in line:
                        key, _ = line.split('=', 1)
                        print(f"   Line {i}: {key.strip()}=***")
                    else:
                        print(f"   Line {i}: {line} (no = found)")
                elif line.strip():
                    print(f"   Line {i}: {line} (comment)")
    except Exception as e:
        print(f"❌ Error reading .env file: {e}")

print("\n🐍 Python Environment Check")
print("-" * 30)

# Check if python-dotenv is installed
try:
    import dotenv
    try:
        version = dotenv.__version__
    except AttributeError:
        version = "installed (version unknown)"
    print(f"✅ python-dotenv installed: {version}")
except ImportError:
    print("❌ python-dotenv NOT installed")
    print("   Install with: pip install python-dotenv")
    sys.exit(1)

# Try loading .env file
print("\n🔄 Loading .env file...")
try:
    from dotenv import load_dotenv
    result = load_dotenv()
    print(f"✅ load_dotenv() returned: {result}")
except Exception as e:
    print(f"❌ Error loading .env: {e}")
    sys.exit(1)

# Check what environment variables are actually set
print("\n🔍 Environment Variables Check")
print("-" * 35)

required_vars = ['ZOOM_ACCOUNT_ID', 'ZOOM_API_KEY', 'ZOOM_API_SECRET', 'ZOOM_USER_EMAIL']

for var in required_vars:
    value = os.getenv(var)
    if value:
        # Show first 3 and last 3 characters for security
        if len(value) > 6:
            masked = f"{value[:3]}...{value[-3:]}"
        else:
            masked = "***"
        print(f"✅ {var}: {masked} (length: {len(value)})")
    else:
        print(f"❌ {var}: Not set")

# Test a simple Zoom API connection
print("\n🔗 Testing Zoom API Connection")
print("-" * 32)

api_key = os.getenv('ZOOM_API_KEY')
api_secret = os.getenv('ZOOM_API_SECRET')

if api_key and api_secret:
    try:
        import jwt
        import time
        
        # Generate JWT token
        payload = {
            'iss': api_key,
            'exp': int(time.time() + 3600),
            'iat': int(time.time()),
            'alg': 'HS256'
        }
        
        token = jwt.encode(payload, api_secret, algorithm='HS256')
        print("✅ JWT token generated successfully")
        print(f"   Token length: {len(token)} characters")
        
        # Test API call
        import requests
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        print("🌐 Testing API call to Zoom...")
        response = requests.get(
            'https://api.zoom.us/v2/users/me',
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            user_data = response.json()
            print("✅ Zoom API connection successful!")
            print(f"   User email: {user_data.get('email', 'Unknown')}")
            print(f"   Account ID: {user_data.get('account_id', 'Unknown')}")
        else:
            print(f"❌ Zoom API call failed: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("   Install with: pip install PyJWT requests")
    except Exception as e:
        print(f"❌ Error testing Zoom API: {e}")
else:
    print("❌ Cannot test API - missing credentials")

print("\n" + "=" * 50)
print("🎯 Summary")
if all(os.getenv(var) for var in required_vars):
    print("✅ All environment variables are loaded correctly!")
    print("   Your .env setup is working properly.")
else:
    print("❌ Some environment variables are missing.")
    print("   Check your .env file format and content.")