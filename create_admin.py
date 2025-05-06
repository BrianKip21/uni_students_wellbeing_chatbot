from flask import Flask, jsonify
from werkzeug.security import generate_password_hash
from datetime import datetime
from pymongo import MongoClient

# Initialize Flask app
app = Flask(__name__)

# MongoDB client initialization (update with your connection details)
client = MongoClient('mongodb://localhost:27017/')
db = client['wellbeing_db']

# Function to create an admin account
def create_admin_account():
    email = "brianadmin@admin.com"
    password = "Brian1045"  # Choose a strong password here
    hashed_password = generate_password_hash(password)
    role = "admin"
    created_at = datetime.utcnow()

    # Insert admin account into MongoDB
    db.admin.insert_one({
        "email": email,
        "password": hashed_password,
        "role": role,
        "created_at": created_at,
        "status": "Active",
        "last_login": created_at  # Set initial login time to account creation time
    })
    print(f"Admin account created for {email}")

# Run the account creation
if __name__ == '__main__':
    create_admin_account()
    app.run(debug=True, port=5001)
