"""
Drawing Module - Blueprint initialization
Contains all drawing meter entry related routes
"""
from flask import Blueprint

drawing_bp = Blueprint('drawing', __name__, url_prefix='/drawing')

# Import routes after blueprint creation to avoid circular imports
from . import routes

