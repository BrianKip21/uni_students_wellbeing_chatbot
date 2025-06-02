"""
Enhanced scheduling utilities with OAuth Zoom integration for real video meetings
wellbeing/utils/scheduling.py
"""

# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from bson.objectid import ObjectId
import uuid

from wellbeing import mongo
from wellbeing.utils.zoom_integration import (
    create_zoom_therapy_meeting,
    update_zoom_meeting,
    cancel_zoom_meeting
)

logger = logging.getLogger(__name__)

class AppointmentScheduler:
    """Enhanced appointment scheduler with OAuth Zoom integration for real meetings"""
    
    def __init__(self):
        pass
    
    def get_therapist_available_slots(self, 
                                    therapist: Dict[str, Any], 
                                    crisis_level: str = 'normal',
                                    days_ahead: int = 14) -> List[Dict[str, Any]]:
        """
        Get available time slots for a therapist
        
        Args:
            therapist: Therapist document from database
            crisis_level: Priority level affecting slot availability
            days_ahead: Number of days to look ahead
            
        Returns:
            List of available time slots
        """
        try:
            available_slots = []
            
            # Get therapist's working hours (default to 9 AM - 5 PM)
            working_hours = therapist.get('working_hours', {
                'monday': [(9, 17)],
                'tuesday': [(9, 17)],
                'wednesday': [(9, 17)],
                'thursday': [(9, 17)],
                'friday': [(9, 17)],
                'saturday': [],
                'sunday': []
            })
            
            # Get existing appointments from database
            existing_appointments = list(mongo.db.appointments.find({
                'therapist_id': therapist['_id'],
                'status': {'$in': ['confirmed', 'suggested']},
                'datetime': {'$gte': datetime.now()}
            }))
            
            existing_times = [apt['datetime'] for apt in existing_appointments]
            
            # Generate available slots
            current_date = datetime.now() + timedelta(days=1)  # Start tomorrow
            
            for day_offset in range(days_ahead):
                check_date = current_date + timedelta(days=day_offset)
                day_name = check_date.strftime('%A').lower()
                
                # Skip if no working hours for this day
                if day_name not in working_hours or not working_hours[day_name]:
                    continue
                
                # Check each working hour block
                for start_hour, end_hour in working_hours[day_name]:
                    for hour in range(start_hour, end_hour):
                        slot_time = check_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                        
                        # Skip past times
                        if slot_time <= datetime.now():
                            continue
                        
                        # Check if slot is available
                        if self._is_slot_available(slot_time, existing_times):
                            slot_data = {
                                'datetime': slot_time,
                                'date': slot_time.strftime('%Y-%m-%d'),
                                'time': slot_time.strftime('%I:%M %p'),
                                'formatted': slot_time.strftime('%A, %B %d at %I:%M %p'),
                                'day_name': slot_time.strftime('%A'),
                                'crisis_priority': crisis_level == 'high'
                            }
                            available_slots.append(slot_data)
            
            # Sort slots - crisis appointments get priority slots first
            if crisis_level == 'high':
                available_slots = available_slots[:10]  # Limit to next 10 slots for crisis
            else:
                available_slots = available_slots[:20]  # More options for regular appointments
            
            logger.info(f"Found {len(available_slots)} available slots for therapist {therapist['_id']}")
            return available_slots
            
        except Exception as e:
            logger.error(f"Error getting therapist availability: {str(e)}")
            return []
    
    def _is_slot_available(self, 
                          slot_time: datetime, 
                          existing_times: List[datetime]) -> bool:
        """
        Check if a time slot is available
        
        Args:
            slot_time: Time slot to check
            existing_times: List of existing appointment times from database
            
        Returns:
            True if slot is available, False otherwise
        """
        # Check database appointments (1-hour buffer)
        for existing_time in existing_times:
            time_diff = abs((slot_time - existing_time).total_seconds()) / 3600
            if time_diff < 1:  # Less than 1 hour difference
                return False
        
        return True
    
    def auto_schedule_best_time(self, 
                              student_id: ObjectId,
                              therapist: Dict[str, Any],
                              appointment_type: str = 'virtual',
                              crisis_level: str = 'normal') -> Tuple[Optional[ObjectId], Optional[Dict[str, Any]]]:
        """
        Automatically schedule the best available time slot with OAuth Zoom integration
        
        Args:
            student_id: Student's ObjectId
            therapist: Therapist document
            appointment_type: Type of appointment (always 'virtual' in current implementation)
            crisis_level: Priority level
            
        Returns:
            Tuple of (appointment_id, appointment_document)
        """
        try:
            # Get available slots
            available_slots = self.get_therapist_available_slots(therapist, crisis_level)
            
            if not available_slots:
                logger.warning(f"No available slots for therapist {therapist['_id']}")
                return None, None
            
            # Select best slot (first one for now, could be enhanced with ML)
            best_slot = available_slots[0]
            
            # Create appointment with Zoom integration
            return self.schedule_appointment_automatically(
                student_id, therapist, best_slot, appointment_type, crisis_level
            )
            
        except Exception as e:
            logger.error(f"Error in auto-scheduling: {str(e)}")
            return None, None
    
    def schedule_appointment_automatically(self,
                                         student_id: ObjectId,
                                         therapist: Dict[str, Any],
                                         selected_slot: Dict[str, Any],
                                         appointment_type: str = 'virtual',
                                         crisis_level: str = 'normal') -> Tuple[Optional[ObjectId], Optional[Dict[str, Any]]]:
        """
        Schedule a specific appointment slot with real OAuth Zoom meeting integration
        
        Args:
            student_id: Student's ObjectId
            therapist: Therapist document
            selected_slot: Selected time slot
            appointment_type: Type of appointment
            crisis_level: Priority level
            
        Returns:
            Tuple of (appointment_id, appointment_document)
        """
        try:
            # Get student and therapist information
            student = mongo.db.users.find_one({'_id': student_id})
            if not student:
                logger.error(f"Student not found: {student_id}")
                return None, None
            
            student_email = student.get('email')
            student_name = student.get('name', student.get('username', 'Student'))
            therapist_email = therapist.get('email')
            therapist_name = therapist.get('name', therapist.get('username', 'Therapist'))
            
            # Create unique meeting ID
            meeting_id = str(uuid.uuid4())[:12].replace('-', '')
            
            # Create appointment document
            appointment_doc = {
                'student_id': student_id,
                'user_id': student_id,  # For backward compatibility
                'therapist_id': therapist['_id'],
                'datetime': selected_slot['datetime'],
                'formatted_time': selected_slot.get('formatted'),
                'type': appointment_type,
                'status': 'confirmed',
                'crisis_level': crisis_level,
                'notes': f'Auto-scheduled {appointment_type} session - Priority: {crisis_level}',
                'created_at': datetime.utcnow(),
                'auto_scheduled': True,
                'meeting_id': meeting_id,
                'student_name': student_name,
                'therapist_name': therapist_name
            }
            
            # Try OAuth Zoom meeting creation
            zoom_success = False
            zoom_meeting_id = None
            
            logger.info(f"Creating Zoom meeting for appointment {meeting_id}")
            
            if student_email and therapist_email:
                try:
                    # Prepare appointment data for Zoom integration
                    zoom_appointment_data = {
                        'datetime': selected_slot['datetime'],
                        'crisis_level': crisis_level,
                        'notes': appointment_doc['notes'],
                        'appointment_id': meeting_id
                    }
                    
                    zoom_success, zoom_result = create_zoom_therapy_meeting(
                        zoom_appointment_data, student_email, therapist_email
                    )
                    
                    if zoom_success and zoom_result.get('created_method') == 'zoom_oauth':
                        zoom_meeting_id = zoom_result.get('zoom_meeting_id')
                        appointment_doc['zoom_meeting_id'] = zoom_meeting_id
                        appointment_doc['meeting_info'] = {
                            'meet_link': zoom_result.get('meet_link'),
                            'host_link': zoom_result.get('host_link'),
                            'platform': 'Zoom',
                            'meeting_password': zoom_result.get('meeting_password'),
                            'dial_in': zoom_result.get('dial_in'),
                            'meeting_uuid': zoom_result.get('meeting_uuid'),
                            'created_method': 'oauth_api'
                        }
                        logger.info(f"✅ Created OAuth Zoom meeting: {zoom_meeting_id}")
                    else:
                        logger.warning(f"OAuth Zoom creation failed or used fallback: {zoom_result}")
                        # Use the fallback meeting info from zoom integration
                        if zoom_result:
                            appointment_doc['meeting_info'] = {
                                'meet_link': zoom_result.get('meet_link'),
                                'host_link': zoom_result.get('host_link', zoom_result.get('meet_link')),
                                'platform': zoom_result.get('platform', 'Zoom (Fallback)'),
                                'meeting_password': zoom_result.get('meeting_password'),
                                'dial_in': zoom_result.get('dial_in'),
                                'created_method': 'fallback',
                                'note': zoom_result.get('note', 'Therapist will provide actual link')
                            }
                        
                except Exception as e:
                    logger.error(f"OAuth Zoom integration error: {str(e)}")
                    zoom_success = False
            else:
                logger.warning(f"Missing email addresses - Student: {bool(student_email)}, Therapist: {bool(therapist_email)}")
            
            # Fallback meeting info if OAuth Zoom failed completely
            if not appointment_doc.get('meeting_info'):
                logger.info("Creating fallback meeting info")
                fallback_meeting = create_enhanced_fallback_meeting_link(
                    f"Therapy Session - {crisis_level.title()}",
                    selected_slot['datetime']
                )
                appointment_doc['meeting_info'] = fallback_meeting
            
            # Insert appointment into database
            result = mongo.db.appointments.insert_one(appointment_doc)
            appointment_id = result.inserted_id
            
            # Update document with ID
            appointment_doc['_id'] = appointment_id
            appointment_doc['zoom_integrated'] = zoom_success
            
            # Log the result
            if zoom_success:
                logger.info(f"✅ Created appointment {appointment_id} with OAuth Zoom integration")
            else:
                logger.info(f"⚠️  Created appointment {appointment_id} with fallback meeting info")
            
            return appointment_id, appointment_doc
            
        except Exception as e:
            logger.error(f"Error scheduling appointment: {str(e)}")
            return None, None

