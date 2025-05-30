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
    
    # Email/SMTP Configuration
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME', 'toobrian2003@gmail.com')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'zbnb hcnm karj ioyn')
    SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'toobrian2003@gmail.com')
    FROM_EMAIL = os.getenv('FROM_EMAIL', 'toobrian2003@gmail.com')  # Alias for sender email
    
    # Application URLs
    SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:5001')  # Changed to http for development
    
    # Password Reset Configuration
    PASSWORD_RESET_TOKEN_EXPIRY = timedelta(minutes=30)  # Token expiry time
    PASSWORD_RESET_SALT = os.getenv('PASSWORD_RESET_SALT', 'password-reset-salt')
    
    # Email Template Configuration
    APP_NAME = "AI-Powered Wellbeing Assistant"
    SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'toobrian2003@gmail.com')
    
    # Security Configuration
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour
    
    # Rate Limiting (for future implementation)
    RATELIMIT_STORAGE_URL = "memory://"
    RATELIMIT_DEFAULT = "100 per hour"
    PASSWORD_RESET_RATE_LIMIT = "5 per hour"  # Max 5 password reset requests per hour
    
    # Logging Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'logs/wellbeing.log')

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    
    # Development-specific email settings
    SITE_URL = os.getenv('DEV_SITE_URL', 'http://127.0.0.1:5001')
    
    # More verbose logging for development
    LOG_LEVEL = 'DEBUG'
    
    # Disable CSRF for easier development (optional)
    # WTF_CSRF_ENABLED = False
    
    # Development email settings (optional - for testing)
    # You can override these for testing with services like MailHog
    # SMTP_SERVER = 'localhost'
    # SMTP_PORT = 1025
    # SMTP_USERNAME = None
    # SMTP_PASSWORD = None

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    
    # Production-specific settings
    SITE_URL = os.getenv('PROD_SITE_URL', 'https://yourdomain.com')
    
    # Stricter security in production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Production logging
    LOG_LEVEL = 'WARNING'
    
    # Production rate limiting
    RATELIMIT_DEFAULT = "50 per hour"
    PASSWORD_RESET_RATE_LIMIT = "3 per hour"
    
    # Force environment variables in production
    if os.getenv('FLASK_ENV') == 'production':
        if not os.getenv('SECRET_KEY'):
            raise ValueError("SECRET_KEY environment variable must be set in production")
        if not os.getenv('SMTP_PASSWORD'):
            raise ValueError("SMTP_PASSWORD environment variable must be set in production")


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    DEBUG = True
    
    # Use in-memory database for testing
    MONGO_URI = "mongodb://localhost:27017/wellbeing_test_db"
    
    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False
    
    # Use mock email service for testing
    SMTP_SERVER = 'localhost'
    SMTP_PORT = 1025
    SMTP_USERNAME = None
    SMTP_PASSWORD = None
    
    # Shorter token expiry for faster testing
    PASSWORD_RESET_TOKEN_EXPIRY = timedelta(minutes=5)

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}