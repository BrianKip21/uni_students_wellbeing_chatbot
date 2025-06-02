#!/usr/bin/env python3
"""
Debug script to test Zoom OAuth authentication
"""
import os
import sys
from pathlib import Path
import base64

print("🔍 Zoom OAuth Debug Script")
print("=" * 50)

# Check current working directory
print(f"📂 Current working directory: {os.getcwd()}")

# Check if .env file exists
env_file = Path(".env")
print(f"📄 .env file exists: {env_file.exists()}")

if env_file.exists():
    print(f"📍 .env file location: {env_file.absolute()}")
    print(f"📏 .env file size: {env_file.stat().st_size} bytes")

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
print("\n🔍 OAuth Environment Variables Check")
print("-" * 38)

oauth_vars = ['ZOOM_ACCOUNT_ID', 'ZOOM_CLIENT_ID', 'ZOOM_CLIENT_SECRET', 'ZOOM_USER_EMAIL']

for var in oauth_vars:
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

# Test OAuth authentication
print("\n🔗 Testing Zoom OAuth Authentication")
print("-" * 37)

client_id = os.getenv('ZOOM_CLIENT_ID')
client_secret = os.getenv('ZOOM_CLIENT_SECRET')
account_id = os.getenv('ZOOM_ACCOUNT_ID')

if client_id and client_secret and account_id:
    try:
        import requests
        
        # Create base64 encoded authorization header
        credentials = f"{client_id}:{client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'account_credentials',
            'account_id': account_id
        }
        
        print("🔑 Requesting OAuth access token...")
        response = requests.post(
            'https://zoom.us/oauth/token',
            headers=headers,
            data=data,
            timeout=30
        )
        
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in', 0)
            
            print("✅ OAuth access token obtained successfully!")
            print(f"   Token length: {len(access_token)} characters")
            print(f"   Expires in: {expires_in} seconds")
            
            # Test API call with OAuth token
            print("\n🌐 Testing API call with OAuth token...")
            api_headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            api_response = requests.get(
                'https://api.zoom.us/v2/users/me',
                headers=api_headers,
                timeout=10
            )
            
            if api_response.status_code == 200:
                user_data = api_response.json()
                print("✅ Zoom API call successful!")
                print(f"   User email: {user_data.get('email', 'Unknown')}")
                print(f"   Account ID: {user_data.get('account_id', 'Unknown')}")
                print(f"   User type: {user_data.get('type', 'Unknown')}")
            else:
                print(f"❌ API call failed: {api_response.status_code}")
                print(f"   Response: {api_response.text}")
                
        else:
            print(f"❌ OAuth token request failed: {response.status_code}")
            print(f"   Response: {response.text}")
            
            if response.status_code == 400:
                print("\n💡 Common 400 errors:")
                print("   - Wrong grant_type (should be 'account_credentials')")
                print("   - Invalid account_id")
                print("   - App not activated")
            elif response.status_code == 401:
                print("\n💡 Common 401 errors:")
                print("   - Wrong client_id or client_secret")
                print("   - App credentials not properly encoded")
                print("   - App not published/activated")
            
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("   Install with: pip install requests")
    except Exception as e:
        print(f"❌ Error testing OAuth: {e}")
else:
    print("❌ Cannot test OAuth - missing credentials")
    missing = []
    if not client_id: missing.append('ZOOM_CLIENT_ID')
    if not client_secret: missing.append('ZOOM_CLIENT_SECRET')  
    if not account_id: missing.append('ZOOM_ACCOUNT_ID')
    print(f"   Missing: {', '.join(missing)}")

print("\n" + "=" * 50)
print("🎯 Summary")
if all(os.getenv(var) for var in oauth_vars):
    print("✅ All OAuth environment variables are loaded!")
    print("   If API calls failed, check your Zoom app settings.")
else:
    print("❌ Some OAuth environment variables are missing.")
    print("   Update your .env file with Server-to-Server OAuth credentials.")

print("\n📋 Next Steps:")
print("1. Create a Server-to-Server OAuth app at marketplace.zoom.us")
print("2. Add required scopes: meeting:write:admin, meeting:read:admin, user:read:admin")
print("3. Update your .env file with the new OAuth credentials")
print("4. Run this script again to verify the setup")