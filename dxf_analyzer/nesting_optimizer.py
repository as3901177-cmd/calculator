"""
Модуль оптимизации раскроя деталей на листах материала.
Версия 4.2 - ПЛОТНАЯ УПАКОВКА с адаптивной стратегией для разных типов фигур.
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
from shapely.geometry import Polygon as ShapelyPolygon, Point, LineString, box
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
    height: float  # ✅ ИСПРАВЛЕНО
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


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_polygon_type(geometry: ShapelyPolygon) -> str:
    """Определяет тип полигона для выбора стратегии упаковки."""
    coords = list(geometry.exterior.coords)
    num_vertices = len(coords) - 1  # Последняя точка = первая
    
    if num_vertices == 3:
        return "triangle"
    elif num_vertices == 4:
        # Проверяем, прямоугольник или нет
        bounds = geometry.bounds
        area = geometry.area
        bbox_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        
        if abs(area - bbox_area) / bbox_area < 0.05:  # 5% погрешность
            return "rectangle"
        else:
            return "complex"
    else:
        return "complex"


def get_optimal_rotations_for_shape(shape_type: str, rotation_step: float) -> List[float]:
    """Возвращает оптимальные углы поворота для разных типов фигур."""
    if shape_type == "triangle":
        # Для треугольников: 0°, 60°, 120°, 180°, 240°, 300° (каждые 60°)
        # + промежуточные углы для плотности
        angles = []
        for base_angle in [0, 60, 120, 180, 240, 300]:
            angles.append(base_angle)
            # Добавляем промежуточные углы
            if rotation_step < 60:
                for offset in range(int(rotation_step), 60, int(rotation_step)):
                    angles.append(base_angle + offset)
        return sorted(set(angles))
    
    elif shape_type == "rectangle":
        # Для прямоугольников: 0° и 90°
        return [0, 90, 180, 270]
    
    else:
        # Для сложных фигур: полный перебор
        return list(range(0, 360, int(rotation_step)))


def calculate_convex_hull_efficiency(geometry: ShapelyPolygon) -> float:
    """Вычисляет коэффициент выпуклости формы."""
    convex_hull = geometry.convex_hull
    return geometry.area / convex_hull.area if convex_hull.area > 0 else 0


# ==================== ИЗВЛЕЧЕНИЕ ГЕОМЕТРИИ ====================

def extract_drawing_geometry(objects_data: List[Any]) -> Optional[ShapelyPolygon]:
    """Извлекает реальную геометрию всего чертежа как полигон."""
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
                    if obj.entity.is_closed and len(points) >= 3:
                        polygon = ShapelyPolygon(line_coords)
                        if polygon.is_valid:
                            return polygon
                    else:
                        lines.append(LineString(line_coords))
            
            elif entity_type == 'CIRCLE':
                center = obj.entity.dxf.center
                radius = obj.entity.dxf.radius
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
    
    try:
        union = unary_union(lines)
        if union.is_empty:
            return None
        
        # Пытаемся создать полигоны из замкнутых контуров
        if hasattr(union, 'geoms'):
            polygons = []
            for geom in union.geoms:
                if isinstance(geom, LineString) and len(geom.coords) >= 3:
                    coords = list(geom.coords)
                    if coords[0] == coords[-1]:
                        poly = ShapelyPolygon(coords)
                        if poly.is_valid:
                            polygons.append(poly)
            
            if polygons:
                return unary_union(polygons)
        
        # Создаем охватывающий прямоугольник
        bounds = union.bounds
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


# ==================== ПРОДВИНУТЫЙ АЛГОРИТМ РАСКРОЯ ====================

class AdvancedNestingOptimizer:
    """
    Продвинутый алгоритм раскроя с АДАПТИВНОЙ стратегией.
    Автоматически выбирает оптимальный метод упаковки для каждого типа фигуры.
    """
    
    def __init__(self, sheet_width: float, sheet_height: float, 
                 spacing: float = 5.0, rotation_step: float = 15.0):
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.spacing = spacing
        self.rotation_step = rotation_step
        self.shape_type = None
        self.optimal_rotations = None
    
    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Выполняет оптимизацию раскроя с адаптивной стратегией."""
        
        # Нормализуем геометрию
        normalized_geom = self._normalize_geometry(part_geometry)
        
        # Определяем тип фигуры
        self.shape_type = get_polygon_type(normalized_geom)
        logger.info(f"Detected shape type: {self.shape_type}")
        
        # Получаем оптимальные углы поворота
        self.optimal_rotations = get_optimal_rotations_for_shape(
            self.shape_type, self.rotation_step
        )
        logger.info(f"Using {len(self.optimal_rotations)} rotation angles: {self.optimal_rotations}")
        
        sheets: List[Sheet] = []
        parts_placed = 0
        
        for part_num in range(1, quantity + 1):
            placed = False
            
            # Пробуем разместить на существующих листах
            for sheet in sheets:
                if self._try_place_on_sheet(sheet, part_num, normalized_geom):
                    placed = True
                    parts_placed += 1
                    break
            
            # Создаём новый лист
            if not placed:
                new_sheet = Sheet(
                    sheet_number=len(sheets) + 1,
                    width=self.sheet_width,
                    height=self.sheet_height,
                    parts=[],
                    used_area=0.0,
                    efficiency=0.0
                )
                
                if self._try_place_on_sheet(new_sheet, part_num, normalized_geom):
                    sheets.append(new_sheet)
                    parts_placed += 1
                else:
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
            algorithm_used=f"Adaptive Nesting ({self.shape_type})"
        )
    
    def _normalize_geometry(self, geom: ShapelyPolygon) -> ShapelyPolygon:
        """Нормализует геометрию - перемещает центр в (0,0)."""
        bounds = geom.bounds
        center_x = (bounds[0] + bounds[2]) / 2
        center_y = (bounds[1] + bounds[3]) / 2
        return translate(geom, xoff=-center_x, yoff=-center_y)
    
    def _try_place_on_sheet(self, sheet: Sheet, part_id: int, geometry: ShapelyPolygon) -> bool:
        """Пытается разместить деталь на листе используя адаптивную стратегию."""
        
        best_placement = None
        best_score = float('inf')
        
        # Используем оптимальные углы для данного типа фигуры
        for angle in self.optimal_rotations:
            # Поворачиваем деталь
            rotated_geom = rotate(geometry, angle, origin='centroid')
            
            # Выбираем стратегию поиска позиции в зависимости от типа
            if self.shape_type == "triangle":
                positions = self._find_triangle_positions(sheet, rotated_geom, angle)
            else:
                positions = self._find_bottom_left_positions(sheet, rotated_geom)
            
            # Проверяем каждую позицию
            for x, y in positions:
                test_geom = translate(rotated_geom, xoff=x, yoff=y)
                
                if self._can_place_at(sheet, test_geom):
                    # Оцениваем размещение
                    score = self._evaluate_placement(sheet, test_geom, angle)
                    
                    if score < best_score:
                        best_score = score
                        best_placement = (x, y, angle, rotated_geom)
                        
                    # Для первой детали берем первую подходящую позицию
                    if not sheet.parts:
                        break
            
            if best_placement and not sheet.parts:
                break
        
        if best_placement is not None:
            x, y, angle, final_geom = best_placement
            
            # Перемещаем геометрию на позицию
            placed_geom = translate(final_geom, xoff=x, yoff=y)
            
            # Размещаем деталь
            placed_part = PlacedPart(
                part_id=part_id,
                part_name=f"Деталь #{part_id}",
                x=x,
                y=y,
                rotation=angle,
                geometry=placed_geom,
                bounding_box=placed_geom.bounds
            )
            
            sheet.parts.append(placed_part)
            sheet.used_area += geometry.area
            sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
            
            return True
        
        return False
    
    def _find_triangle_positions(self, sheet: Sheet, geometry: ShapelyPolygon, 
                                  angle: float) -> List[Tuple[float, float]]:
        """
        Специальная стратегия для треугольников - размещение вершина к основанию.
        """
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]
        
        positions = []
        
        # Если лист пуст - размещаем в углу
        if not sheet.parts:
            offset_x = -bounds[0]
            offset_y = -bounds[1]
            positions.append((offset_x, offset_y))
            return positions
        
        # Для треугольников: ищем позиции для плотной упаковки
        grid_step = 3  # Мелкая сетка для точности
        
        # 1. Позиции вдоль нижней границы
        for x in range(0, int(self.sheet_width - part_width + 1), grid_step):
            positions.append((x - bounds[0], -bounds[1]))
        
        # 2. Позиции около каждой размещенной детали
        for part in sheet.parts:
            part_bounds = part.bounding_box
            part_angle = part.rotation % 360
            current_angle = angle % 360
            
            # Определяем, является ли угол "перевернутым" (разница ~180°)
            angle_diff = abs(current_angle - part_angle) % 360
            is_inverted = (150 < angle_diff < 210) or (angle_diff < 30) or (angle_diff > 330)
            
            if is_inverted:
                # Размещаем ВПЛОТНУЮ для эффекта "вершина к основанию"
                tight_spacing = self.spacing * 0.5  # Уменьшенный отступ
            else:
                tight_spacing = self.spacing
            
            # Справа от детали
            x_right = part_bounds[2] + tight_spacing
            if x_right + part_width <= self.sheet_width:
                # Пробуем разные высоты
                for y_offset in range(-int(part_height), int(part_height) + 1, grid_step):
                    y_test = part_bounds[1] + y_offset
                    if 0 <= y_test <= self.sheet_height - part_height:
                        positions.append((x_right - bounds[0], y_test - bounds[1]))
            
            # Сверху от детали
            y_top = part_bounds[3] + tight_spacing
            if y_top + part_height <= self.sheet_height:
                # Пробуем разные позиции по горизонтали
                for x_offset in range(-int(part_width), int(part_width) + 1, grid_step):
                    x_test = part_bounds[0] + x_offset
                    if 0 <= x_test <= self.sheet_width - part_width:
                        positions.append((x_test - bounds[0], y_top - bounds[1]))
            
            # Слева от детали
            x_left = part_bounds[0] - part_width - tight_spacing
            if x_left >= 0:
                for y_offset in range(-int(part_height), int(part_height) + 1, grid_step):
                    y_test = part_bounds[1] + y_offset
                    if 0 <= y_test <= self.sheet_height - part_height:
                        positions.append((x_left - bounds[0], y_test - bounds[1]))
            
            # Позиции для плотной упаковки треугольников
            if is_inverted:
                # Пробуем разместить с минимальным зазором
                for x_offset in range(-int(part_width//2), int(part_width//2) + 1, grid_step):
                    for y_offset in range(-int(part_height//2), int(part_height//2) + 1, grid_step):
                        x_test = part_bounds[0] + x_offset
                        y_test = part_bounds[1] + y_offset
                        
                        if (0 <= x_test <= self.sheet_width - part_width and 
                            0 <= y_test <= self.sheet_height - part_height):
                            positions.append((x_test - bounds[0], y_test - bounds[1]))
        
        # Сортируем: приоритет нижним и левым позициям
        positions.sort(key=lambda p: (p[1], p[0]))
        
        return positions
    
    def _find_bottom_left_positions(self, sheet: Sheet, geometry: ShapelyPolygon) -> List[Tuple[float, float]]:
        """Bottom-Left стратегия для обычных фигур."""
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]
        
        positions = []
        
        if not sheet.parts:
            offset_x = -bounds[0]
            offset_y = -bounds[1]
            positions.append((offset_x, offset_y))
            return positions
        
        # Стандартная сетка
        step = 5
        
        # Вдоль границ
        for x in range(0, int(self.sheet_width - part_width + 1), step):
            positions.append((x - bounds[0], -bounds[1]))
        
        for y in range(0, int(self.sheet_height - part_height + 1), step):
            positions.append((-bounds[0], y - bounds[1]))
        
        # Около деталей
        for part in sheet.parts:
            part_bounds = part.bounding_box
            
            candidates = [
                (part_bounds[2] + self.spacing, part_bounds[1]),
                (part_bounds[2] + self.spacing, part_bounds[3] - part_height),
                (part_bounds[0], part_bounds[3] + self.spacing),
                (part_bounds[2] - part_width, part_bounds[3] + self.spacing),
                (part_bounds[0] - part_width - self.spacing, part_bounds[1]),
                (part_bounds[0] - part_width - self.spacing, part_bounds[3] - part_height)
            ]
            
            for x, y in candidates:
                if (0 <= x <= self.sheet_width - part_width and 
                    0 <= y <= self.sheet_height - part_height):
                    positions.append((x - bounds[0], y - bounds[1]))
        
        positions.sort(key=lambda p: (p[1], p[0]))
        return positions
    
    def _evaluate_placement(self, sheet: Sheet, geometry: ShapelyPolygon, angle: float) -> float:
        """
        Оценивает качество размещения.
        Меньше = лучше.
        """
        bounds = geometry.bounds
        
        # Базовая оценка: минимизируем высоту и ширину
        score = bounds[1] * 1000 + bounds[0]
        
        # Бонус за компактность (близость к другим деталям)
        if sheet.parts:
            min_distance = float('inf')
            for part in sheet.parts:
                distance = geometry.distance(part.geometry)
                min_distance = min(min_distance, distance)
            
            # Чем ближе к другим, тем лучше (но не меньше минимального отступа)
            if min_distance >= self.spacing:
                score -= (100 - min_distance) * 10
        
        # Небольшой штраф за угол поворота (предпочитаем меньше поворотов)
        normalized_angle = angle % 360
        if normalized_angle > 180:
            normalized_angle = 360 - normalized_angle
        score += normalized_angle * 0.1
        
        return score
    
    def _fits_on_sheet(self, geometry: ShapelyPolygon) -> bool:
        """Проверяет, помещается ли геометрия на лист."""
        bounds = geometry.bounds
        return (bounds[0] >= -0.1 and bounds[1] >= -0.1 and 
                bounds[2] <= self.sheet_width + 0.1 and bounds[3] <= self.sheet_height + 0.1)
    
    def _can_place_at(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        """Проверяет, можно ли разместить деталь в заданной позиции."""
        
        # Проверка границ листа
        if not self._fits_on_sheet(geometry):
            return False
        
        # Проверка пересечения с другими деталями
        for part in sheet.parts:
            # Создаем буфер для минимального отступа
            buffered_part = part.geometry.buffer(self.spacing)
            
            # Проверяем пересечение
            if geometry.intersects(buffered_part):
                return False
        
        return True


# ==================== ВИЗУАЛИЗАЦИЯ ====================

def visualize_nesting_result(result: NestingResult, sheet_index: int = 0) -> plt.Figure:
    """Визуализация раскроя с реальной формой деталей."""
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
        colors = plt.cm.tab20(np.linspace(0, 1, max(20, len(sheet.parts))))
        
        for i, part in enumerate(sheet.parts):
            if isinstance(part.geometry, ShapelyPolygon):
                exterior_coords = list(part.geometry.exterior.coords)
                if len(exterior_coords) > 2:
                    # Рисуем полигон детали
                    polygon = Polygon(
                        exterior_coords,
                        linewidth=2, edgecolor='#000000', 
                        facecolor=colors[i % len(colors)],
                        alpha=0.8, zorder=10
                    )
                    ax.add_patch(polygon)
                    
                    # Центр детали
                    centroid = part.geometry.centroid
                    center_x, center_y = centroid.x, centroid.y
                    
                    # Подпись
                    label_text = f"#{part.part_id}"
                    if part.rotation != 0:
                        label_text += f"\n{part.rotation:.0f}°"
                    
                    ax.text(
                        center_x, center_y,
                        label_text,
                        ha='center', va='center',
                        fontsize=9, fontweight='bold', color='#000000',
                        zorder=20,
                        bbox=dict(
                            boxstyle='round,pad=0.3',
                            facecolor='white',
                            alpha=0.9,
                            edgecolor='#333333',
                            linewidth=1
                        )
                    )
                    
                    # Стрелка направления поворота
                    if part.rotation != 0:
                        bounds = part.geometry.bounds
                        arrow_length = min(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.25
                        angle_rad = math.radians(part.rotation)
                        arrow_dx = arrow_length * math.cos(angle_rad)
                        arrow_dy = arrow_length * math.sin(angle_rad)
                        
                        ax.arrow(
                            center_x, center_y,
                            arrow_dx, arrow_dy,
                            head_width=arrow_length * 0.3,
                            head_length=arrow_length * 0.4,
                            fc='red', ec='red',
                            zorder=15, alpha=0.7, linewidth=1.5
                        )
    
    # Настройка осей
    margin_x = sheet.width * 0.02
    margin_y = sheet.height * 0.02
    
    ax.set_xlim(-margin_x, sheet.width + margin_x)
    ax.set_ylim(-margin_y, sheet.height + margin_y)
    ax.set_aspect('equal', adjustable='box')
    
    # Сетка
    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.8, color='#AAAAAA')
    
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
    
    # Статистика
    stats_text = f"""СТАТИСТИКА:
Площадь листа: {sheet.total_area/1e6:.3f} м²
Использовано: {sheet.used_area/1e6:.3f} м²
Отходы: {sheet.waste_area/1e6:.3f} м²
Эффективность: {sheet.efficiency:.1f}%"""
    
    ax.text(
        0.02, 0.98, stats_text,
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.85),
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
                'X (мм)': round(part.x, 2),
                'Y (мм)': round(part.y, 2),
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
    st.markdown("**Плотная упаковка деталей с учетом реальной формы и поворотов.**")
    
    st.info("💡 **Логика:** Весь загруженный чертёж = 1 деталь. Алгоритм автоматически определяет тип фигуры и применяет оптимальную стратегию упаковки.")
    
    if not objects_data:
        st.warning("⚠️ Нет данных для оптимизации. Загрузите и обработайте DXF файл.")
        return
    
    # Извлекаем геометрию
    with st.spinner('🔍 Анализ геометрии чертежа...'):
        part_geometry = extract_drawing_geometry(objects_data)
    
    if not part_geometry:
        st.error("❌ Не удалось определить геометрию чертежа.")
        return
    
    # Информация о геометрии
    bounds = part_geometry.bounds
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    shape_type = get_polygon_type(part_geometry)
    
    st.success(f"✅ Геометрия детали успешно определена! Тип: **{shape_type}**")
    
    col_info1, col_info2, col_info3, col_info4 = st.columns(4)
    with col_info1:
        st.metric("Ширина", f"{width:.2f} мм")
    with col_info2:
        st.metric("Высота", f"{height:.2f} мм")
    with col_info3:
        st.metric("Площадь", f"{part_geometry.area/1e6:.4f} м²")
    with col_info4:
        st.metric("Тип фигуры", shape_type.capitalize())
    
    # Предпросмотр геометрии
    with st.expander("🔍 Предпросмотр геометрии детали", expanded=False):
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
        ax.set_title(f"Геометрия детали ({shape_type})", fontsize=14, fontweight='bold')
        ax.set_xlabel('X (мм)')
        ax.set_ylabel('Y (мм)')
        
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
            value=20, step=1,
            help="Сколько копий детали нужно разместить"
        )
        spacing = st.number_input(
            "Минимальный отступ (мм)",
            min_value=0.0, max_value=100.0,
            value=5.0, step=1.0,
            help="Минимальное расстояние между деталями"
        )
        
        # Рекомендуемые углы в зависимости от типа
        if shape_type == "triangle":
            default_rotation = 15.0
            help_text = "Для треугольников рекомендуется 15° для плотной упаковки"
        elif shape_type == "rectangle":
            default_rotation = 90.0
            help_text = "Для прямоугольников достаточно 90°"
        else:
            default_rotation = 45.0
            help_text = "Для сложных фигур рекомендуется 15-45°"
        
        rotation_step = st.slider(
            "Точность поворота (°)",
            min_value=5.0, max_value=90.0,
            value=default_rotation, step=5.0,
            help=help_text
        )
    
    st.markdown("---")
    
    # Кнопка запуска
    if st.button("🚀 Запустить оптимизацию", type="primary", use_container_width=True):
        with st.spinner(f'⏳ Оптимизация размещения {quantity} деталей ({shape_type})...'):
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