# Legacy function wrappers for backward compatibility
def get_therapist_available_slots(therapist: Dict[str, Any], 
                                crisis_level: str = 'normal') -> List[Dict[str, Any]]:
    """Legacy wrapper for get_therapist_available_slots"""
    scheduler = AppointmentScheduler()
    return scheduler.get_therapist_available_slots(therapist, crisis_level)

def auto_schedule_best_time(student_id: ObjectId,
                          therapist: Dict[str, Any],
                          appointment_type: str = 'virtual',
                          crisis_level: str = 'normal') -> Tuple[Optional[ObjectId], Optional[Dict[str, Any]]]:
    """Legacy wrapper for auto_schedule_best_time"""
    scheduler = AppointmentScheduler()
    return scheduler.auto_schedule_best_time(student_id, therapist, appointment_type, crisis_level)

def schedule_appointment_automatically(student_id: ObjectId,
                                     therapist: Dict[str, Any],
                                     selected_slot: Dict[str, Any],
                                     appointment_type: str = 'virtual',
                                     crisis_level: str = 'normal') -> Tuple[Optional[ObjectId], Optional[Dict[str, Any]]]:
    """Legacy wrapper for schedule_appointment_automatically"""
    scheduler = AppointmentScheduler()
    return scheduler.schedule_appointment_automatically(
        student_id, therapist, selected_slot, appointment_type, crisis_level
    )

