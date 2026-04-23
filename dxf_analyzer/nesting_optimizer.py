"""
Модуль оптимизации раскроя деталей на листах материала.
Версия 4.0 - Продвинутая оптимизация с учетом реальной формы деталей.
Размещает детали любой сложной формы с поворотами под любым углом.
"""

import math
import logging
from typing import List, Tuple, Optional, Dict, Any, Set
from dataclasses import dataclass
from enum import Enum
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle
import streamlit as st
import pandas as pd
import numpy as np
from shapely.geometry import Polygon as ShapelyPolygon, Point, LineString
from shapely.affinity import rotate, translate
from shapely.ops import unary_union

logger = logging.getLogger(__name__)


# ==================== КЛАССЫ ДАННЫХ ====================

@dataclass
class PlacedPart:
    """Размещённая деталь на листе."""
    part_id: int
    part_name: str
    x: float
    y: float
    rotation: float  # угол поворота в градусах
    geometry: ShapelyPolygon  # реальная геометрия детали
    bounding_box: Tuple[float, float, float, float]  # minx, miny, maxx, maxy


@dataclass
class Sheet:
    """Лист материала с размещёнными деталями."""
    sheet_number: int
    width: float
    height: height
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
    parts_not_placed: int
    total_material_used: float
    total_waste: float
    average_efficiency: float
    algorithm_used: str


# ==================== ИЗВЛЕЧЕНИЕ ГЕОМЕТРИИ ЧЕРТЕЖА ====================

def extract_drawing_geometry(objects_data: List[Any]) -> Optional[ShapelyPolygon]:
    """
    Извлекает реальную геометрию ВСЕГО чертежа как полигон.
    
    Args:
        objects_data: Список DXFObject
    
    Returns:
        ShapelyPolygon или None если нет объектов
    """
    lines = []
    
    for obj in objects_data:
        if obj.entity is None:
            continue
        
        entity_type = obj.entity.dxftype()
        
        try:
            if entity_type == 'LINE':
                start = obj.entity.dxf.start
                end = obj.entity.dxf.end
                lines.append(LineString([(start.x, start.y), (end.x, end.y)]))
            
            elif entity_type == 'LWPOLYLINE':
                points = list(obj.entity.get_points('xy'))
                if len(points) >= 2:
                    line_coords = [(p[0], p[1]) for p in points]
                    if obj.entity.closed and len(points) >= 3:
                        polygon = ShapelyPolygon(line_coords)
                        if polygon.is_valid:
                            return polygon
                    else:
                        lines.append(LineString(line_coords))
            
            elif entity_type == 'POLYLINE':
                points = list(obj.entity.points())
                if len(points) >= 2:
                    line_coords = [(p.x, p.y) for p in points]
                    if obj.is_closed and len(points) >= 3:
                        polygon = ShapelyPolygon(line_coords)
                        if polygon.is_valid:
                            return polygon
                    else:
                        lines.append(LineString(line_coords))
            
            elif entity_type == 'CIRCLE':
                center = obj.entity.dxf.center
                radius = obj.entity.dxf.radius
                # Создаем приближенный круг
                circle_points = []
                for i in range(36):
                    angle = i * 10
                    x = center.x + radius * math.cos(math.radians(angle))
                    y = center.y + radius * math.sin(math.radians(angle))
                    circle_points.append((x, y))
                polygon = ShapelyPolygon(circle_points)
                if polygon.is_valid:
                    return polygon
            
            elif entity_type == 'ARC':
                center = obj.entity.dxf.center
                radius = obj.entity.dxf.radius
                start_angle = obj.entity.dxf.start_angle
                end_angle = obj.entity.dxf.end_angle
                
                arc_points = []
                angle_diff = end_angle - start_angle
                if angle_diff < 0:
                    angle_diff += 360
                
                steps = max(5, int(angle_diff / 10))
                for i in range(steps + 1):
                    angle = start_angle + (angle_diff * i / steps)
                    x = center.x + radius * math.cos(math.radians(angle))
                    y = center.y + radius * math.sin(math.radians(angle))
                    arc_points.append((x, y))
                
                lines.append(LineString(arc_points))
            
            elif entity_type == 'SPLINE':
                spline_points = []
                for pt in obj.entity.flattening(0.1):
                    spline_points.append((pt[0], pt[1]))
                
                if len(spline_points) >= 2:
                    lines.append(LineString(spline_points))
        
        except Exception as e:
            logger.debug(f"Ошибка извлечения геометрии для {entity_type}: {e}")
            continue
    
    if not lines:
        return None
    
    # Объединяем все линии в одну геометрию
    try:
        union = unary_union(lines)
        if union.is_empty:
            return None
        
        # Если получились замкнутые контуры, используем их
        if hasattr(union, 'geoms'):
            polygons = []
            for geom in union.geoms:
                if isinstance(geom, LineString) and len(geom.coords) >= 3:
                    # Пытаемся создать полигон из замкнутой линии
                    coords = list(geom.coords)
                    if coords[0] == coords[-1]:
                        poly = ShapelyPolygon(coords)
                        if poly.is_valid:
                            polygons.append(poly)
            
            if polygons:
                return unary_union(polygons)
        
        # Если не получилось создать полигоны, создаем охватывающий прямоугольник
        bounds = union.bounds
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        rect_coords = [
            (bounds[0], bounds[1]),
            (bounds[2], bounds[1]),
            (bounds[2], bounds[3]),
            (bounds[0], bounds[3]),
            (bounds[0], bounds[1])
        ]
        return ShapelyPolygon(rect_coords)
        
    except Exception as e:
        logger.error(f"Ошибка создания геометрии: {e}")
        return None


