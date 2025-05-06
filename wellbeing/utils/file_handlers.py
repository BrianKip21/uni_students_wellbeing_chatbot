import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app

def handle_video_upload(file):
    """
    Handle video file uploads securely.
    
    Args:
        file: The file object from request.files
        
    Returns:
        str: The relative path to the saved file or None if upload failed
    """
    if file and file.filename:
        # Generate unique filename
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Save the file
        file.save(file_path)
        
        # Return the relative path to be stored in database
        return f"/static/uploads/videos/{unique_filename}"
    return None