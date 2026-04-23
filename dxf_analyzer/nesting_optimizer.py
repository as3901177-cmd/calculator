"""
Модуль оптимизации раскроя деталей на листах материала.
Версия 2.0 с улучшенной визуализацией.
"""

import math
import logging
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import streamlit as st
import pandas as pd
from collections import defaultdict

logger = logging.getLogger(__name__)


# ==================== КЛАССЫ ДАННЫХ ====================

class RotationMode(Enum):
    """Режимы поворота деталей."""
    NO_ROTATION = "Без поворота"
    ROTATE_90 = "Только 90°"


@dataclass
class BoundingBox:
    """Габаритный прямоугольник детали."""
    width: float
    height: float
    area: float


@dataclass
class PlacedPart:
    """Размещённая деталь на листе."""
    part_id: int
    part_name: str
    x: float
    y: float
    width: float
    height: float
    rotated: bool
    original_width: float
    original_height: float
    area: float


@dataclass
class Sheet:
    """Лист материала с размещёнными деталями."""
    sheet_number: int
    width: float
    height: float
    parts: List[PlacedPart]
    used_area: float
    efficiency: float
    
    @property
    def total_area(self) -> float:
        return self.width * self.height
    
    @property
    def waste_area(self) -> float:
        return self.total_area - self.used_area
    
    @property
    def waste_percent(self) -> float:
        return (self.waste_area / self.total_area) * 100 if self.total_area > 0 else 0


@dataclass
class NestingResult:
    """Результат оптимизации раскроя."""
    sheets: List[Sheet]
    total_parts: int
    parts_placed: int
    parts_not_placed: List[int]
    total_material_used: float
    total_waste: float
    average_efficiency: float
    algorithm_used: str


# ==================== ИЗВЛЕЧЕНИЕ ГАБАРИТОВ ====================

def get_bounding_box_from_objects(objects_data: List[Any]) -> Dict[int, BoundingBox]:
    """
    Извлекает габаритные размеры для каждой цепи объектов.
    
    Args:
        objects_data: Список DXFObject
    
    Returns:
        Словарь {chain_id: BoundingBox}
    """
    chains_bounds = {}
    chains = defaultdict(list)
    
    # Группируем объекты по цепям
    for obj in objects_data:
        if obj.chain_id > 0:
            chains[obj.chain_id].append(obj)
    
    # Вычисляем габариты для каждой цепи
    for chain_id, chain_objects in chains.items():
        all_x = []
        all_y = []
        total_length = sum(obj.length for obj in chain_objects)
        
        for obj in chain_objects:
            if obj.entity is None:
                continue
            
            entity_type = obj.entity.dxftype()
            
            try:
                if entity_type == 'LINE':
                    start = obj.entity.dxf.start
                    end = obj.entity.dxf.end
                    all_x.extend([start.x, end.x])
                    all_y.extend([start.y, end.y])
                
                elif entity_type in ('CIRCLE', 'ARC'):
                    center = obj.entity.dxf.center
                    radius = obj.entity.dxf.radius
                    all_x.extend([center.x - radius, center.x + radius])
                    all_y.extend([center.y - radius, center.y + radius])
                
                elif entity_type == 'ELLIPSE':
                    center = obj.entity.dxf.center
                    major_axis = obj.entity.dxf.major_axis
                    ratio = obj.entity.dxf.ratio
                    a = math.sqrt(major_axis.x**2 + major_axis.y**2)
                    b = a * ratio
                    all_x.extend([center.x - a, center.x + a])
                    all_y.extend([center.y - b, center.y + b])
                
                elif entity_type == 'LWPOLYLINE':
                    points = list(obj.entity.get_points('xy'))
                    for p in points:
                        all_x.append(p[0])
                        all_y.append(p[1])
                
                elif entity_type == 'POLYLINE':
                    points = list(obj.entity.points())
                    for p in points:
                        all_x.append(p.x)
                        all_y.append(p.y)
                
                elif entity_type == 'SPLINE':
                    for pt in obj.entity.flattening(0.1):
                        all_x.append(pt[0])
                        all_y.append(pt[1])
            
            except Exception as e:
                logger.debug(f"Ошибка извлечения координат для {entity_type}: {e}")
                continue
        
        if all_x and all_y:
            width = max(all_x) - min(all_x)
            height = max(all_y) - min(all_y)
            # Используем реальную площадь габаритного прямоугольника
            area = width * height
            
            chains_bounds[chain_id] = BoundingBox(
                width=width,
                height=height,
                area=area
            )
    
    return chains_bounds


