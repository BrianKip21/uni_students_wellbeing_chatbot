from flask import Blueprint

# Store the blueprint as a module-level variable
api_bp = Blueprint('api', __name__)

def init_blueprint():
    """Initialize the API blueprint with routes"""
    # Import route modules here to register routes with blueprint
    # before the blueprint is registered with the app
    import wellbeing.blueprints.api.users
    import wellbeing.blueprints.api.chat
    
    return api_bp