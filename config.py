"""
Конфигурация приложения: константы, настройки, палитра цветов.
"""

import logging
import subprocess
import sys

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==================== ПРЕДЕЛЫ И ДОПУСКИ ====================
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

# Допуск для определения связности контуров
PIERCING_TOLERANCE = 0.1  # мм

# Типы с нулевой длиной
ZERO_LENGTH_TYPES = {'POINT', 'MLINE', 'INSERT', 'TEXT', 'ATTRIB', 'DIMENSION'}
SILENT_SKIP_TYPES = {'DIMENSION', 'VIEWPORT', 'LAYOUT', 'BLOCK'}

# ==================== ЦВЕТА СТАТУСОВ ====================
COLOR_ERROR_OVERLAY = '#FF0000'
COLOR_WARNING_OVERLAY = '#FF8800'
COLOR_NORMAL_OVERLAY = None

MARKER_COLOR_NORMAL = '#FFFFFF'
MARKER_BG_NORMAL = '#000000'
MARKER_COLOR_WARNING = '#000000'
MARKER_BG_WARNING = '#FF8800'
MARKER_COLOR_ERROR = '#FFFFFF'
MARKER_BG_ERROR = '#FF0000'

# ==================== ПАЛИТРА ACI ====================
ACI_COLORS = {
    0: '#000000', 1: '#FF0000', 2: '#FFFF00', 3: '#00FF00', 4: '#00FFFF',
    5: '#0000FF', 6: '#FF00FF', 7: '#FFFFFF', 8: '#414141', 9: '#808080',
    10: '#FF0000', 11: '#FFAAAA', 12: '#BD0000', 13: '#BD3D3D',
    14: '#840000', 15: '#843D3D', 16: '#FF3333', 17: '#FF6666',
    18: '#FF9999', 19: '#FFCCCC', 20: '#FF0000', 21: '#FFFF00',
    22: '#00FF00', 23: '#00FFFF', 24: '#0000FF', 25: '#FF00FF',
    26: '#FFFF80', 27: '#80FF80', 28: '#80FFFF', 29: '#8080FF', 30: '#FF80FF',
    256: '#000000', 257: '#FF0000',
}

COLOR_NAMES = {
    0: "Чёрный", 1: "Красный", 2: "Жёлтый", 3: "Зелёный",
    4: "Голубой", 5: "Синий", 6: "Пурпур", 7: "Белый",
    8: "Тёмно-серый", 9: "Серый", 256: "По слою", 257: "По блоку"
}


def get_aci_color(color_id: int) -> str:
    """Преобразует ACI номер цвета в HEX код."""
    if color_id in ACI_COLORS:
        return ACI_COLORS[color_id]
    
    if 1 <= color_id <= 255:
        base_colors = [
            '#000000', '#FF0000', '#FFFF00', '#00FF00', '#00FFFF',
            '#0000FF', '#FF00FF', '#FFFFFF', '#414141', '#808080'
        ]
        return base_colors[color_id % len(base_colors)]
    
    return '#000000'


def get_color_name(color_id: int) -> str:
    """Получает название цвета по ACI коду."""
    return COLOR_NAMES.get(color_id, f"Цвет {color_id}")


# ==================== АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ ====================
def install_dependencies():
    """Устанавливает необходимые библиотеки."""
    required = {
        'ezdxf': 'ezdxf>=1.3.0',
        'matplotlib': 'matplotlib>=3.8.0',
        'pandas': 'pandas>=2.2.0'
    }
    
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            print(f"📦 Установка {package}...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                package, "--no-cache-dir", "--quiet"
            ])