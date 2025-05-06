from datetime import datetime, timezone
from bson.objectid import ObjectId
from flask import current_app
from wellbeing import mongo

def create_journal_entry(user_id, title, content, entry_date, mood, gratitude_items=None):
    """Create a new journal entry."""
    # Validate and format date
    if isinstance(entry_date, str):
        try:
            entry_date = datetime.strptime(entry_date, '%Y-%m-%d')
            entry_date = entry_date.replace(tzinfo=timezone.utc)
        except ValueError:
            entry_date = datetime.now(timezone.utc)
    
    # Create journal entry document
    journal_entry = {
        'user_id': user_id,
        'date': entry_date,
        'title': title[:100],  # Limit title length
        'content': content[:5000],  # Limit content length
        'mood': mood,
        'gratitude': gratitude_items or [],
        'created_at': datetime.now(timezone.utc)
    }
    
    # Insert into database
    result = mongo.db.journals.insert_one(journal_entry)
    return str(result.inserted_id)

def get_journal_entries(user_id, limit=5):
    """Get journal entries for a user."""
    entries = list(mongo.db.journals.find(
        {"user_id": user_id}
    ).sort("date", -1).limit(limit))
    
    # Format journal entries
    formatted_entries = []
    for entry in entries:
        try:
            formatted_entry = {
                '_id': str(entry['_id']),
                'title': entry.get('title', 'Untitled Entry'),
                'content': entry.get('content', ''),
                'mood': entry.get('mood', 'neutral')
            }
            
            # Handle date formatting safely
            try:
                formatted_entry['date'] = entry.get('date', datetime.now(timezone.utc)).strftime('%b %d, %Y')
            except:
                formatted_entry['date'] = datetime.now(timezone.utc).strftime('%b %d, %Y')
                
            formatted_entries.append(formatted_entry)
        except Exception as e:
            current_app.logger.error(f"Error processing journal entry: {str(e)}")
    
    return formatted_entries

def get_journal_entry(entry_id, user_id):
    """Get a single journal entry."""
    try:
        entry = mongo.db.journals.find_one({
            '_id': ObjectId(entry_id),
            'user_id': user_id
        })
        
        if not entry:
            return None
        
        # Format entry for display
        formatted_entry = {
            '_id': str(entry['_id']),
            'title': entry.get('title', 'Untitled Entry'),
            'content': entry.get('content', ''),
            'date': entry.get('date', datetime.now(timezone.utc)).strftime('%B %d, %Y'),
            'mood': entry.get('mood', 'neutral'),
            'gratitude': entry.get('gratitude', [])
        }
        
        return formatted_entry
    except Exception as e:
        current_app.logger.error(f"Error retrieving journal entry: {str(e)}")
        return None