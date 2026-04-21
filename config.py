import logging
import math

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==================== КОНСТАНТЫ ====================
MAX_SPLINE_POINTS = 5000
SPLINE_FLATTENING = 0.01
MAX_LENGTH = 1_000_000
MIN_LENGTH = 1e-6
BULGE_EPSILON = 0.0001
COORD_EPSILON = 1e-10
ENTITY_COORD_PRECISION = 10
MAX_ENTITIES_PER_BLOCK = 10000
MAX_CENTER_POINTS = 500
MAX_FILE_SIZE_MB = 50
PIERCING_TOLERANCE = 0.1  # мм

# Палитра цветов ACI (AutoCAD Color Index)
ACI_COLORS = {
    0: '#000000', 1: '#FF0000', 2: '#FFFF00', 3: '#00FF00', 
    4: '#00FFFF', 5: '#0000FF', 6: '#FF00FF', 7: '#FFFFFF',
    8: '#414141', 9: '#808080', 256: '#000000', 257: '#FF0000'
}

def get_aci_color(color_id: int) -> str:
    """Преобразует ACI номер цвета в HEX код."""
    if color_id in ACI_COLORS:
        return ACI_COLORS[color_id]
    if 1 <= color_id <= 255:
        base_colors = ['#000000', '#FF0000', '#FFFF00', '#00FF00', '#00FFFF',
                       '#0000FF', '#FF00FF', '#FFFFFF', '#414141', '#808080']
        return base_colors[color_id % len(base_colors)]
    return '#000000'

def get_color_name(color_id: int) -> str:
    """Получает название цвета по ACI коду."""
    color_names = {
        0: "Чёрный", 1: "Красный", 2: "Жёлтый", 3: "Зелёный",
        4: "Голубой", 5: "Синий", 6: "Пурпур", 7: "Белый",
        8: "Тёмно-серый", 9: "Серый", 256: "По слою", 257: "По блоку"
    }
    return color_names.get(color_id, f"Цвет {color_id}")

# Цвета для интерфейса
COLOR_ERROR_OVERLAY = '#FF0000'
COLOR_WARNING_OVERLAY = '#FF8800'
MARKER_COLOR_NORMAL = '#FFFFFF'
MARKER_BG_NORMAL = '#000000'
MARKER_BG_WARNING = '#FF8800'
MARKER_BG_ERROR = '#FF0000'