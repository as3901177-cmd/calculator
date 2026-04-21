"""
Анализатор Чертежей CAD Pro v24.0

Модульная система для анализа DXF чертежей.
"""

from .config import (
    MAX_SPLINE_POINTS, SPLINE_FLATTENING, MAX_LENGTH, MIN_LENGTH,
    BULGE_EPSILON, COORD_EPSILON, PIERCING_TOLERANCE, MAX_FILE_SIZE_MB,
    get_aci_color, get_color_name, install_dependencies
)
from .models import DXFObject, ObjectStatus, ErrorSeverity, ProcessingIssue
from .errors import ErrorCollector
from .calculators import calculators
from .geometry import (
    get_entity_center, get_entity_center_with_offset,
    get_entity_endpoints, count_piercings_advanced, get_piercing_statistics
)
from .visualization import visualize_dxf_with_status_indicators

__version__ = "24.0"
__all__ = [
    'DXFObject', 'ObjectStatus', 'ErrorSeverity', 'ProcessingIssue',
    'ErrorCollector', 'calculators',
    'get_entity_center', 'get_entity_center_with_offset',
    'get_entity_endpoints', 'count_piercings_advanced', 'get_piercing_statistics',
    'visualize_dxf_with_status_indicators',
    'get_aci_color', 'get_color_name',
    'MAX_SPLINE_POINTS', 'SPLINE_FLATTENING', 'MAX_LENGTH', 'MIN_LENGTH',
    'PIERCING_TOLERANCE', 'MAX_FILE_SIZE_MB',
    'install_dependencies', '__version__'
]