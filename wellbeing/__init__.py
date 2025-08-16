import os
import logging
from flask import Flask, render_template
from datetime import datetime
from flask_pymongo import PyMongo
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
from flask_moment import Moment
from wellbeing.extensions import socketio, mongo
from dotenv import load_dotenv  # ADD THIS IMPORT

app = Flask(__name__)
moment = Moment(app)

# CRITICAL FIX: Load .env file BEFORE any configuration
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize extensions
mongo = PyMongo()
scheduler = BackgroundScheduler()

def validate_claude_config(app):
    """Validate Claude API configuration."""
    api_key = app.config.get('CLAUDE_API_KEY')
    
    if not api_key:
        app.logger.warning('⚠ CLAUDE_API_KEY not configured - chatbot functionality will be limited')
        return False
    
    if not api_key.startswith('sk-ant-'):
        app.logger.error('❌ Invalid Claude API key format - should start with "sk-ant-"')
        return False
    
    # Basic validation - Claude keys are typically longer than 50 characters
    if len(api_key) < 50:
        app.logger.warning('⚠ Claude API key seems too short - please verify')
    
    # Get model info
    configured_model = app.config.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')  # UPDATED DEFAULT
    available_models = app.config.get('AVAILABLE_CLAUDE_MODELS', {})
    
    if configured_model in available_models:
        model_info = available_models[configured_model]
        app.logger.info(f'✅ Claude configured with model: {model_info["name"]}')
        app.logger.info(f'✅ Model description: {model_info["description"]}')
        app.logger.info(f'✅ Pricing: ${model_info["cost_input"]}/${model_info["cost_output"]} per M tokens')
    else:
        app.logger.warning(f'⚠ Model {configured_model} not found in available models')
    
    app.logger.info(f'✅ Max tokens per response: {app.config.get("CLAUDE_MAX_TOKENS")}')
    app.logger.info(f'✅ Monthly budget: ${app.config.get("MAX_MONTHLY_SPEND", 0)}')
    app.logger.info(f'✅ Daily budget: ${app.config.get("DAILY_SPENDING_LIMIT", 0)}')
    app.logger.info(f'✅ Crisis detection: {"enabled" if app.config.get("CRISIS_DETECTION_ENABLED") else "disabled"}')
    
    return True

def test_claude_connection(app):
    """Test Claude API connection during startup."""
    try:
        import anthropic
        
        api_key = app.config.get('CLAUDE_API_KEY')
        if not api_key:
            return False
            
        # Quick test to see if API key works
        client = anthropic.Anthropic(api_key=api_key)
        
        # Try a minimal API call
        test_response = client.messages.create(
            model=app.config.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514'),  # UPDATED DEFAULT
            max_tokens=5,
            messages=[{"role": "user", "content": "Test"}]
        )
        
        app.logger.info('✅ Claude API connection successful')
        app.logger.info(f'✅ Test response received ({len(test_response.content)} content blocks)')
        
        # Log usage info
        if hasattr(test_response, 'usage') and test_response.usage:
            app.logger.info(f'✅ API test used {test_response.usage.input_tokens} input + {test_response.usage.output_tokens} output tokens')
        
        return True
        
    except ImportError:
        app.logger.error('❌ Anthropic library not installed - run: pip install anthropic')
        return False
    except anthropic.AuthenticationError:
        app.logger.error('❌ Claude API authentication failed - check your API key')
        return False
    except anthropic.RateLimitError:
        app.logger.warning('⚠ Claude API rate limit hit during test - API is working but busy')
        return True  # Still working, just rate limited
    except Exception as e:
        app.logger.error(f'❌ Claude API connection test failed: {e}')
        return False

