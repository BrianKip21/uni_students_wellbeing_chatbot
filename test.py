#!/usr/bin/env python3
"""
Simple test for Zoom meeting creation
"""
from dotenv import load_dotenv
load_dotenv()

import os
import base64
import requests
from datetime import datetime, timedelta

def test_meeting_creation():
    print("🧪 Testing Zoom Meeting Creation")
    print("=" * 35)
    
    # Get OAuth credentials
    client_id = os.getenv('ZOOM_CLIENT_ID')
    client_secret = os.getenv('ZOOM_CLIENT_SECRET')
    account_id = os.getenv('ZOOM_ACCOUNT_ID')
    
    if not all([client_id, client_secret, account_id]):
        print("❌ Missing OAuth credentials")
        return False
    
    try:
        # Get OAuth token
        print("🔑 Getting access token...")
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
        
        response = requests.post(
            'https://zoom.us/oauth/token',
            headers=headers,
            data=data,
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"❌ Token request failed: {response.status_code}")
            return False
        
        access_token = response.json()['access_token']
        print("✅ Access token obtained")
        
        # Create a test meeting
        print("\n🎯 Creating test meeting...")
        
        meeting_data = {
            'topic': 'Test Therapy Session - Integration Check',
            'type': 2,  # Scheduled meeting
            'start_time': (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S'),
            'duration': 60,
            'timezone': 'America/New_York',
            'password': '123456',
            'agenda': 'Test meeting for Zoom integration verification',
            'settings': {
                'host_video': True,
                'participant_video': True,
                'join_before_host': False,
                'mute_upon_entry': True,
                'waiting_room': True,
                'approval_type': 0,
                'audio': 'both',
                'auto_recording': 'none'
            }
        }
        
        api_headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        meeting_response = requests.post(
            'https://api.zoom.us/v2/users/me/meetings',
            json=meeting_data,
            headers=api_headers,
            timeout=30
        )
        
        if meeting_response.status_code == 201:
            meeting_info = meeting_response.json()
            print("✅ Meeting created successfully!")
            print(f"   Meeting ID: {meeting_info['id']}")
            print(f"   Topic: {meeting_info['topic']}")
            print(f"   Join URL: {meeting_info['join_url']}")
            print(f"   Start URL: {meeting_info['start_url']}")
            print(f"   Password: {meeting_info.get('password', 'None')}")
            
            # Test meeting cleanup
            print(f"\n🧹 Cleaning up test meeting...")
            delete_response = requests.delete(
                f"https://api.zoom.us/v2/meetings/{meeting_info['id']}",
                headers=api_headers,
                timeout=30
            )
            
            if delete_response.status_code == 204:
                print("✅ Test meeting deleted successfully")
            else:
                print(f"⚠️  Could not delete meeting: {delete_response.status_code}")
            
            print(f"\n🎉 ZOOM INTEGRATION IS WORKING PERFECTLY!")
            print("   Your therapy appointment system can now create Zoom meetings.")
            return True
            
        else:
            print(f"❌ Meeting creation failed: {meeting_response.status_code}")
            print(f"   Response: {meeting_response.text}")
            
            if meeting_response.status_code == 400:
                error_data = meeting_response.json()
                if 'scopes' in error_data.get('message', '').lower():
                    print("\n💡 You need to add the 'meeting:write:user' scope to your Zoom app")
                    print("   1. Go to marketplace.zoom.us/develop/apps")
                    print("   2. Open your app → Scopes tab")
                    print("   3. Add 'meeting:write:user' scope")
                    print("   4. Save and activate your app")
            
            return False
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_meeting_creation()
    if success:
        print("\n🚀 Ready to integrate with your therapy system!")
    else:
        print("\n🔧 Please fix the issues above and try again.")