def create_google_meet_link(session_title: str = "Therapy Session") -> Dict[str, Any]:
    """
    Legacy function - now creates Zoom meetings instead of Google Meet
    
    Args:
        session_title: Title for the meeting
        
    Returns:
        Dictionary containing meeting information
    """
    return create_enhanced_fallback_meeting_link(session_title)

def create_fallback_meeting_link(session_title: str = "Therapy Session") -> Dict[str, Any]:
    """
    Create a fallback meeting link when real OAuth Zoom API is not available
    
    Args:
        session_title: Title for the meeting
        
    Returns:
        Dictionary containing meeting information
    """
    return create_enhanced_fallback_meeting_link(session_title)

def create_enhanced_fallback_meeting_link(session_title: str = "Therapy Session", 
                                        meeting_time: datetime = None) -> Dict[str, Any]:
    """
    Create an enhanced fallback meeting link with better formatting
    
    Args:
        session_title: Title for the meeting
        meeting_time: Scheduled meeting time
        
    Returns:
        Dictionary containing meeting information
    """
    try:
        meeting_id = str(uuid.uuid4())[:12].replace('-', '')
        time_str = meeting_time.strftime('%Y%m%d%H%M') if meeting_time else ''
        
        return {
            'meet_link': f'https://zoom.us/j/fallback{meeting_id}',
            'host_link': f'https://zoom.us/s/fallback{meeting_id}',
            'platform': 'Zoom (Manual Setup Required)',
            'meeting_id': f'fallback-{meeting_id}',
            'meeting_password': '123456',
            'dial_in': '+1-646-558-8656',
            'generated_method': 'fallback',
            'note': 'Therapist will provide actual Zoom link before session',
            'instructions': 'Please wait for your therapist to send the actual meeting link',
            'created_at': datetime.utcnow().isoformat(),
            'meeting_title': session_title
        }
    except Exception as e:
        logger.error(f"Error creating enhanced fallback meeting link: {str(e)}")
        # Return minimal meeting info
        return {
            'meet_link': 'https://zoom.us/j/manual-meeting',
            'host_link': 'https://zoom.us/s/manual-meeting',
            'platform': 'Zoom (Manual)',
            'meeting_id': 'manual-meeting',
            'meeting_password': '123456',
            'dial_in': '+1-646-558-8656',
            'generated_method': 'error_fallback',
            'note': 'Contact your therapist for meeting details',
            'error': str(e)
        }

