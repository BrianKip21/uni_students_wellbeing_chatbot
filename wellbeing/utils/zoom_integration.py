# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

import os
import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
import time
import uuid
import base64

logger = logging.getLogger(__name__)

class ZoomMeetingManager:
    """Manages Zoom meeting creation for therapy appointments using OAuth"""
    
    def __init__(self):
        # OAuth credentials (new method)
        self.client_id = os.getenv('ZOOM_CLIENT_ID')
        self.client_secret = os.getenv('ZOOM_CLIENT_SECRET')
        self.account_id = os.getenv('ZOOM_ACCOUNT_ID')
        self.user_email = os.getenv('ZOOM_USER_EMAIL')
        
        # API endpoints
        self.base_url = 'https://api.zoom.us/v2'
        self.oauth_url = 'https://zoom.us/oauth/token'
        
        # Token caching
        self._access_token = None
        self._token_expires_at = 0
        
        if not all([self.client_id, self.client_secret, self.account_id]):
            logger.warning("Zoom OAuth credentials not configured - using fallback mode")
    
    def get_access_token(self) -> Optional[str]:
        """Get OAuth access token for Zoom API authentication"""
        try:
            # Return cached token if still valid
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token
            
            # Create base64 encoded authorization header
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'account_credentials',
                'account_id': self.account_id
            }
            
            response = requests.post(
                self.oauth_url,
                headers=headers,
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self._access_token = token_data['access_token']
                
                # Set expiration time (subtract 5 minutes for safety)
                expires_in = token_data.get('expires_in', 3600)
                self._token_expires_at = time.time() + expires_in - 300
                
                return self._access_token
            else:
                logger.error(f"OAuth token request failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting OAuth access token: {str(e)}")
            return None
    
    def create_therapy_meeting(self, 
                             appointment_data: Dict[str, Any],
                             student_email: str = None,
                             therapist_email: str = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Create a Zoom meeting for therapy appointment
        
        Args:
            appointment_data: Dictionary containing appointment details
            student_email: Student's email (optional)
            therapist_email: Therapist's email (optional)
            
        Returns:
            Tuple of (success: bool, meeting_info: dict)
        """
        try:
            if not all([self.client_id, self.client_secret, self.account_id]):
                return self._create_fallback_meeting(appointment_data)
            
            # Get OAuth access token
            token = self.get_access_token()
            if not token:
                return self._create_fallback_meeting(appointment_data)
            
            # Prepare meeting data
            meeting_data = self._prepare_meeting_data(appointment_data, student_email, therapist_email)
            
            # Create meeting via Zoom API
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Use 'me' or the configured user email
            user_id = self.user_email if self.user_email else 'me'
            
            response = requests.post(
                f'{self.base_url}/users/{user_id}/meetings',
                json=meeting_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 201:
                meeting_response = response.json()
                
                meeting_info = {
                    'zoom_meeting_id': meeting_response['id'],
                    'meet_link': meeting_response['join_url'],
                    'host_link': meeting_response['start_url'],
                    'meeting_password': meeting_response.get('password', ''),
                    'dial_in': self._format_dial_in_info(meeting_response),
                    'platform': 'Zoom',
                    'meeting_uuid': meeting_response.get('uuid'),
                    'created_method': 'zoom_oauth'
                }
                
                logger.info(f"Created Zoom meeting: {meeting_response['id']}")
                return True, meeting_info
                
            else:
                logger.error(f"Zoom API error: {response.status_code} - {response.text}")
                return self._create_fallback_meeting(appointment_data)
                
        except Exception as e:
            logger.error(f"Error creating Zoom meeting: {str(e)}")
            return self._create_fallback_meeting(appointment_data)
    
    def _prepare_meeting_data(self, appointment_data: Dict[str, Any], 
                            student_email: str = None, 
                            therapist_email: str = None) -> Dict[str, Any]:
        """Prepare meeting data for Zoom API"""
        
        appointment_time = appointment_data.get('datetime', datetime.now() + timedelta(hours=1))
        crisis_level = appointment_data.get('crisis_level', 'normal')
        
        # Format topic
        if crisis_level == 'high':
            topic = f"🚨 Priority Therapy Session - {appointment_time.strftime('%B %d, %Y')}"
        else:
            topic = f"Therapy Session - {appointment_time.strftime('%B %d, %Y')}"
        
        # Prepare attendee list
        attendees = []
        if student_email:
            attendees.append({'email': student_email})
        if therapist_email:
            attendees.append({'email': therapist_email})
        
        meeting_data = {
            'topic': topic,
            'type': 2,  # Scheduled meeting
            'start_time': appointment_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'duration': 60,  # 60 minutes
            'timezone': 'America/New_York',
            'password': self._generate_meeting_password(),
            'agenda': self._create_meeting_agenda(appointment_data),
            'settings': {
                'host_video': True,
                'participant_video': True,
                'cn_meeting': False,
                'in_meeting': False,
                'join_before_host': False,
                'mute_upon_entry': True,
                'watermark': False,
                'use_pmi': False,
                'approval_type': 0,  # Automatically approve
                'audio': 'both',  # Telephone and VoIP
                'auto_recording': 'none',
                'enforce_login': False,
                'waiting_room': True,  # Enable waiting room for security
                'meeting_authentication': False
            }
        }
        
        # Add attendees if provided
        if attendees:
            meeting_data['attendees'] = attendees
        
        return meeting_data
    
    def _generate_meeting_password(self) -> str:
        """Generate a secure meeting password"""
        import random
        import string
        
        # Generate 6-digit password
        return ''.join(random.choices(string.digits, k=6))
    
    def _create_meeting_agenda(self, appointment_data: Dict[str, Any]) -> str:
        """Create meeting agenda/description"""
        
        crisis_level = appointment_data.get('crisis_level', 'normal')
        notes = appointment_data.get('notes', '')
        
        agenda = f"""
🩺 Confidential Therapy Session

Priority Level: {crisis_level.title()}
Duration: 60 minutes
Type: Virtual Session

Important Reminders:
• Please join on time
• Ensure you're in a private, quiet space
• Test your audio/video before the session
• Contact support if you have technical issues

Session Notes: {notes}

This is a confidential therapy session. Please maintain privacy and professionalism.
        """.strip()
        
        return agenda
    
    def _format_dial_in_info(self, meeting_response: Dict[str, Any]) -> Optional[str]:
        """Format dial-in information from Zoom response"""
        try:
            # Zoom provides global dial-in numbers
            if 'dial_in_numbers' in meeting_response:
                us_numbers = [
                    num for num in meeting_response['dial_in_numbers'] 
                    if num.get('country_name') == 'US'
                ]
                if us_numbers:
                    return us_numbers[0].get('number')
            
            # Fallback
            return '+1-646-558-8656'  # Zoom's primary US number
            
        except Exception:
            return '+1-646-558-8656'
    
    def _create_fallback_meeting(self, appointment_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Create fallback meeting info when Zoom API is unavailable"""
        
        meeting_id = str(uuid.uuid4())[:12].replace('-', '')
        
        fallback_info = {
            'zoom_meeting_id': f'fallback-{meeting_id}',
            'meet_link': f'https://zoom.us/j/fallback{meeting_id}',
            'host_link': f'https://zoom.us/s/fallback{meeting_id}',
            'meeting_password': '123456',
            'dial_in': '+1-646-558-8656',
            'platform': 'Zoom (Fallback)',
            'created_method': 'fallback',
            'note': 'Therapist will provide actual Zoom link'
        }
        
        logger.warning("Using fallback Zoom meeting info")
        return False, fallback_info
    
    def update_meeting(self, meeting_id: str, appointment_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Update an existing Zoom meeting"""
        try:
            if not all([self.client_id, self.client_secret, self.account_id]):
                return False, {'error': 'Zoom OAuth not configured'}
            
            token = self.get_access_token()
            if not token:
                return False, {'error': 'Failed to get access token'}
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Prepare update data
            update_data = {
                'start_time': appointment_data['datetime'].strftime('%Y-%m-%dT%H:%M:%S'),
                'duration': 60,
                'timezone': 'America/New_York'
            }
            
            response = requests.patch(
                f'{self.base_url}/meetings/{meeting_id}',
                json=update_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 204:  # No content = success
                logger.info(f"Updated Zoom meeting: {meeting_id}")
                return True, {'meeting_id': meeting_id}
            else:
                logger.error(f"Failed to update Zoom meeting: {response.status_code}")
                return False, {'error': f'Update failed: {response.status_code}'}
                
        except Exception as e:
            logger.error(f"Error updating Zoom meeting: {str(e)}")
            return False, {'error': str(e)}
    
    def cancel_meeting(self, meeting_id: str) -> Tuple[bool, Dict[str, Any]]:
        """Cancel/delete a Zoom meeting"""
        try:
            if not all([self.client_id, self.client_secret, self.account_id]):
                return False, {'error': 'Zoom OAuth not configured'}
            
            token = self.get_access_token()
            if not token:
                return False, {'error': 'Failed to get access token'}
            
            headers = {
                'Authorization': f'Bearer {token}'
            }
            
            response = requests.delete(
                f'{self.base_url}/meetings/{meeting_id}',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 204:  # No content = success
                logger.info(f"Cancelled Zoom meeting: {meeting_id}")
                return True, {'message': 'Meeting cancelled successfully'}
            else:
                logger.error(f"Failed to cancel Zoom meeting: {response.status_code}")
                return False, {'error': f'Cancellation failed: {response.status_code}'}
                
        except Exception as e:
            logger.error(f"Error cancelling Zoom meeting: {str(e)}")
            return False, {'error': str(e)}
    
    def get_meeting_info(self, meeting_id: str) -> Tuple[bool, Dict[str, Any]]:
        """Get information about a Zoom meeting"""
        try:
            if not all([self.client_id, self.client_secret, self.account_id]):
                return False, {'error': 'Zoom OAuth not configured'}
            
            token = self.get_access_token()
            if not token:
                return False, {'error': 'Failed to get access token'}
            
            headers = {
                'Authorization': f'Bearer {token}'
            }
            
            response = requests.get(
                f'{self.base_url}/meetings/{meeting_id}',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                meeting_data = response.json()
                return True, meeting_data
            else:
                return False, {'error': f'Failed to get meeting: {response.status_code}'}
                
        except Exception as e:
            logger.error(f"Error getting Zoom meeting info: {str(e)}")
            return False, {'error': str(e)}

# Convenience functions for easy integration

def create_zoom_therapy_meeting(appointment_data: Dict[str, Any], 
                              student_email: str = None, 
                              therapist_email: str = None) -> Tuple[bool, Dict[str, Any]]:
    """
    Create a Zoom meeting for therapy appointment
    
    Args:
        appointment_data: Appointment details
        student_email: Student's email
        therapist_email: Therapist's email
        
    Returns:
        Tuple of (success: bool, meeting_info: dict)
    """
    zoom_manager = ZoomMeetingManager()
    return zoom_manager.create_therapy_meeting(appointment_data, student_email, therapist_email)

def update_zoom_meeting(meeting_id: str, appointment_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Update a Zoom meeting"""
    zoom_manager = ZoomMeetingManager()
    return zoom_manager.update_meeting(meeting_id, appointment_data)

def cancel_zoom_meeting(meeting_id: str) -> Tuple[bool, Dict[str, Any]]:
    """Cancel a Zoom meeting"""
    zoom_manager = ZoomMeetingManager()
    return zoom_manager.cancel_meeting(meeting_id)

def test_zoom_integration() -> bool:
    """Test Zoom OAuth integration"""
    try:
        zoom_manager = ZoomMeetingManager()
        
        # Test with dummy data
        test_appointment = {
            'datetime': datetime.now() + timedelta(hours=1),
            'crisis_level': 'normal',
            'notes': 'Test appointment',
            'appointment_id': 'test-123'
        }
        
        success, result = zoom_manager.create_therapy_meeting(
            test_appointment,
            'test-student@example.com',
            'test-therapist@example.com'
        )
        
        if success and result.get('created_method') == 'zoom_oauth':
            # Clean up test meeting
            meeting_id = result.get('zoom_meeting_id')
            if meeting_id and not meeting_id.startswith('fallback'):
                zoom_manager.cancel_meeting(meeting_id)
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Zoom integration test failed: {str(e)}")
        return False