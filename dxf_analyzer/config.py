"""
Конфигурация и константы приложения
"""

import subprocess
import sys
from typing import Dict

# ==================== КОНСТАНТЫ ====================
MAX_FILE_SIZE_MB = 50
MIN_LENGTH = 0.001
TOLERANCE = 0.1  # Допуск для определения связности объектов (мм)

# Типы объектов с нулевой длиной (не показываем ошибку)
ZERO_LENGTH_TYPES = {'POINT', 'INSERT', 'MTEXT', 'TEXT'}

# Типы, которые пропускаем без уведомления
SILENT_SKIP_TYPES = {
    'DIMENSION', 'LEADER', 'MLEADER', 'HATCH', 'SOLID', 'TRACE',
    'VIEWPORT', 'ATTDEF', 'ATTRIB', 'SEQEND', 'VERTEX', 'POLYLINE',
    'ACAD_TABLE', 'MTEXT', 'TEXT', 'POINT', 'INSERT', 'BLOCK'
}

# ==================== ЦВЕТА ACI (AutoCAD Color Index) ====================
ACI_COLORS: Dict[int, str] = {
    0: "#FFFFFF",  # ByBlock
    1: "#FF0000",  # Красный
    2: "#FFFF00",  # Жёлтый
    3: "#00FF00",  # Зелёный
    4: "#00FFFF",  # Голубой
    5: "#0000FF",  # Синий
    6: "#FF00FF",  # Пурпурный
    7: "#FFFFFF",  # Белый/Чёрный
    8: "#808080",  # Серый
    9: "#C0C0C0",  # Светло-серый
    256: "#FFFFFF", # ByLayer
}

COLOR_NAMES: Dict[int, str] = {
    0: "ByBlock",
    1: "Красный",
    2: "Жёлтый",
    3: "Зелёный",
    4: "Голубой",
    5: "Синий",
    6: "Пурпурный",
    7: "Белый/Чёрный",
    8: "Серый",
    9: "Светло-серый",
    256: "ByLayer",
}

def get_aci_color(color_code: int) -> str:
    """Возвращает HEX-цвет по коду ACI"""
    return ACI_COLORS.get(color_code, "#808080")

def get_color_name(color_code: int) -> str:
    """Возвращает название цвета по коду ACI"""
    if color_code in COLOR_NAMES:
        return COLOR_NAMES[color_code]
    return f"ACI {color_code}"

# ==================== АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ ====================
def install_dependencies():
    """Проверка и установка необходимых библиотек"""
    required = {
        'ezdxf': 'ezdxf>=1.1.0',
        'matplotlib': 'matplotlib>=3.7.0',
        'streamlit': 'streamlit>=1.28.0',
        'pandas': 'pandas>=2.0.0',
        'numpy': 'numpy>=1.24.0'
    }
    
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"📦 Установка недостающих пакетов: {', '.join(missing)}")
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', '--quiet', *missing
        ])
        print("✅ Все зависимости установлены")