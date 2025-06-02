# simple_create_admin.py - Super simple admin creation (no app imports)
# SAVE AS: simple_create_admin.py (next to your app.py)

import os
from datetime import datetime
from werkzeug.security import generate_password_hash
from pymongo import MongoClient
from dotenv import load_dotenv

def create_admin():
    """Create admin directly in MongoDB without Flask app"""
    
    # Load environment variables
    load_dotenv()
    
    # Get credentials from environment
    email = os.getenv('ADMIN_EMAIL')
    password = os.getenv('ADMIN_PASSWORD')
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    db_name = os.getenv('DB_NAME', 'wellbeing_db')
    
    if not email or not password:
        print("❌ Please set ADMIN_EMAIL and ADMIN_PASSWORD in your .env file")
        print()
        print("Add these lines to your .env file:")
        print("ADMIN_EMAIL=youremail@gmail.com")
        print("ADMIN_PASSWORD=YourSecurePassword123!")
        return False
    
    try:
        # Connect directly to MongoDB
        print("🔌 Connecting to MongoDB...")
        client = MongoClient(mongodb_uri)
        db = client[db_name]
        
        # Test connection
        client.admin.command('ping')
        print("✅ MongoDB connection successful")
        
        # Check if admin already exists
        existing_count = db.admin.count_documents({})
        if existing_count > 0:
            print("❌ Admin already exists!")
            existing = db.admin.find_one({}, {"email": 1})
            print(f"   Existing admin: {existing.get('email', 'Unknown')}")
            return False
        
        # Create admin
        print("👑 Creating admin account...")
        hashed_password = generate_password_hash(password)
        
        admin_doc = {
            "email": email,
            "password": hashed_password,
            "role": "super_admin",
            "permissions": ["read", "write", "delete", "manage_users", "manage_system"],
            "created_at": datetime.utcnow(),
            "status": "active",
            "last_login": None
        }
        
        result = db.admin.insert_one(admin_doc)
        
        print("🎉 SUCCESS! Admin created!")
        print(f"📧 Email: {email}")
        print(f"🆔 Admin ID: {result.inserted_id}")
        print("🔒 Password is securely hashed")
        print()
        print("✨ You can now use these credentials to log into your app!")
        
        # Close connection
        client.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print("💡 Troubleshooting:")
        print("   - Make sure MongoDB is running")
        print("   - Check your MONGODB_URI in .env file")
        print("   - Make sure .env file exists and has the right values")
        return False

if __name__ == '__main__':
    print("🔐 Simple Admin Creator")
    print("=" * 30)
    print()
    
    success = create_admin()
    
    if success:
        print()
        print("🚀 Next steps:")
        print("   1. Start your Flask app: python app.py")
        print("   2. Log in with your admin credentials")
        print("   3. You're all set!")
    else:
        print()
        print("❌ Admin creation failed")
        print("Please fix the issues above and try again")