def validate_budget_config(app):
    """Validate budget configuration."""
    monthly_budget = app.config.get('MAX_MONTHLY_SPEND', 0)
    daily_budget = app.config.get('DAILY_SPENDING_LIMIT', 0)
    alert_threshold = app.config.get('USAGE_ALERT_THRESHOLD', 0)
    
    if monthly_budget <= 0:
        app.logger.warning('⚠ No monthly budget set - usage tracking will be limited')
        return False
    
    if daily_budget <= 0:
        app.logger.warning('⚠ No daily budget set - usage tracking will be limited')
    
    if alert_threshold >= monthly_budget:
        app.logger.warning('⚠ Alert threshold is >= monthly budget - adjust configuration')
    
    # Validate budget ratios
    if daily_budget * 31 > monthly_budget * 2:
        app.logger.warning('⚠ Daily budget seems high compared to monthly budget')
    
    # Estimate potential usage
    model_name = app.config.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')  # UPDATED DEFAULT
    available_models = app.config.get('AVAILABLE_CLAUDE_MODELS', {})
    
    if model_name in available_models:
        model_info = available_models[model_name]
        # Estimate conversations possible (assuming 200 input + 300 output tokens per conversation - UPDATED for shorter responses)
        estimated_cost_per_conversation = (200 / 1_000_000) * model_info['cost_input'] + (300 / 1_000_000) * model_info['cost_output']
        estimated_conversations = int(monthly_budget / estimated_cost_per_conversation)
        
        app.logger.info(f'✅ Budget configured for approximately {estimated_conversations:,} conversations per month')
        app.logger.info(f'✅ Estimated cost per conversation: ${estimated_cost_per_conversation:.4f}')
    
    return True

