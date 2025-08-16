import os
import secrets
from datetime import timedelta, datetime

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
    
    # ===== NEW: Claude API Configuration =====
    # Claude API Settings
    CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')  # Required - get from Anthropic console
    CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-3-haiku-20240307')  # Model to use
    CLAUDE_MAX_TOKENS = int(os.getenv('CLAUDE_MAX_TOKENS', '150'))  # Short responses
    CLAUDE_TEMPERATURE = float(os.getenv('CLAUDE_TEMPERATURE', '0.5'))  # Lower temperature for consistency
    
    # Claude Rate Limiting and Cost Management
    CLAUDE_RATE_LIMIT_PER_MINUTE = int(os.getenv('CLAUDE_RATE_LIMIT_PER_MINUTE', '50'))
    CLAUDE_RATE_LIMIT_PER_DAY = int(os.getenv('CLAUDE_RATE_LIMIT_PER_DAY', '5000'))
    CLAUDE_RATE_LIMIT_PER_USER_PER_HOUR = int(os.getenv('CLAUDE_RATE_LIMIT_PER_USER_PER_HOUR', '200'))
    
    # Claude Timeout and Retry Settings
    CLAUDE_TIMEOUT = int(os.getenv('CLAUDE_TIMEOUT', '30'))  # seconds
    CLAUDE_MAX_RETRIES = int(os.getenv('CLAUDE_MAX_RETRIES', '3'))
    CLAUDE_RETRY_DELAY = float(os.getenv('CLAUDE_RETRY_DELAY', '1.0'))  # seconds
    
    # Budget Management Settings
    MAX_MONTHLY_SPEND = float(os.getenv('MAX_MONTHLY_SPEND', '5.00'))  # $5 budget
    USAGE_ALERT_THRESHOLD = float(os.getenv('USAGE_ALERT_THRESHOLD', '4.00'))  # Alert at $4
    DAILY_SPENDING_LIMIT = float(os.getenv('DAILY_SPENDING_LIMIT', '0.50'))  # $0.50 per day
    
    # Chatbot Configuration - UPDATED FOR SHORT RESPONSES
    CHATBOT_SYSTEM_PROMPT = os.getenv('CHATBOT_SYSTEM_PROMPT', 
        """You are a university counseling chatbot. CRITICAL: Keep ALL responses under 30 words maximum.
        - Use 1-2 short sentences only
        - Be supportive but extremely brief
        - If crisis mentioned, say "Please call 988 immediately" 
        - Ask one short follow-up question when helpful
        - Never exceed 30 words per response"""
    )
    
    # Crisis Detection Settings
    CRISIS_DETECTION_ENABLED = os.getenv('CRISIS_DETECTION_ENABLED', 'True') == 'True'
    CRISIS_KEYWORDS = [
        'suicide', 'kill myself', 'hurt myself', 'end it all', 'don\'t want to live',
        'self harm', 'cutting', 'overdose', 'jump off', 'hang myself'
    ]
    CRISIS_RESPONSE_MESSAGE = os.getenv('CRISIS_RESPONSE_MESSAGE',
        """🚨 I'm concerned. Please call 988 (Crisis Hotline) or 911 immediately. You matter and help is available."""
    )
    
    # Available Claude Models (for reference and validation)
    AVAILABLE_CLAUDE_MODELS = {
        'claude-3-haiku-20240307': {
            'name': 'Claude 3 Haiku',
            'cost_input': 0.25,  # per million tokens
            'cost_output': 1.25,  # per million tokens
            'description': 'Fast and cost-effective for everyday tasks'
        },
        'claude-3-sonnet-20240229': {
            'name': 'Claude 3 Sonnet', 
            'cost_input': 3.00,
            'cost_output': 15.00,
            'description': 'Balanced performance and intelligence'
        },
        'claude-3-5-sonnet-20241022': {
            'name': 'Claude 3.5 Sonnet',
            'cost_input': 3.00,
            'cost_output': 15.00,
            'description': 'Most advanced capabilities'
        }
    }
    
    # App startup time for health checks
    @staticmethod
    def init_app(app):
        app.config['app_start_time'] = datetime.now()
        
        # Validate critical configurations
        if not app.config.get('CLAUDE_API_KEY'):
            app.logger.warning('CLAUDE_API_KEY not configured - chatbot will not work properly')
        
        # Validate Claude model
        claude_model = app.config.get('CLAUDE_MODEL')
        available_models = app.config.get('AVAILABLE_CLAUDE_MODELS', {})
        if claude_model not in available_models:
            app.logger.warning(f'Unknown Claude model: {claude_model}')
        else:
            model_info = available_models[claude_model]
            app.logger.info(f"Using {model_info['name']} - {model_info['description']}")
            app.logger.info(f"Cost: ${model_info['cost_input']}/${model_info['cost_output']} per M tokens")
        
        app.logger.info(f"Max tokens per response: {app.config.get('CLAUDE_MAX_TOKENS')}")
        app.logger.info(f"Crisis detection: {'enabled' if app.config.get('CRISIS_DETECTION_ENABLED') else 'disabled'}")
        app.logger.info(f"Monthly budget: ${app.config.get('MAX_MONTHLY_SPEND', 0)}")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    
    # Development-specific email settings
    SITE_URL = os.getenv('DEV_SITE_URL', 'http://127.0.0.1:5001')
    
    # More verbose logging for development
    LOG_LEVEL = 'DEBUG'
    
    # ===== FIXED: Development Claude Settings =====
    # Use same short responses as base config
    CLAUDE_MODEL = os.getenv('DEV_CLAUDE_MODEL', 'claude-3-haiku-20240307')  # Cheapest option
    CLAUDE_MAX_TOKENS = int(os.getenv('DEV_CLAUDE_MAX_TOKENS', '150'))  # FIXED: Now uses 150
    CLAUDE_TEMPERATURE = float(os.getenv('DEV_CLAUDE_TEMPERATURE', '0.5'))  # Lower for consistency
    CLAUDE_RATE_LIMIT_PER_MINUTE = int(os.getenv('DEV_CLAUDE_RATE_LIMIT_PER_MINUTE', '25'))
    CLAUDE_RATE_LIMIT_PER_DAY = int(os.getenv('DEV_CLAUDE_RATE_LIMIT_PER_DAY', '2500'))
    CLAUDE_RATE_LIMIT_PER_USER_PER_HOUR = int(os.getenv('DEV_CLAUDE_RATE_LIMIT_PER_USER_PER_HOUR', '100'))
    
    # Conservative budget for development
    MAX_MONTHLY_SPEND = float(os.getenv('DEV_MAX_MONTHLY_SPEND', '2.00'))  # $2 for dev
    DAILY_SPENDING_LIMIT = float(os.getenv('DEV_DAILY_SPENDING_LIMIT', '0.25'))  # $0.25 per day
    
    # Override system prompt for even shorter development responses
    CHATBOT_SYSTEM_PROMPT = os.getenv('DEV_CHATBOT_SYSTEM_PROMPT',
        """University counseling bot. Max 20 words per response. Be brief and supportive. Ask short follow-up questions."""
    )
    
    @staticmethod
    def init_app(app):
        Config.init_app(app)
        app.logger.info('Development mode - using SHORT response settings')
        app.logger.info(f'Max tokens per response: {app.config.get("CLAUDE_MAX_TOKENS")}')
        app.logger.info(f'Temperature: {app.config.get("CLAUDE_TEMPERATURE")}')
        app.logger.info(f'Daily spending limit: ${app.config.get("DAILY_SPENDING_LIMIT")}')


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
    
    # ===== NEW: Production Claude Settings =====
    # Production also uses short responses but slightly longer than dev
    CLAUDE_MODEL = os.getenv('PROD_CLAUDE_MODEL', 'claude-3-haiku-20240307')  # Still budget-friendly
    CLAUDE_MAX_TOKENS = int(os.getenv('PROD_CLAUDE_MAX_TOKENS', '200'))  # Slightly longer for production
    CLAUDE_TEMPERATURE = float(os.getenv('PROD_CLAUDE_TEMPERATURE', '0.6'))
    CLAUDE_RATE_LIMIT_PER_MINUTE = int(os.getenv('PROD_CLAUDE_RATE_LIMIT_PER_MINUTE', '50'))
    CLAUDE_RATE_LIMIT_PER_DAY = int(os.getenv('PROD_CLAUDE_RATE_LIMIT_PER_DAY', '5000'))
    CLAUDE_RATE_LIMIT_PER_USER_PER_HOUR = int(os.getenv('PROD_CLAUDE_RATE_LIMIT_PER_USER_PER_HOUR', '200'))
    
    # Production budget limits
    MAX_MONTHLY_SPEND = float(os.getenv('PROD_MAX_MONTHLY_SPEND', '10.00'))  # Higher for production
    DAILY_SPENDING_LIMIT = float(os.getenv('PROD_DAILY_SPENDING_LIMIT', '1.00'))  # $1 per day
    
    # Force environment variables in production
    @staticmethod
    def init_app(app):
        Config.init_app(app)
        
        if os.getenv('FLASK_ENV') == 'production':
            if not os.getenv('SECRET_KEY'):
                raise ValueError("SECRET_KEY environment variable must be set in production")
            if not os.getenv('SMTP_PASSWORD'):
                raise ValueError("SMTP_PASSWORD environment variable must be set in production")
            
            # ===== NEW: Validate Claude configuration in production =====
            if not os.getenv('CLAUDE_API_KEY'):
                raise ValueError("CLAUDE_API_KEY environment variable must be set in production")
            
            api_key = os.getenv('CLAUDE_API_KEY')
            if not api_key.startswith('sk-ant-'):
                raise ValueError("Invalid CLAUDE_API_KEY format - should start with 'sk-ant-'")
            
            claude_model = os.getenv('PROD_CLAUDE_MODEL', 'claude-3-haiku-20240307')
            available_models = app.config.get('AVAILABLE_CLAUDE_MODELS', {})
            if claude_model not in available_models:
                raise ValueError(f"Invalid CLAUDE_MODEL: {claude_model}. Available: {list(available_models.keys())}")
            
            app.logger.info('Production mode - Claude API configured and validated')
        
        # Set up production logging
        import logging
        from logging.handlers import RotatingFileHandler
        
        if not os.path.exists('logs'):
            os.mkdir('logs')
        
        file_handler = RotatingFileHandler('logs/wellbeing.log', maxBytes=10240000, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Wellbeing app startup - Production mode with Claude API')


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
    
    # ===== NEW: Testing Claude Settings =====
    # Mock Claude settings for testing
    CLAUDE_API_KEY = 'sk-ant-test-key-for-testing-1234567890'  # Mock key
    CLAUDE_MODEL = 'claude-3-haiku-20240307'
    CLAUDE_MAX_TOKENS = 50  # Very short for tests
    CLAUDE_TEMPERATURE = 0.3  # Very consistent for testing
    CLAUDE_TIMEOUT = 5  # Shorter timeout for tests
    CLAUDE_RATE_LIMIT_PER_MINUTE = 100  # Higher for testing
    CLAUDE_RATE_LIMIT_PER_DAY = 1000
    CLAUDE_RATE_LIMIT_PER_USER_PER_HOUR = 200
    
    # No budget limits for testing
    MAX_MONTHLY_SPEND = 1000.00  # High limit to not interfere with tests
    DAILY_SPENDING_LIMIT = 100.00
    
    # Disable actual API calls in testing
    CLAUDE_MOCK_RESPONSES = True
    
    @staticmethod
    def init_app(app):
        Config.init_app(app)
        app.logger.info('Testing mode - using mock Claude configuration')
        app.logger.info('Claude API calls will be mocked in tests')


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}