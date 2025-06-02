from flask import Blueprint

connection_bp = Blueprint(
    'connection', 
    __name__, 
    url_prefix='/api/connection',
    template_folder='templates',
    static_folder='static'
)

from . import routes