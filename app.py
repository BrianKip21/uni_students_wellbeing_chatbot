# app.py
from flask import Flask, render_template, request,jsonify, redirect, session, flash, url_for
from flask_pymongo import PyMongo
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import os
import bcrypt
import logging
from bson.objectid import ObjectId
from flask_cors import CORS 
from datetime import datetime


app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["MONGO_URI"] = "mongodb://Linda:linda@127.0.0.1:27017/wellbeing_db"


mongo = PyMongo(app)

# User Routes
"""@app.route('/')
def home():
    return redirect(url_for('login'))"""

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        users = mongo.db.users
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']  # Get confirm password

        # Check if passwords match
        if password != confirm_password:
            flash('Passwords do not match!')
            return redirect(url_for('register'))

        # Check if user already exists
        existing_user = users.find_one({'email': email})
        if existing_user:
            flash('Email already exists!')
            return redirect(url_for('register'))

        # Hash the password and store the user
        hashpass = generate_password_hash(password)
        users.insert_one({
         'name': request.form['name'],
        'email': email,
         'password': generate_password_hash(password)
        })

            
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))

    return render_template('register.html')


"""@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            users = mongo.db.users
            email = request.form.get('email')
            password = request.form.get('password')
            
            print(f"[DEBUG] Login attempt for email: {email}")
            
            # Find user
            user = users.find_one({'email': email})
            if user and check_password_hash(user['password'], password):
                session['user'] = str(user['_id'])
                print("[DEBUG] Login successful")
                return jsonify({
                    'success': True,
                    'message': 'Login successful'
                })
            
            print("[DEBUG] Login failed: Invalid credentials")
            return jsonify({
                'success': False,
                'message': 'Invalid email/password combination'
            })
            
        except Exception as e:
            print(f"[DEBUG] Login error: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'An error occurred. Please try again.'
            })
    
    return render_template('login.html')"""
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            users = mongo.db.users
            email = request.form.get('email')
            password = request.form.get('password')
            
            print(f"[DEBUG] Login attempt for email: {email}")
            
            # Find user
            user = users.find_one({'email': email})
            if user and check_password_hash(user['password'], password):
                session['user'] = str(user['_id'])
                print("[DEBUG] Login successful")
                # Instead of JSON, return a redirect response
                return redirect(url_for('dashboard'))
            
            print("[DEBUG] Login failed: Invalid credentials")
            flash('Invalid credentials')
            return redirect(url_for('login'))
            
        except Exception as e:
            print(f"[DEBUG] Login error: {str(e)}")
            flash('An error occurred')
            return redirect(url_for('login'))
    
    return render_template('login.html')

"""@app.route('/dashboard')
def dashboard():
    # Check if user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get user data
    user = mongo.db.users.find_one({'_id': session['user_id']})
    return render_template('dashboard.html', user=user)
"""
@app.route('/dashboard')
def dashboard():
    print(f"[DEBUG] Dashboard accessed. Session contents: {session}")
    print(f"[DEBUG] Current user in session: {session.get('user')}")

    if 'user' not in session:
        print("[DEBUG] No user in session, redirecting to login")
        return redirect(url_for('login'))
    
    # Sample user data (fetch this from your database)
    user_data = {
        "email": session.get('user')  # Assuming 'user' stores the email
    }

    # Sample data for recent chats
    recent_chats = [
        {"message": "How to manage stress?", "timestamp": datetime.utcnow()},
        {"message": "Tips for better sleep", "timestamp": datetime.utcnow()}
    ]

    # Sample resources
    resources = [
        {"title": "Mindfulness Guide", "description": "Learn how to meditate."},
        {"title": "Sleep Tips", "description": "Improve your sleep quality."}
    ]

    return render_template('dashboard.html', user=user_data, recent_chats=recent_chats, resources=resources)


@app.route('/update_mood', methods=['POST'])
def update_mood():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    mood = request.form.get('mood')
    if mood:
        try:
            mongo.db.users.update_one(
                {'_id': ObjectId(session['user_id'])},
                {
                    '$set': {'current_mood': mood},
                    '$push': {
                        'mood_history': {
                            'mood': mood,
                            'timestamp': datetime.utcnow()
                        }
                    }
                }
            )
            flash('Mood updated successfully!')
        except Exception as e:
            flash('Failed to update mood')
    
    return redirect(url_for('dashboard'))

# Additional routes for the quick actions
@app.route('/contact_counselor')
def contact_counselor():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # Add counselor contact logic
    return "Contact Counselor Page"

@app.route('/schedule_appointment')
def schedule_appointment():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # Add appointment scheduling logic
    return "Schedule Appointment Page"

@app.route('/start_meditation')
def start_meditation():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # Add meditation session logic
    return "Meditation Page"

@app.route('/chatbot')
def chatbot():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('chatbot.html')

@app.route('/resources')
def resources():
    if 'user' not in session:
        return redirect(url_for('login'))
    resources = mongo.db.resources.find()
    return render_template('resources.html', resources=resources)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        users = mongo.db.users
        users.update_one(
            {'_id': ObjectId(session['user'])},
            {'$set': {
                'name': request.form['name'],
                'bio': request.form['bio']
            }}
        )
        flash('Profile updated successfully!')
    
    user = mongo.db.users.find_one({'_id': ObjectId(session['user'])})
    return render_template('profile.html', user=user)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        users = mongo.db.users
        users.update_one(
            {'_id': ObjectId(session['user'])},
            {'$set': {
                'settings.notifications': bool(request.form.get('notifications')),
                'settings.theme': request.form.get('theme')
            }}
        )
        flash('Settings updated successfully!')
    
    user = mongo.db.users.find_one({'_id': ObjectId(session['user'])})
    return render_template('settings.html', user=user)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)
    