# ==================== АЛГОРИТМ РАСКРОЯ ====================

class FirstFitDecreasing:
    """
    Алгоритм First Fit Decreasing (FFD).
    Сортирует детали по убыванию площади и размещает в первый подходящий лист.
    """
    
    def __init__(self, sheet_width: float, sheet_height: float, 
                 spacing: float = 5.0, rotation_mode: RotationMode = RotationMode.ROTATE_90):
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.spacing = spacing
        self.rotation_mode = rotation_mode
    
    def optimize(self, parts: Dict[int, BoundingBox]) -> NestingResult:
        """
        Выполняет оптимизацию раскроя.
        
        Args:
            parts: Словарь {chain_id: BoundingBox}
        
        Returns:
            NestingResult с результатами размещения
        """
        # Сортируем детали по убыванию площади
        sorted_parts = sorted(parts.items(), key=lambda x: x[1].area, reverse=True)
        
        sheets: List[Sheet] = []
        parts_not_placed: List[int] = []
        
        for part_id, bbox in sorted_parts:
            placed = False
            
            # Пробуем разместить на существующих листах
            for sheet in sheets:
                if self._try_place_on_sheet(sheet, part_id, bbox):
                    placed = True
                    break
            
            # Если не поместилось, создаём новый лист
            if not placed:
                new_sheet = Sheet(
                    sheet_number=len(sheets) + 1,
                    width=self.sheet_width,
                    height=self.sheet_height,
                    parts=[], 
                    used_area=0.0, 
                    efficiency=0.0
                )
                
                if self._try_place_on_sheet(new_sheet, part_id, bbox):
                    sheets.append(new_sheet)
                else:
                    parts_not_placed.append(part_id)
        
        # Вычисляем статистику
        total_parts = len(parts)
        parts_placed = total_parts - len(parts_not_placed)
        total_material_used = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        average_efficiency = sum(s.efficiency for s in sheets) / len(sheets) if sheets else 0
        
        return NestingResult(
            sheets=sheets, 
            total_parts=total_parts, 
            parts_placed=parts_placed,
            parts_not_placed=parts_not_placed, 
            total_material_used=total_material_used,
            total_waste=total_waste, 
            average_efficiency=average_efficiency,
            algorithm_used="First Fit Decreasing (FFD)"
        )
    
    def _try_place_on_sheet(self, sheet: Sheet, part_id: int, bbox: BoundingBox) -> bool:
        """
        Пытается разместить деталь на листе.
        Использует алгоритм Bottom-Left для поиска позиции.
        """
        # Варианты размещения (с поворотом и без)
        orientations = [(bbox.width, bbox.height, False)]
        
        if self.rotation_mode != RotationMode.NO_ROTATION:
            orientations.append((bbox.height, bbox.width, True))
        
        for width, height, rotated in orientations:
            # Проверка, что деталь влезает в лист
            if width > self.sheet_width or height > self.sheet_height:
                continue
            
            # Ищем позицию Bottom-Left
            position = self._find_bottom_left_position(sheet, width, height)
            
            if position is not None:
                x, y = position
                
                # Размещаем деталь
                placed_part = PlacedPart(
                    part_id=part_id, 
                    part_name=f"Цепь {part_id}",
                    x=x, y=y, 
                    width=width, height=height, 
                    rotated=rotated,
                    original_width=bbox.width, 
                    original_height=bbox.height, 
                    area=bbox.area
                )
                
                sheet.parts.append(placed_part)
                sheet.used_area += bbox.area
                sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
                
                return True
        
        return False
    
    def _find_bottom_left_position(self, sheet: Sheet, width: float, height: float) -> Optional[Tuple[float, float]]:
        """
        Находит позицию для размещения методом Bottom-Left.
        Начинает с левого нижнего угла, двигается вправо и вверх.
        """
        # Создаём сетку возможных позиций
        candidate_positions = [(0, 0)]
        
        # Добавляем позиции от существующих деталей
        for part in sheet.parts:
            candidate_positions.append((part.x + part.width + self.spacing, part.y))
            candidate_positions.append((part.x, part.y + part.height + self.spacing))
        
        # Сортируем по Y (снизу вверх), затем по X (слева направо)
        candidate_positions.sort(key=lambda p: (p[1], p[0]))
        
        # Ищем первую подходящую позицию
        for x, y in candidate_positions:
            if self._can_place_at(sheet, x, y, width, height):
                return (x, y)
        
        return None
    
    def _can_place_at(self, sheet: Sheet, x: float, y: float, width: float, height: float) -> bool:
        """
        Проверяет, можно ли разместить деталь в позиции (x, y).
        """
        # Проверка выхода за границы листа
        if x + width > self.sheet_width or y + height > self.sheet_height:
            return False
        
        # Проверка пересечения с другими деталями
        for part in sheet.parts:
            if self._rectangles_overlap(
                x, y, width, height, 
                part.x, part.y, part.width, part.height
            ):
                return False
        
        return True
    
    def _rectangles_overlap(self, x1: float, y1: float, w1: float, h1: float,
                           x2: float, y2: float, w2: float, h2: float) -> bool:
        """
        Проверяет пересечение двух прямоугольников с учётом отступа.
        """
        return not (
            x1 + w1 + self.spacing <= x2 or 
            x2 + w2 + self.spacing <= x1 or
            y1 + h1 + self.spacing <= y2 or 
            y2 + h2 + self.spacing <= y1
        )


