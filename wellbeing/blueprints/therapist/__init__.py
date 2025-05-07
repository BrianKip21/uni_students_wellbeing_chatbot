from flask import Blueprint

therapist_bp = Blueprint('therapist', __name__)

from . import routes