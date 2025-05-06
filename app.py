"""
Main application entry point.
This imports and creates the app using the factory pattern.
"""
from wellbeing import create_app, mongo

# Create the Flask app
app = create_app()

# This allows you to access the database in shell sessions
# and keeps backward compatibility
db = mongo.db

if __name__ == '__main__':
    # Create static uploads directory if it doesn't exist
    import os
    if not os.path.exists('static/uploads/videos'):
        os.makedirs('static/uploads/videos')
        
    # Run the application
    app.run(host='0.0.0.0', port=5001, debug=True)