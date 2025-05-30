import os
import logging
from flask import Flask, render_template
from datetime import datetime
from flask_cors import CORS
from flask_pymongo import PyMongo
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
from flask_moment import Moment

app = Flask(__name__)
moment = Moment(app)

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize extensions
mongo = PyMongo()
scheduler = BackgroundScheduler()
bert_model = None

def create_app(test_config=None):
    """Create and configure the Flask application using a factory pattern."""
    app = Flask(__name__, instance_relative_config=True, 
                template_folder='../templates',    # Point to existing templates
                static_folder='../static')         # Point to existing static files
    
    # Load config
    if test_config is None:
        # Load the instance config, if it exists
        app.config.from_object('config.DevelopmentConfig')

    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)
    
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
    
    # Method override middleware to handle PUT and DELETE from forms
    from wellbeing.utils.middleware import MethodOverrideMiddleware
    app.wsgi_app = MethodOverrideMiddleware(app.wsgi_app)
    
    # Register blueprints
    from wellbeing.blueprints.auth import auth_bp
    from wellbeing.blueprints.dashboard import dashboard_bp
    from wellbeing.blueprints.admin import admin_bp
    from wellbeing.blueprints.tracking import tracking_bp
    from wellbeing.blueprints.chatbot import chatbot_bp
    from wellbeing.blueprints.therapist import therapist_bp

    # Import the API blueprint and initialize it
    from wellbeing.blueprints.api import init_blueprint
    api_bp = init_blueprint()  

    app.register_blueprint(auth_bp)
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
        from wellbeing.models import create_indexes
        create_indexes()
        from wellbeing.ml.model_loader import initialize_original_model, initialize_bert_model
        initialize_original_model()
        initialize_bert_model()
        from wellbeing.services.feedback_service import initialize_feedback_system
        initialize_feedback_system()
    
    return app