# ==================== АЛГОРИТМ РАСКРОЯ С УЧЕТОМ ФОРМЫ ====================

class AdvancedNestingOptimizer:
    """
    Продвинутый алгоритм раскроя с учетом реальной формы деталей.
    Поддерживает повороты под любым углом.
    """
    
    def __init__(self, sheet_width: float, sheet_height: float, 
                 spacing: float = 5.0, rotation_step: float = 15.0):
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.spacing = spacing
        self.rotation_step = rotation_step  # шаг поворота в градусах
    
    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """
        Выполняет оптимизацию раскроя для заданного количества деталей.
        
        Args:
            part_geometry: Реальная геометрия одной детали
            quantity: Количество деталей для размещения
        
        Returns:
            NestingResult с результатами размещения
        """
        sheets: List[Sheet] = []
        parts_placed = 0
        
        for part_num in range(1, quantity + 1):
            placed = False
            
            # Пробуем разместить на существующих листах
            for sheet in sheets:
                if self._try_place_on_sheet(sheet, part_num, part_geometry):
                    placed = True
                    parts_placed += 1
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
                
                if self._try_place_on_sheet(new_sheet, part_num, part_geometry):
                    sheets.append(new_sheet)
                    parts_placed += 1
                else:
                    # Деталь не влезает даже на новый лист
                    break
        
        parts_not_placed = quantity - parts_placed
        total_material_used = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        average_efficiency = sum(s.efficiency for s in sheets) / len(sheets) if sheets else 0
        
        return NestingResult(
            sheets=sheets,
            total_parts=quantity,
            parts_placed=parts_placed,
            parts_not_placed=parts_not_placed,
            total_material_used=total_material_used,
            total_waste=total_waste,
            average_efficiency=average_efficiency,
            algorithm_used="Advanced Shape-Based Nesting"
        )
    
    def _try_place_on_sheet(self, sheet: Sheet, part_id: int, geometry: ShapelyPolygon) -> bool:
        """
        Пытается разместить деталь на листе с оптимальным поворотом.
        """
        best_placement = None
        best_score = float('-inf')
        
        # Пробуем разные углы поворота
        angles = list(range(0, 360, int(self.rotation_step)))
        
        for angle in angles:
            # Поворачиваем деталь
            rotated_geom = rotate(geometry, angle, origin='centroid')
            
            # Находим лучшую позицию для этого угла
            position = self._find_best_position(sheet, rotated_geom)
            
            if position is not None:
                x, y = position
                
                # Оцениваем качество размещения
                score = self._evaluate_placement(sheet, x, y, rotated_geom)
                
                if score > best_score:
                    best_score = score
                    best_placement = (x, y, angle, rotated_geom)
        
        if best_placement is not None:
            x, y, angle, final_geom = best_placement
            
            # Размещаем деталь
            placed_part = PlacedPart(
                part_id=part_id,
                part_name=f"Деталь #{part_id}",
                x=x,
                y=y,
                rotation=angle,
                geometry=translate(final_geom, xoff=x, yoff=y),
                bounding_box=translate(final_geom, xoff=x, yoff=y).bounds
            )
            
            sheet.parts.append(placed_part)
            sheet.used_area += geometry.area
            sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
            
            return True
        
        return False
    
    def _find_best_position(self, sheet: Sheet, geometry: ShapelyPolygon) -> Optional[Tuple[float, float]]:
        """
        Находит лучшую позицию для размещения с учетом формы.
        """
        bounds = geometry.bounds
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        
        # Проверка, что деталь помещается на лист
        if width > self.sheet_width or height > self.sheet_height:
            return None
        
        best_position = None
        min_distance_to_others = float('inf')
        
        # Создаем сетку возможных позиций
        step_x = max(10, int(width / 5))
        step_y = max(10, int(height / 5))
        
        for x in range(0, int(self.sheet_width - width + 1), step_x):
            for y in range(0, int(self.sheet_height - height + 1), step_y):
                # Проверяем возможность размещения
                test_geom = translate(geometry, xoff=x, yoff=y)
                
                if self._can_place_at(sheet, test_geom):
                    # Оцениваем плотность размещения
                    distance_score = self._calculate_distance_score(sheet, test_geom)
                    
                    if distance_score < min_distance_to_others:
                        min_distance_to_others = distance_score
                        best_position = (x, y)
        
        # Если не нашли в сетке, пробуем Bottom-Left
        if best_position is None:
            # Пытаемся разместить в левом нижнем углу
            test_geom = translate(geometry, xoff=0, yoff=0)
            if self._can_place_at(sheet, test_geom):
                best_position = (0, 0)
        
        return best_position
    
    def _can_place_at(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        """
        Проверяет, можно ли разместить деталь в заданной позиции.
        """
        # Проверка выхода за границы листа
        bounds = geometry.bounds
        if (bounds[0] < 0 or bounds[1] < 0 or 
            bounds[2] > self.sheet_width or bounds[3] > self.sheet_height):
            return False
        
        # Проверка пересечения с другими деталями
        for part in sheet.parts:
            if geometry.intersects(part.geometry):
                distance = geometry.distance(part.geometry)
                if distance < self.spacing:
                    return False
        
        return True
    
    def _calculate_distance_score(self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        """
        Оценивает качество размещения по расстоянию до других деталей.
        """
        if not sheet.parts:
            return 0.0
        
        total_distance = 0.0
        for part in sheet.parts:
            distance = geometry.distance(part.geometry)
            total_distance += distance
        
        return -total_distance  # Минус потому что хотим максимизировать расстояние
    
    def _evaluate_placement(self, sheet: Sheet, x: float, y: float, geometry: ShapelyPolygon) -> float:
        """
        Оценивает качество размещения.
        """
        score = 0.0
        
        # Бонус за близость к другим деталям (плотная упаковка)
        if sheet.parts:
            min_distance = float('inf')
            for part in sheet.parts:
                test_geom = translate(geometry, xoff=x, yoff=y)
                distance = test_geom.distance(part.geometry)
                min_distance = min(min_distance, distance)
            
            # Чем ближе, тем выше оценка (но не меньше минимального отступа)
            if min_distance >= self.spacing:
                score += (100 - min_distance) * 0.1
        
        # Бонус за близость к краям (если это первая деталь)
        if not sheet.parts:
            edge_dist = min(x, y, self.sheet_width - x, self.sheet_height - y)
            score += (100 - edge_dist) * 0.05
        
        # Штраф за большой угол поворота (если нужно минимизировать повороты)
        # score -= abs(rotation) * 0.01
        
        return score


# ==================== ВИЗУАЛИЗАЦИЯ ====================

def visualize_nesting_result(result: NestingResult, sheet_index: int = 0) -> plt.Figure:
    """Визуализация раскроя с учетом реальной формы деталей."""
    if sheet_index >= len(result.sheets):
        raise ValueError(f"Лист #{sheet_index + 1} не найден")
    
    sheet = result.sheets[sheet_index]
    
    # Динамический размер фигуры
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
    
    # Границы листа
    sheet_rect = Rectangle(
        (0, 0), sheet.width, sheet.height,
        linewidth=4, edgecolor='#FF0000', facecolor='#E8E8E8',
        alpha=0.4, linestyle='--', label='Границы листа'
    )
    ax.add_patch(sheet_rect)
    
    if not sheet.parts:
        ax.text(
            sheet.width / 2, sheet.height / 2,
            'ЛИСТ ПУСТ\nНет размещённых деталей',
            ha='center', va='center',
            fontsize=20, color='#999999', weight='bold',
            bbox=dict(boxstyle='round,pad=1', facecolor='white', alpha=0.8)
        )
    else:
        # Цвета для деталей
        colors = plt.cm.Set3(np.linspace(0, 1, len(sheet.parts)))
        
        for i, part in enumerate(sheet.parts):
            # Получаем координаты полигона
            if isinstance(part.geometry, ShapelyPolygon):
                exterior_coords = list(part.geometry.exterior.coords)
                if len(exterior_coords) > 2:
                    # Рисуем полигон детали
                    polygon = Polygon(
                        exterior_coords,
                        linewidth=2.5, edgecolor='#000000', 
                        facecolor=colors[i % len(colors)],
                        alpha=0.85, zorder=10
                    )
                    ax.add_patch(polygon)
                    
                    # Центр детали
                    centroid = part.geometry.centroid
                    center_x, center_y = centroid.x, centroid.y
                    
                    # Подпись
                    ax.text(
                        center_x, center_y,
                        f"#{part.part_id}\n{part.rotation:.0f}°",
                        ha='center', va='center',
                        fontsize=10, fontweight='bold', color='#000000',
                        zorder=20,
                        bbox=dict(
                            boxstyle='round,pad=0.3',
                            facecolor='white',
                            alpha=0.95,
                            edgecolor='#333333',
                            linewidth=1.5
                        )
                    )
                    
                    # Отображаем направление поворота
                    if part.rotation != 0:
                        # Рисуем стрелку направления
                        arrow_length = min(part.geometry.bounds[2] - part.geometry.bounds[0],
                                         part.geometry.bounds[3] - part.geometry.bounds[1]) * 0.3
                        angle_rad = math.radians(part.rotation)
                        arrow_dx = arrow_length * math.cos(angle_rad)
                        arrow_dy = arrow_length * math.sin(angle_rad)
                        
                        ax.arrow(
                            center_x, center_y,
                            arrow_dx, arrow_dy,
                            head_width=5, head_length=8,
                            fc='red', ec='red',
                            zorder=15, alpha=0.8
                        )
    
    # Настройка осей
    margin_x = sheet.width * 0.03
    margin_y = sheet.height * 0.03
    
    ax.set_xlim(-margin_x, sheet.width + margin_x)
    ax.set_ylim(-margin_y, sheet.height + margin_y)
    ax.set_aspect('equal', adjustable='box')
    
    # Сетка
    ax.grid(True, alpha=0.4, linestyle=':', linewidth=1, color='#AAAAAA')
    
    # Деления осей
    step = max(100, int(sheet.width / 20) // 100 * 100)
    if sheet.width > 0:
        ax.set_xticks(range(0, int(sheet.width) + 1, step))
    if sheet.height > 0:
        ax.set_yticks(range(0, int(sheet.height) + 1, step))
    
    # Заголовок
    title_lines = [
        f"📄 ЛИСТ №{sheet.sheet_number}",
        f"Размер: {sheet.width:.0f} × {sheet.height:.0f} мм ({sheet.width/1000:.2f} × {sheet.height/1000:.2f} м)",
        f"Деталей: {len(sheet.parts)} | Эффективность: {sheet.efficiency:.1f}% | Отходы: {sheet.waste_percent:.1f}%"
    ]
    
    ax.set_title(
        '\n'.join(title_lines),
        fontsize=13, fontweight='bold',
        pad=20, loc='center'
    )
    
    ax.set_xlabel('Ширина (мм)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Высота (мм)', fontsize=11, fontweight='bold')
    
    # Легенда
    if sheet.parts:
        legend_elements = [
            plt.Line2D([0], [0], color='#FF0000', linewidth=4, linestyle='--', label='Границы листа'),
            plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='#888888',
                      markersize=10, label=f'Детали ({len(sheet.parts)} шт.)'),
            plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='red',
                      markersize=8, label='Направление поворота')
        ]
        ax.legend(
            handles=legend_elements,
            loc='upper right',
            fontsize=9,
            framealpha=0.95,
            edgecolor='black'
        )
    
    # Статистика
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
    """Экспортирует результат раскроя в CSV."""
    rows = []
    for sheet in result.sheets:
        for part in sheet.parts:
            bounds = part.bounding_box
            rows.append({
                'Лист': sheet.sheet_number,
                'Деталь №': part.part_id,
                'X центра (мм)': round((bounds[0] + bounds[2]) / 2, 2),
                'Y центра (мм)': round((bounds[1] + bounds[3]) / 2, 2),
                'Угол поворота (°)': round(part.rotation, 2),
                'Ширина габарита (мм)': round(bounds[2] - bounds[0], 2),
                'Высота габарита (мм)': round(bounds[3] - bounds[1], 2),
                'Площадь (мм²)': round(part.geometry.area, 2)
            })
    return pd.DataFrame(rows).to_csv(index=False, encoding='utf-8-sig')


def export_summary_to_csv(result: NestingResult) -> str:
    """Экспортирует сводку по листам в CSV."""
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
    """Отрисовывает вкладку оптимизации раскроя."""
    st.markdown("## 🔲 Продвинутая оптимизация раскроя")
    st.markdown("**Размещение деталей с учетом реальной формы и поворотов под любым углом.**")
    
    st.info("💡 **Логика:** Весь загруженный чертёж = 1 деталь. Алгоритм анализирует реальную форму и размещает копии с оптимальными поворотами.")
    
    if not objects_data:
        st.warning("⚠️ Нет данных для оптимизации. Загрузите и обработайте DXF файл.")
        return
    
    # Извлекаем реальную геометрию чертежа
    with st.spinner('🔍 Анализ геометрии чертежа...'):
        part_geometry = extract_drawing_geometry(objects_data)
    
    if not part_geometry:
        st.error("❌ Не удалось определить геометрию чертежа.")
        return
    
    # Показываем информацию о геометрии
    bounds = part_geometry.bounds
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    
    st.success("✅ Геометрия детали успешно определена!")
    
    col_info1, col_info2, col_info3, col_info4 = st.columns(4)
    with col_info1:
        st.metric("Ширина", f"{width:.2f} мм")
    with col_info2:
        st.metric("Высота", f"{height:.2f} мм")
    with col_info3:
        st.metric("Площадь", f"{part_geometry.area/1e6:.4f} м²")
    with col_info4:
        st.metric("Тип геометрии", "Полигон" if isinstance(part_geometry, ShapelyPolygon) else "Линии")
    
    # Предпросмотр геометрии
    with st.expander("🔍 Предпросмотр геометрии детали", expanded=True):
        fig, ax = plt.subplots(figsize=(10, 8), dpi=100)
        fig.patch.set_facecolor('#FFFFFF')
        ax.set_facecolor('#F8F8F8')
        
        if isinstance(part_geometry, ShapelyPolygon):
            exterior_coords = list(part_geometry.exterior.coords)
            if len(exterior_coords) > 2:
                polygon = Polygon(
                    exterior_coords,
                    linewidth=3, edgecolor='#0000FF', facecolor='#ADD8E6',
                    alpha=0.7
                )
                ax.add_patch(polygon)
        
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)
        ax.set_title("Геометрия детали", fontsize=14, fontweight='bold')
        ax.set_xlabel('X (мм)')
        ax.set_ylabel('Y (мм)')
        
        # Автоматические границы
        margin = max(width, height) * 0.1
        ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
        ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
        
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)
    
    st.markdown("---")
    
    # Настройки раскроя
    st.markdown("### ⚙️ Параметры раскроя")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Параметры листа материала:**")
        sheet_width = st.number_input(
            "Ширина листа (мм)",
            min_value=100.0, max_value=10000.0,
            value=3000.0, step=100.0
        )
        sheet_height = st.number_input(
            "Высота листа (мм)",
            min_value=100.0, max_value=10000.0,
            value=1500.0, step=100.0
        )
    
    with col2:
        st.markdown("**Настройки размещения:**")
        quantity = st.number_input(
            "Количество деталей",
            min_value=1, max_value=1000,
            value=10, step=1,
            help="Сколько копий детали нужно разместить"
        )
        spacing = st.number_input(
            "Минимальный отступ (мм)",
            min_value=0.0, max_value=100.0,
            value=5.0, step=1.0,
            help="Минимальное расстояние между деталями"
        )
        rotation_step = st.slider(
            "Точность поворота (°)",
            min_value=5.0, max_value=45.0,
            value=15.0, step=5.0,
            help="Шаг перебора углов поворота (меньше = точнее, но медленнее)"
        )
    
    st.markdown("---")
    
    # Кнопка запуска
    if st.button("🚀 Запустить оптимизацию", type="primary", use_container_width=True):
        with st.spinner(f'⏳ Оптимизация размещения {quantity} деталей...'):
            try:
                optimizer = AdvancedNestingOptimizer(
                    sheet_width, sheet_height, spacing, rotation_step
                )
                
                result = optimizer.optimize(part_geometry, quantity)
                
                st.session_state['nesting_result'] = result
                
                st.success("✅ Оптимизация завершена!")
                st.balloons()
            
            except Exception as e:
                st.error(f"❌ Ошибка при оптимизации: {e}")
                logger.error(f"Nesting optimization error: {e}")
                st.exception(e)
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
            st.metric("✅ Размещено", result.parts_placed)
        
        with col_r3:
            st.metric("❌ Не поместилось", result.parts_not_placed)
        
        with col_r4:
            st.metric("📈 Эффективность", f"{result.average_efficiency:.1f}%")
        
        with col_r5:
            st.metric("♻️ Отходы", f"{(result.total_waste / 1e6):.2f} м²")
        
        # Предупреждение
        if result.parts_not_placed > 0:
            st.error(
                f"⚠️ **{result.parts_not_placed} деталей не поместились!** "
                f"Увеличьте размер листа или уменьшите количество деталей."
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
        
        if len(result.sheets) > 1:
            sheet_to_view = st.selectbox(
                "Выберите лист для просмотра:",
                options=range(len(result.sheets)),
                format_func=lambda x: f"Лист #{x + 1} ({len(result.sheets[x].parts)} деталей, {result.sheets[x].efficiency:.1f}%)"
            )
        else:
            sheet_to_view = 0
            st.info(f"Показан лист #1 ({len(result.sheets[0].parts)} деталей)")
        
        try:
            fig = visualize_nesting_result(result, sheet_to_view)
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        except Exception as e:
            st.error(f"❌ Ошибка визуализации: {e}")
            logger.error(f"Visualization error: {e}")
            st.exception(e)
        
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
