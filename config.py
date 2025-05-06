import os
import secrets
from datetime import timedelta

class Config:
    """Base configuration class."""
    
    # Flask config
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(24))
    DEBUG = os.getenv("FLASK_DEBUG", "True") == "True"
    
    # MongoDB config
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/wellbeing_db")
    
    # Session config
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    
    # File upload config
    UPLOAD_FOLDER = 'static/uploads/videos'
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False