# Enhanced utility functions for appointment management

def get_upcoming_appointments(student_id: ObjectId, limit: int = 5) -> List[Dict[str, Any]]:
    """Get upcoming appointments for a student"""
    try:
        appointments = list(mongo.db.appointments.find({
            'student_id': student_id,
            'datetime': {'$gte': datetime.now()},
            'status': {'$in': ['confirmed', 'suggested']}
        }).sort('datetime', 1).limit(limit))
        
        # Enhance appointments with better meeting info
        for apt in appointments:
            if apt.get('meeting_info') and not apt['meeting_info'].get('instructions'):
                apt['meeting_info']['instructions'] = 'Join the meeting at the scheduled time'
        
        return appointments
    except Exception as e:
        logger.error(f"Error getting upcoming appointments: {str(e)}")
        return []

def get_therapist_schedule(therapist_id: ObjectId, 
                          start_date: datetime = None,
                          end_date: datetime = None) -> List[Dict[str, Any]]:
    """Get therapist's schedule within date range"""
    try:
        if not start_date:
            start_date = datetime.now()
        if not end_date:
            end_date = start_date + timedelta(days=30)
        
        appointments = list(mongo.db.appointments.find({
            'therapist_id': therapist_id,
            'datetime': {'$gte': start_date, '$lte': end_date},
            'status': {'$in': ['confirmed', 'suggested']}
        }).sort('datetime', 1))
        
        return appointments
    except Exception as e:
        logger.error(f"Error getting therapist schedule: {str(e)}")
        return []

def check_appointment_conflicts(therapist_id: ObjectId, 
                               appointment_time: datetime,
                               exclude_appointment_id: ObjectId = None) -> bool:
    """Check if an appointment time conflicts with existing appointments"""
    try:
        query = {
            'therapist_id': therapist_id,
            'status': {'$in': ['confirmed', 'suggested']},
            'datetime': {
                '$gte': appointment_time - timedelta(minutes=30),
                '$lte': appointment_time + timedelta(minutes=30)
            }
        }
        
        if exclude_appointment_id:
            query['_id'] = {'$ne': exclude_appointment_id}
        
        conflicts = mongo.db.appointments.find_one(query)
        return conflicts is not None
        
    except Exception as e:
        logger.error(f"Error checking appointment conflicts: {str(e)}")
        return True  # Assume conflict on error for safety

def update_appointment_meeting_info(appointment_id: ObjectId) -> bool:
    """Update appointment with fresh meeting information"""
    try:
        appointment = mongo.db.appointments.find_one({'_id': appointment_id})
        if not appointment:
            return False
        
        # Create new meeting link
        new_meeting_info = create_enhanced_fallback_meeting_link(
            f"Therapy Session - {appointment.get('crisis_level', 'normal').title()}",
            appointment.get('datetime')
        )
        
        # Update in database
        mongo.db.appointments.update_one(
            {'_id': appointment_id},
            {'$set': {'meeting_info': new_meeting_info, 'updated_at': datetime.utcnow()}}
        )
        
        logger.info(f"Updated meeting info for appointment {appointment_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating appointment meeting info: {str(e)}")
        return False

def update_zoom_meeting_in_appointment(appointment_id: ObjectId, 
                                     new_datetime: datetime) -> bool:
    """Update OAuth Zoom meeting when appointment is rescheduled"""
    try:
        appointment = mongo.db.appointments.find_one({'_id': appointment_id})
        if not appointment:
            logger.warning(f"Appointment not found: {appointment_id}")
            return False
        
        zoom_meeting_id = appointment.get('zoom_meeting_id')
        if zoom_meeting_id and not zoom_meeting_id.startswith('fallback'):
            # Update real OAuth Zoom meeting
            appointment_data = {**appointment, 'datetime': new_datetime}
            success, result = update_zoom_meeting(zoom_meeting_id, appointment_data)
            
            if success:
                logger.info(f"✅ Updated OAuth Zoom meeting {zoom_meeting_id}")
                
                # Update database with new meeting time
                mongo.db.appointments.update_one(
                    {'_id': appointment_id},
                    {'$set': {
                        'datetime': new_datetime,
                        'updated_at': datetime.utcnow(),
                        'zoom_updated': True
                    }}
                )
                return True
            else:
                logger.warning(f"❌ Failed to update OAuth Zoom meeting: {result}")
        else:
            logger.info(f"No real Zoom meeting to update for appointment {appointment_id}")
        
        return False
        
    except Exception as e:
        logger.error(f"Error updating OAuth Zoom meeting: {str(e)}")
        return False

