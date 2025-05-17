#!/usr/bin/env python
# scripts/migrate_assignments.py

from datetime import datetime
from bson.objectid import ObjectId
import logging
import sys
import os

# Add the parent directory to the path so we can import our application
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('wellbeing.migration')

# Import your application and create a context
from wellbeing import create_app
from wellbeing import mongo

# Create the application and push an application context
app = create_app()
app_context = app.app_context()
app_context.push()

def migrate_assignments():
    """Migrate assignments from appointments to therapist_assignments"""
    print("Starting migration of therapist assignments...")
    logger.info("Starting migration of therapist assignments")
    
    # Check if mongo is initialized correctly
    if mongo is None:
        print("ERROR: MongoDB connection not initialized!")
        logger.error("MongoDB connection not initialized")
        return 0, 0, 0
    
    try:
        # Find assignments in appointments collection that appear to be actual assignments
        # and not just regular appointments
        assignments = list(mongo.db.appointments.find({
            '$or': [
                {'assignment': True},
                {'status': 'active', 'session_count': {'$exists': True}}
            ]
        }))
        
        print(f"Found {len(assignments)} potential assignments to migrate")
        logger.info(f"Found {len(assignments)} potential assignments to migrate")
        
        migrated_count = 0
        skipped_count = 0
        error_count = 0
        
        for assignment in assignments:
            try:
                # Check if already exists in therapist_assignments
                existing = mongo.db.therapist_assignments.find_one({
                    'student_id': assignment['student_id'],
                    'therapist_id': assignment['therapist_id'],
                    'status': 'active'
                })
                
                if existing:
                    skipped_count += 1
                    logger.info(f"Skipped existing assignment for student {assignment['student_id']}")
                    continue
                    
                # Create new assignment
                new_assignment = {
                    'student_id': assignment['student_id'],
                    'therapist_id': assignment['therapist_id'],
                    'status': 'active',
                    'created_at': assignment.get('created_at', datetime.now()),
                    'updated_at': datetime.now(),
                    'migrated_from': 'appointments',
                    'original_id': assignment['_id']
                }
                
                # Copy any relevant fields from the original assignment
                for field in ['next_session', 'session_count', 'notes']:
                    if field in assignment:
                        new_assignment[field] = assignment[field]
                
                # Insert into therapist_assignments collection
                result = mongo.db.therapist_assignments.insert_one(new_assignment)
                
                if result.inserted_id:
                    migrated_count += 1
                    logger.info(f"Successfully migrated assignment for student {assignment['student_id']}")
                    
                    # Update the therapist's current student count
                    therapist_id = assignment['therapist_id']
                    therapist = mongo.db.therapists.find_one({'_id': therapist_id})
                    
                    if therapist:
                        current_students = therapist.get('current_students', 0)
                        if not isinstance(current_students, int):
                            current_students = 0
                        
                        mongo.db.therapists.update_one(
                            {'_id': therapist_id},
                            {'$set': {'current_students': current_students + 1}}
                        )
                    
            except Exception as e:
                error_count += 1
                logger.error(f"Error migrating assignment: {str(e)}")
        
        print(f"Migration complete: {migrated_count} migrated, {skipped_count} skipped, {error_count} errors")
        logger.info(f"Migration complete: {migrated_count} migrated, {skipped_count} skipped, {error_count} errors")
        
        return migrated_count, skipped_count, error_count
    
    except Exception as e:
        print(f"Error in migration: {str(e)}")
        logger.error(f"Error in migration: {str(e)}")
        return 0, 0, 0

def update_therapist_counts():
    """Update therapist current_students counts based on active assignments"""
    print("Updating therapist student counts...")
    logger.info("Updating therapist student counts")
    
    # Check if mongo is initialized correctly
    if mongo is None:
        print("ERROR: MongoDB connection not initialized!")
        logger.error("MongoDB connection not initialized")
        return 0
    
    try:
        # Get all therapists
        therapists = list(mongo.db.therapists.find())
        
        print(f"Found {len(therapists)} therapists to update")
        logger.info(f"Found {len(therapists)} therapists to update")
        
        update_count = 0
        for therapist in therapists:
            # Count active assignments for this therapist
            actual_count = mongo.db.therapist_assignments.count_documents({
                'therapist_id': therapist['_id'],
                'status': 'active'
            })
            
            # Get current count
            current_count = therapist.get('current_students', 0)
            if not isinstance(current_count, int):
                current_count = 0
            
            # Update if different
            if actual_count != current_count:
                mongo.db.therapists.update_one(
                    {'_id': therapist['_id']},
                    {'$set': {'current_students': actual_count}}
                )
                update_count += 1
                print(f"Updated therapist {therapist['_id']}: {current_count} → {actual_count} students")
                logger.info(f"Updated therapist {therapist['_id']}: {current_count} → {actual_count} students")
        
        print(f"Updated {update_count} therapist records")
        logger.info(f"Updated {update_count} therapist records")
        
        return update_count
    
    except Exception as e:
        print(f"Error updating therapist counts: {str(e)}")
        logger.error(f"Error updating therapist counts: {str(e)}")
        return 0

# This will allow the script to be imported without running the interactive menu
if __name__ == "__main__":
    try:
        print("=== Assignment Migration Tool ===")
        choice = input("Choose operation:\n1. Migrate assignments\n2. Update therapist counts\n3. Both\nEnter choice (1-3): ")
        
        if choice == '1' or choice == '3':
            migrate_assignments()
        
        if choice == '2' or choice == '3':
            update_therapist_counts()
        
        print("Operation completed!")
    except Exception as e:
        print(f"Error occurred: {e}")
        logger.error(f"Error in migration script: {e}")
    finally:
        # Pop the application context when done
        app_context.pop()