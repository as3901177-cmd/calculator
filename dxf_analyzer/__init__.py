"""
Модульная система для анализа DXF чертежей.
"""

from .config import (
    MAX_SPLINE_POINTS, SPLINE_FLATTENING, MAX_LENGTH, MIN_LENGTH,
    BULGE_EPSILON, COORD_EPSILON, PIERCING_TOLERANCE, MAX_FILE_SIZE_MB,
    get_aci_color, get_color_name
)