# ==================== ВИЗУАЛИЗАЦИЯ (УЛУЧШЕННАЯ) ====================

def visualize_nesting_result(result: NestingResult, sheet_index: int = 0) -> plt.Figure:
    """
    Визуализация раскроя с автомасштабированием и улучшенной контрастностью.
    
    Args:
        result: Результат оптимизации
        sheet_index: Индекс листа для отображения (0-based)
    
    Returns:
        Matplotlib фигура с визуализацией
    """
    if sheet_index >= len(result.sheets):
        raise ValueError(f"Лист #{sheet_index + 1} не найден")
    
    sheet = result.sheets[sheet_index]
    
    # Динамический размер фигуры в зависимости от пропорций листа
    aspect_ratio = sheet.width / sheet.height
    if aspect_ratio > 1.5:
        figsize = (16, 10)
    elif aspect_ratio < 0.67:
        figsize = (10, 16)
    else:
        figsize = (14, 12)
    
    fig, ax = plt.subplots(figsize=figsize, dpi=120)
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#F8F8F8')
    
    # Рисуем границы листа
    sheet_rect = Rectangle(
        (0, 0), sheet.width, sheet.height,
        linewidth=4, edgecolor='#FF0000', facecolor='#E8E8E8', 
        alpha=0.4, linestyle='--', label='Границы листа'
    )
    ax.add_patch(sheet_rect)
    
    # Рисуем детали с контрастными цветами
    import colorsys
    
    if not sheet.parts:
        # Если нет деталей, показываем пустой лист
        ax.text(
            sheet.width / 2, sheet.height / 2,
            'ЛИСТ ПУСТ\nНет размещённых деталей',
            ha='center', va='center',
            fontsize=20, color='#999999',
            weight='bold',
            bbox=dict(boxstyle='round,pad=1', facecolor='white', alpha=0.8)
        )
    else:
        for i, part in enumerate(sheet.parts):
            # Генерируем яркие контрастные цвета
            hue = (i * 0.618033988749895) % 1.0
            rgb = colorsys.hsv_to_rgb(hue, 0.7, 0.95)  # Увеличена насыщенность
            color = '#{:02x}{:02x}{:02x}'.format(
                int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)
            )
            
            # Рисуем прямоугольник детали
            part_rect = Rectangle(
                (part.x, part.y), part.width, part.height,
                linewidth=2.5, edgecolor='#000000', facecolor=color, 
                alpha=0.85, zorder=10
            )
            ax.add_patch(part_rect)
            
            # Центр детали
            center_x = part.x + part.width / 2
            center_y = part.y + part.height / 2
            
            # Метка поворота
            rotation_marker = " ↻" if part.rotated else ""
            
            # Размеры детали для подписи
            size_label = f"{part.width:.0f}×{part.height:.0f}"
            
            # Основная подпись (ID цепи)
            ax.text(
                center_x, center_y,
                f"Ц{part.part_id}{rotation_marker}",
                ha='center', va='center',
                fontsize=11, fontweight='bold', color='#000000',
                zorder=20,
                bbox=dict(
                    boxstyle='round,pad=0.4', 
                    facecolor='white', 
                    alpha=0.95,
                    edgecolor='#333333',
                    linewidth=1.5
                )
            )
            
            # Размеры детали (чуть ниже)
            ax.text(
                center_x, center_y - part.height * 0.25,
                size_label,
                ha='center', va='center',
                fontsize=8, color='#555555',
                zorder=20,
                style='italic'
            )
            
            # Координаты углов (для отладки)
            ax.plot(
                part.x, part.y, 
                marker='o', markersize=4, 
                color='#00FF00', zorder=15
            )
    
    # Настройка осей с небольшим отступом
    margin_x = sheet.width * 0.03
    margin_y = sheet.height * 0.03
    
    ax.set_xlim(-margin_x, sheet.width + margin_x)
    ax.set_ylim(-margin_y, sheet.height + margin_y)
    ax.set_aspect('equal', adjustable='box')
    
    # Сетка для удобства
    ax.grid(True, alpha=0.4, linestyle=':', linewidth=1, color='#AAAAAA')
    
    # Деления на осях (каждые 100 мм)
    step = max(100, int(sheet.width / 20) // 100 * 100)  # Адаптивный шаг
    if sheet.width > 0:
        ax.set_xticks(range(0, int(sheet.width) + 1, step))
    if sheet.height > 0:
        ax.set_yticks(range(0, int(sheet.height) + 1, step))
    
    # Заголовок с подробной информацией
    title_lines = [
        f"📄 ЛИСТ №{sheet.sheet_number}",
        f"Размер: {sheet.width:.0f} × {sheet.height:.0f} мм ({sheet.width/1000:.2f} × {sheet.height/1000:.2f} м)",
        f"Деталей: {len(sheet.parts)} | Эффективность: {sheet.efficiency:.1f}% | Отходы: {sheet.waste_percent:.1f}% ({sheet.waste_area/1e6:.3f} м²)"
    ]
    
    ax.set_title(
        '\n'.join(title_lines), 
        fontsize=13, fontweight='bold', 
        pad=20, loc='center'
    )
    
    # Подписи осей
    ax.set_xlabel('Ширина (мм)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Высота (мм)', fontsize=11, fontweight='bold')
    
    # Легенда
    if sheet.parts:
        legend_elements = [
            plt.Line2D([0], [0], color='#FF0000', linewidth=4, linestyle='--', label='Границы листа'),
            plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='#888888', 
                      markersize=10, label=f'Детали ({len(sheet.parts)} шт.)'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#00FF00',
                      markersize=6, label='Углы деталей')
        ]
        ax.legend(
            handles=legend_elements,
            loc='upper right',
            fontsize=9,
            framealpha=0.95,
            edgecolor='black'
        )
    
    # Статистика в углу
    stats_text = f"""
СТАТИСТИКА:
Площадь листа: {sheet.total_area/1e6:.3f} м²
Использовано: {sheet.used_area/1e6:.3f} м²
Отходы: {sheet.waste_area/1e6:.3f} м²
Эффективность: {sheet.efficiency:.1f}%
    """.strip()
    
    ax.text(
        0.02, 0.98, stats_text,
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
        family='monospace'
    )
    
    plt.tight_layout()
    return fig