def cancel_zoom_meeting_in_appointment(appointment_id: ObjectId) -> bool:
    """Cancel OAuth Zoom meeting when appointment is cancelled"""
    try:
        appointment = mongo.db.appointments.find_one({'_id': appointment_id})
        if not appointment:
            logger.warning(f"Appointment not found: {appointment_id}")
            return False
        
        zoom_meeting_id = appointment.get('zoom_meeting_id')
        if zoom_meeting_id and not zoom_meeting_id.startswith('fallback'):
            # Cancel real OAuth Zoom meeting
            success, result = cancel_zoom_meeting(zoom_meeting_id)
            
            if success:
                logger.info(f"✅ Cancelled OAuth Zoom meeting {zoom_meeting_id}")
                
                # Update database
                mongo.db.appointments.update_one(
                    {'_id': appointment_id},
                    {'$set': {
                        'status': 'cancelled',
                        'cancelled_at': datetime.utcnow(),
                        'zoom_cancelled': True
                    }}
                )
                return True
            else:
                logger.warning(f"❌ Failed to cancel OAuth Zoom meeting: {result}")
        else:
            logger.info(f"No real Zoom meeting to cancel for appointment {appointment_id}")
        
        return False
        
    except Exception as e:
        logger.error(f"Error cancelling OAuth Zoom meeting: {str(e)}")
        return False

def get_appointment_meeting_details(appointment_id: ObjectId) -> Optional[Dict[str, Any]]:
    """Get comprehensive meeting details for an appointment"""
    try:
        appointment = mongo.db.appointments.find_one({'_id': appointment_id})
        if not appointment:
            return None
        
        meeting_info = appointment.get('meeting_info', {})
        
        # Enhance meeting info with additional details
        enhanced_info = {
            'appointment_id': str(appointment_id),
            'datetime': appointment.get('datetime'),
            'formatted_time': appointment.get('formatted_time'),
            'crisis_level': appointment.get('crisis_level', 'normal'),
            'student_name': appointment.get('student_name'),
            'therapist_name': appointment.get('therapist_name'),
            'zoom_integrated': appointment.get('zoom_integrated', False),
            'meeting_details': meeting_info
        }
        
        return enhanced_info
        
    except Exception as e:
        logger.error(f"Error getting appointment meeting details: {str(e)}")
        return None

def refresh_zoom_meeting_for_appointment(appointment_id: ObjectId) -> bool:
    """Refresh Zoom meeting details for an appointment"""
    try:
        appointment = mongo.db.appointments.find_one({'_id': appointment_id})
        if not appointment:
            return False
        
        # Get student and therapist details
        student = mongo.db.users.find_one({'_id': appointment['student_id']})
        therapist = mongo.db.users.find_one({'_id': appointment['therapist_id']})
        
        if not student or not therapist:
            logger.warning(f"Missing student or therapist for appointment {appointment_id}")
            return False
        
        student_email = student.get('email')
        therapist_email = therapist.get('email')
        
        if student_email and therapist_email:
            # Create new OAuth Zoom meeting
            zoom_appointment_data = {
                'datetime': appointment['datetime'],
                'crisis_level': appointment.get('crisis_level', 'normal'),
                'notes': appointment.get('notes', ''),
                'appointment_id': str(appointment_id)
            }
            
            success, result = create_zoom_therapy_meeting(
                zoom_appointment_data, student_email, therapist_email
            )
            
            if success and result.get('created_method') == 'zoom_oauth':
                # Update appointment with new meeting info
                mongo.db.appointments.update_one(
                    {'_id': appointment_id},
                    {'$set': {
                        'zoom_meeting_id': result.get('zoom_meeting_id'),
                        'meeting_info': {
                            'meet_link': result.get('meet_link'),
                            'host_link': result.get('host_link'),
                            'platform': 'Zoom',
                            'meeting_password': result.get('meeting_password'),
                            'dial_in': result.get('dial_in'),
                            'meeting_uuid': result.get('meeting_uuid'),
                            'created_method': 'oauth_refresh'
                        },
                        'zoom_integrated': True,
                        'refreshed_at': datetime.utcnow()
                    }}
                )
                
                logger.info(f"✅ Refreshed OAuth Zoom meeting for appointment {appointment_id}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error refreshing Zoom meeting: {str(e)}")
        return False