def create_app(test_config=None):
    """Create and configure the Flask application using a factory pattern."""
    app = Flask(__name__, instance_relative_config=True, 
                template_folder='../templates',    # Point to existing templates
                static_folder='../static')         # Point to existing static files
    
    # Load config
    if test_config is None:
        # Load the instance config, if it exists
        app.config.from_object('config.DevelopmentConfig')
        
        # CRITICAL FIX: Override config with .env values
        # This ensures .env values take precedence over config.py
        app.config.update({
            'CLAUDE_API_KEY': os.getenv('CLAUDE_API_KEY'),
            'CLAUDE_MODEL': os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514'),
            'CLAUDE_MAX_TOKENS': int(os.getenv('CLAUDE_MAX_TOKENS', 800)),  # UPDATED DEFAULT
            'CLAUDE_TEMPERATURE': float(os.getenv('CLAUDE_TEMPERATURE', 0.7)),
            'CLAUDE_TIMEOUT': int(os.getenv('CLAUDE_TIMEOUT', 30)),
            'CLAUDE_MAX_RETRIES': int(os.getenv('CLAUDE_MAX_RETRIES', 3)),
            'CLAUDE_RETRY_DELAY': float(os.getenv('CLAUDE_RETRY_DELAY', 1.0)),
            'CHATBOT_SYSTEM_PROMPT': os.getenv('CHATBOT_SYSTEM_PROMPT'),
            'CRISIS_DETECTION_ENABLED': os.getenv('CRISIS_DETECTION_ENABLED', 'True').lower() == 'true',
            'MAX_MONTHLY_SPEND': float(os.getenv('MAX_MONTHLY_SPEND', 5.00)),       # UPDATED DEFAULT
            'USAGE_ALERT_THRESHOLD': float(os.getenv('USAGE_ALERT_THRESHOLD', 4.00)), # UPDATED DEFAULT
            'DAILY_SPENDING_LIMIT': float(os.getenv('DAILY_SPENDING_LIMIT', 0.50)),   # UPDATED DEFAULT
        })
        
        # DEBUG: Print loaded configuration
        print("\n" + "="*60)
        print("🔧 CONFIGURATION LOADED FROM .ENV FILE")
        print("="*60)
        print(f"CLAUDE_MODEL: {app.config['CLAUDE_MODEL']}")
        print(f"CLAUDE_MAX_TOKENS: {app.config['CLAUDE_MAX_TOKENS']}")
        print(f"CLAUDE_API_KEY: {'✅ Set' if app.config['CLAUDE_API_KEY'] else '❌ Missing'}")
        prompt = app.config['CHATBOT_SYSTEM_PROMPT']
        print(f"CHATBOT_SYSTEM_PROMPT: {'✅ Set (' + str(len(prompt)) + ' chars)' if prompt else '❌ Missing'}")
        print(f"MAX_MONTHLY_SPEND: ${app.config['MAX_MONTHLY_SPEND']}")
        print(f"DAILY_SPENDING_LIMIT: ${app.config['DAILY_SPENDING_LIMIT']}")
        print(f"USAGE_ALERT_THRESHOLD: ${app.config['USAGE_ALERT_THRESHOLD']}")
        print("="*60 + "\n")
        
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)
    
    # NEW: Set app startup time for health checks
    app.config['app_start_time'] = datetime.now()
    
    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass
    
    # Configure upload folder
    UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    
    # Initialize extensions
    mongo.init_app(app)
    CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
    
    # Register Jinja filter
    def format_datetime(value):
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        return value

    app.jinja_env.filters['format_datetime'] = format_datetime
    
    # Fix for proxy headers
    app.wsgi_app = ProxyFix(app.wsgi_app)

    mongo.init_app(app)
    socketio.init_app(app)

    from wellbeing.utils.enhanced_scheduling import enhance_existing_scheduling_routes
    
    # Method override middleware to handle PUT and DELETE from forms
    from wellbeing.utils.middleware import MethodOverrideMiddleware
    app.wsgi_app = MethodOverrideMiddleware(app.wsgi_app)
    
    # Register blueprints
    from wellbeing.blueprints.auth import auth_bp
    from wellbeing.connection import connection_bp
    from wellbeing.blueprints.dashboard import dashboard_bp
    from wellbeing.blueprints.admin import admin_bp
    from wellbeing.blueprints.tracking import tracking_bp
    from wellbeing.blueprints.chatbot import chatbot_bp
    from wellbeing.blueprints.therapist import therapist_bp

    # Import the API blueprint and initialize it
    from wellbeing.blueprints.api import init_blueprint
    api_bp = init_blueprint()  

    app.register_blueprint(auth_bp)
    app.register_blueprint(connection_bp)
    app.register_blueprint(therapist_bp, url_prefix='/therapist')
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(tracking_bp)
    app.register_blueprint(chatbot_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
   
    # Set up error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('500.html'), 500

    
    # Initialize models and database indexes
    with app.app_context():
        # Initialize database indexes
        from wellbeing.models import create_indexes
        create_indexes()
        
        # REMOVED: Both model initializations (no longer needed)
        # OLD CODE (removed):
        # from wellbeing.ml.model_loader import initialize_original_model, initialize_bert_model
        # initialize_original_model()
        # initialize_bert_model()
        
        # NEW: Initialize Claude chatbot configuration
        logger.info("🤖 Initializing Claude AI chatbot configuration...")
        try:
            # Validate Claude configuration
            claude_config_valid = validate_claude_config(app)
            budget_config_valid = validate_budget_config(app)
            
            if claude_config_valid and budget_config_valid:
                # Test connection (optional - comment out if it slows startup)
                if not app.config.get('TESTING'):  # Skip API test during testing
                    connection_success = test_claude_connection(app)
                    if connection_success:
                        logger.info("✅ Claude AI chatbot initialization complete and tested")
                    else:
                        logger.warning("⚠ Claude API configuration valid but connection test failed")
                        logger.warning("⚠ Chatbot may still work but verify API key and network")
                else:
                    logger.info("✅ Claude AI chatbot configuration complete (testing mode - connection not tested)")
            else:
                logger.warning("⚠ Claude AI chatbot initialization incomplete - check configuration")
                
        except Exception as e:
            logger.error(f"❌ Claude AI initialization failed: {e}")
            logger.warning("⚠ Chatbot will use fallback responses")
        
        
        
        # ============== INITIALIZE AUTOMATED MODERATION SYSTEM ==============
        logger.info("Initializing automated message moderation system...")
        try:
            from wellbeing.utils.moderation_setup import initialize_automated_moderation, add_moderation_routes
            
            # Initialize the moderation system
            initialize_automated_moderation(app)
            
            # Add moderation routes
            add_moderation_routes(app)
            
            logger.info("✅ Automated moderation system initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize automated moderation: {e}")
            # Continue without moderation - the app should still work
        # ======================================================================

        # ============== INITIALIZE BUDGET TRACKING SYSTEM ==============
        logger.info("Initializing budget tracking system...")
        try:
            # Create budget tracking indexes if needed
            from wellbeing.models.chat import ensure_cost_tracking_indexes
            ensure_cost_tracking_indexes()
            
            # Initialize budget monitoring
            monthly_budget = app.config.get('MAX_MONTHLY_SPEND', 0)
            daily_budget = app.config.get('DAILY_SPENDING_LIMIT', 0)
            
            if monthly_budget > 0:
                logger.info(f"✅ Budget tracking initialized - Monthly: ${monthly_budget}, Daily: ${daily_budget}")
            else:
                logger.warning("⚠ Budget tracking disabled - no monthly budget set")
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize budget tracking: {e}")
        # ===============================================================

    enhance_existing_scheduling_routes()
    
    # NEW: Log final startup status with Claude-specific info
    logger.info("=" * 80)
    logger.info("🚀 AI-Powered Wellbeing Assistant Started Successfully (Claude Edition)")
    logger.info(f"📅 Startup time: {app.config['app_start_time']}")
    logger.info(f"🔧 Environment: {app.config.get('FLASK_ENV', 'unknown')}")
    
    # Claude-specific startup info
    claude_model = app.config.get('CLAUDE_MODEL', 'not configured')
    if claude_model != 'not configured':
        available_models = app.config.get('AVAILABLE_CLAUDE_MODELS', {})
        if claude_model in available_models:
            model_info = available_models[claude_model]
            logger.info(f"🤖 Claude Model: {model_info['name']} ({model_info['description']})")
            logger.info(f"💰 Model Cost: ${model_info['cost_input']}/${model_info['cost_output']} per M tokens")
        else:
            logger.info(f"🤖 Claude Model: {claude_model}")
    else:
        logger.warning("⚠ Claude Model: Not configured")
    
    # Budget info
    monthly_budget = app.config.get('MAX_MONTHLY_SPEND', 0)
    daily_budget = app.config.get('DAILY_SPENDING_LIMIT', 0)
    logger.info(f"💳 Budget Limits: ${monthly_budget}/month, ${daily_budget}/day")
    
    # Features status
    logger.info(f"🔐 Crisis Detection: {'enabled' if app.config.get('CRISIS_DETECTION_ENABLED') else 'disabled'}")
    logger.info(f"📊 Cost Tracking: {'enabled' if monthly_budget > 0 else 'disabled'}")
    logger.info(f"🎯 Max Tokens: {app.config.get('CLAUDE_MAX_TOKENS', 'not set')}")
    
    # Estimated usage
    if monthly_budget > 0 and claude_model in app.config.get('AVAILABLE_CLAUDE_MODELS', {}):
        model_info = app.config.get('AVAILABLE_CLAUDE_MODELS', {})[claude_model]
        # UPDATED: More accurate estimate for shorter responses
        estimated_cost_per_msg = (200 / 1_000_000) * model_info['cost_input'] + (300 / 1_000_000) * model_info['cost_output']
        estimated_messages = int(monthly_budget / estimated_cost_per_msg)
        logger.info(f"📈 Estimated Usage: ~{estimated_messages:,} conversations/month")
    
    logger.info("=" * 80)
    
    return app