# ==================== ЭКСПОРТ ====================

def export_nesting_to_csv(result: NestingResult) -> str:
    """
    Экспортирует результат раскроя в CSV формат.
    
    Returns:
        CSV строка
    """
    rows = []
    for sheet in result.sheets:
        for part in sheet.parts:
            rows.append({
                'Лист': sheet.sheet_number, 
                'ID цепи': part.part_id,
                'Название': part.part_name, 
                'X (мм)': round(part.x, 2),
                'Y (мм)': round(part.y, 2), 
                'Ширина (мм)': round(part.width, 2),
                'Высота (мм)': round(part.height, 2),
                'Повёрнуто': 'Да' if part.rotated else 'Нет',
                'Площадь (мм²)': round(part.area, 2)
            })
    return pd.DataFrame(rows).to_csv(index=False, encoding='utf-8-sig')


def export_summary_to_csv(result: NestingResult) -> str:
    """
    Экспортирует сводку по листам в CSV.
    
    Returns:
        CSV строка
    """
    rows = []
    for sheet in result.sheets:
        rows.append({
            'Номер листа': sheet.sheet_number, 
            'Ширина (мм)': sheet.width,
            'Высота (мм)': sheet.height, 
            'Деталей': len(sheet.parts),
            'Использовано (мм²)': round(sheet.used_area, 2),
            'Общая площадь (мм²)': round(sheet.total_area, 2),
            'Отходы (мм²)': round(sheet.waste_area, 2),
            'Эффективность (%)': round(sheet.efficiency, 2),
            'Отходы (%)': round(sheet.waste_percent, 2)
        })
    return pd.DataFrame(rows).to_csv(index=False, encoding='utf-8-sig')


