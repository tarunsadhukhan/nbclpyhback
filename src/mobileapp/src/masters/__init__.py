from flask import Blueprint

masters_bp = Blueprint('masters', __name__)

from src.mobileapp.src.masters.departments import departments_bp
from src.mobileapp.src.masters.shifts       import shifts_bp
from src.mobileapp.src.masters.occupations  import occupations_bp