# ==================== STREAMLIT ИНТЕРФЕЙС ====================

def render_nesting_optimizer_tab(objects_data: List[Any]):
    """
    Отрисовывает вкладку оптимизации раскроя в Streamlit.
    
    Args:
        objects_data: Список DXFObject из главного модуля
    """
    st.markdown("## 🔲 Оптимизация раскроя деталей")
    st.markdown("**Автоматическое размещение деталей на листах материала с минимизацией отходов.**")
    
    # Проверка наличия данных
    if not objects_data:
        st.warning("⚠️ Нет данных для оптимизации. Загрузите и обработайте DXF файл.")
        return
    
    # Извлекаем габариты деталей
    with st.spinner('🔍 Анализ габаритов деталей...'):
        parts = get_bounding_box_from_objects(objects_data)
    
    if not parts:
        st.warning("⚠️ Не найдено деталей с габаритами для раскроя.")
        st.info("💡 Убедитесь что чертёж обработан и найдены цепи объектов (chain_id > 0)")
        return
    
    st.success(f"✅ Найдено деталей для размещения: **{len(parts)}**")
    
    # Показываем габариты
    with st.expander("📏 Габариты деталей", expanded=False):
        parts_rows = [
            {
                'ID цепи': pid, 
                'Ширина (мм)': round(bbox.width, 2),
                'Высота (мм)': round(bbox.height, 2), 
                'Площадь (мм²)': round(bbox.area, 2)
            }
            for pid, bbox in sorted(parts.items())
        ]
        st.dataframe(pd.DataFrame(parts_rows), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Настройки раскроя
    st.markdown("### ⚙️ Параметры листа материала")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        sheet_width = st.number_input(
            "Ширина листа (мм)", 
            min_value=100.0, max_value=10000.0, 
            value=3000.0, step=100.0
        )
    
    with col2:
        sheet_height = st.number_input(
            "Высота листа (мм)", 
            min_value=100.0, max_value=10000.0, 
            value=1500.0, step=100.0
        )
    
    with col3:
        spacing = st.number_input(
            "Отступ между деталями (мм)", 
            min_value=0.0, max_value=100.0, 
            value=5.0, step=1.0,
            help="Минимальное расстояние между деталями"
        )
    
    # Дополнительные настройки
    rotation_mode = st.radio(
        "Режим поворота деталей:",
        options=[RotationMode.NO_ROTATION, RotationMode.ROTATE_90],
        format_func=lambda x: x.value,
        horizontal=True
    )
    
    st.markdown("---")
    
    # Кнопка запуска
    if st.button("🚀 Запустить оптимизацию", type="primary", use_container_width=True):
        with st.spinner('⏳ Выполняется оптимизация раскроя...'):
            try:
                optimizer = FirstFitDecreasing(
                    sheet_width, sheet_height, spacing, rotation_mode
                )
                
                result = optimizer.optimize(parts)
                
                st.session_state['nesting_result'] = result
                
                st.success("✅ Оптимизация завершена!")
            
            except Exception as e:
                st.error(f"❌ Ошибка при оптимизации: {e}")
                logger.error(f"Nesting optimization error: {e}")
                return
    
    # Отображение результатов
    if 'nesting_result' in st.session_state:
        result = st.session_state['nesting_result']
        
        st.markdown("---")
        st.markdown("### 📊 Результаты оптимизации")
        
        # Общая статистика
        col_r1, col_r2, col_r3, col_r4, col_r5 = st.columns(5)
        
        with col_r1:
            st.metric("📄 Листов", len(result.sheets))
        
        with col_r2:
            st.metric("✅ Размещено деталей", result.parts_placed)
        
        with col_r3:
            st.metric("❌ Не размещено", len(result.parts_not_placed))
        
        with col_r4:
            st.metric("📈 Средняя эффективность", f"{result.average_efficiency:.1f}%")
        
        with col_r5:
            st.metric("♻️ Общие отходы", f"{(result.total_waste / 1e6):.2f} м²")
        
        # Предупреждение если не все детали размещены
        if result.parts_not_placed:
            st.error(
                f"⚠️ **{len(result.parts_not_placed)} деталей не поместились на листы!** "
                f"Цепи: {', '.join(map(str, result.parts_not_placed))}. "
                f"Увеличьте размер листа или уменьшите детали."
            )
        
        st.markdown("---")
        
        # Детали по листам
        st.markdown("### 📋 Детализация по листам")
        
        summary_rows = [
            {
                'Лист №': s.sheet_number, 
                'Деталей': len(s.parts),
                'Использовано (м²)': round(s.used_area / 1e6, 4),
                'Отходы (м²)': round(s.waste_area / 1e6, 4),
                'Эффективность (%)': round(s.efficiency, 2),
                'Отходы (%)': round(s.waste_percent, 2)
            }
            for s in result.sheets
        ]
        
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
        
        # Визуализация
        st.markdown("### 🎨 Визуализация раскроя")
        
        sheet_to_view = st.selectbox(
            "Выберите лист для просмотра:",
            options=range(len(result.sheets)),
            format_func=lambda x: f"Лист #{x + 1} ({len(result.sheets[x].parts)} деталей, {result.sheets[x].efficiency:.1f}%)"
        )
        
        try:
            fig = visualize_nesting_result(result, sheet_to_view)
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        except Exception as e:
            st.error(f"❌ Ошибка визуализации: {e}")
            logger.error(f"Visualization error: {e}")
        
        # Экспорт
        st.markdown("### 💾 Экспорт результатов")
        
        col_e1, col_e2 = st.columns(2)
        
        with col_e1:
            st.download_button(
                label="📥 Скачать размещение деталей (CSV)",
                data=export_nesting_to_csv(result),
                file_name="nesting_details.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col_e2:
            st.download_button(
                label="📥 Скачать сводку по листам (CSV)",
                data=export_summary_to_csv(result),
                file_name="nesting_summary.csv",
                mime="text/csv",
                use_container_width=True
            )
