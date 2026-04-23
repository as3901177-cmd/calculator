"""
Продвинутый алгоритм раскроя с поддержкой произвольных треугольников.
Версия 2.3 - с улучшенным извлечением геометрии из DXF.
"""

import math
from typing import List, Optional, Tuple, Any
from dataclasses import dataclass, field
import logging
from enum import Enum

# Безопасный импорт Shapely
try:
    from shapely.geometry import Polygon as ShapelyPolygon, Point, LineString
    from shapely.affinity import translate, rotate
    from shapely.strtree import STRtree
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    ShapelyPolygon = Any
    print("Warning: shapely is not installed. Run: pip install shapely")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Типы данных
# ---------------------------------------------------------------------------

class TriangleType(Enum):
    """Типы треугольников по углам."""
    ACUTE = "acute"
    RIGHT = "right"
    OBTUSE = "obtuse"
    EQUILATERAL = "equilateral"
    ISOSCELES = "isosceles"


@dataclass
class PlacedPart:
    part_id: int
    part_name: str
    x: float
    y: float
    rotation: float
    geometry: ShapelyPolygon
    bounding_box: tuple


@dataclass
class Sheet:
    sheet_number: int
    width: float
    height: float
    parts: List[PlacedPart] = field(default_factory=list)
    used_area: float = 0.0
    efficiency: float = 0.0
    spatial_index: Optional[Any] = None
    
    def rebuild_spatial_index(self):
        if self.parts and SHAPELY_AVAILABLE:
            self.spatial_index = STRtree([p.geometry for p in self.parts])
    
    @property
    def total_area(self) -> float:
        return self.width * self.height
    
    @property
    def waste_area(self) -> float:
        return self.total_area - self.used_area


@dataclass
class NestingResult:
    sheets: List[Sheet]
    total_parts: int
    parts_placed: int
    parts_not_placed: int
    total_material_used: float
    total_waste: float
    average_efficiency: float
    algorithm_used: str


# ---------------------------------------------------------------------------
# УЛУЧШЕННАЯ КОНВЕРТАЦИЯ DXF → Shapely
# ---------------------------------------------------------------------------

def dxf_object_to_shapely(dxf_obj: Any) -> Optional[ShapelyPolygon]:
    """
    Улучшенная конвертация DXF объекта в Shapely Polygon.
    Поддерживает различные форматы DXF объектов.
    """
    if not SHAPELY_AVAILABLE or dxf_obj is None:
        return None
    
    vertices = []
    
    try:
        # Случай 1: Объект имеет атрибут 'entity' (из ezdxf)
        if hasattr(dxf_obj, 'entity'):
            entity = dxf_obj.entity
            entity_type = entity.dxftype() if hasattr(entity, 'dxftype') else None
            
            # POLYLINE
            if hasattr(entity, 'vertices'):
                for v in entity.vertices:
                    if hasattr(v, 'dxf'):
                        vertices.append((float(v.dxf.x), float(v.dxf.y)))
                    elif hasattr(v, 'x') and hasattr(v, 'y'):
                        vertices.append((float(v.x), float(v.y)))
            
            # LWPOLYLINE
            elif hasattr(entity, 'points'):
                for p in entity.points():
                    if isinstance(p, (tuple, list)) and len(p) >= 2:
                        vertices.append((float(p[0]), float(p[1])))
                    elif hasattr(p, 'x') and hasattr(p, 'y'):
                        vertices.append((float(p.x), float(p.y)))
            
            # LINE - для линий нужно создать полигон из 4 точек (толщина)
            elif entity_type == 'LINE':
                if hasattr(entity, 'dxf'):
                    start = entity.dxf.start
                    end = entity.dxf.end
                    # Создаем прямоугольник толщиной 1мм
                    thickness = 1.0
                    vertices = [
                        (float(start.x), float(start.y)),
                        (float(end.x), float(end.y)),
                        (float(end.x + thickness), float(end.y + thickness)),
                        (float(start.x + thickness), float(start.y + thickness))
                    ]
            
            # CIRCLE
            elif entity_type == 'CIRCLE':
                center = entity.dxf.center
                radius = entity.dxf.radius
                # Аппроксимируем круг 36-угольником
                for i in range(36):
                    angle = i * 10 * math.pi / 180
                    x = center.x + radius * math.cos(angle)
                    y = center.y + radius * math.sin(angle)
                    vertices.append((float(x), float(y)))
        
        # Случай 2: Прямой доступ к атрибутам
        elif hasattr(dxf_obj, 'vertices'):
            for v in dxf_obj.vertices:
                if hasattr(v, 'dxf'):
                    vertices.append((float(v.dxf.x), float(v.dxf.y)))
                elif hasattr(v, 'x') and hasattr(v, 'y'):
                    vertices.append((float(v.x), float(v.y)))
        
        elif hasattr(dxf_obj, 'points'):
            for p in dxf_obj.points():
                if isinstance(p, (tuple, list)) and len(p) >= 2:
                    vertices.append((float(p[0]), float(p[1])))
        
        # Случай 3: Объект уже является списком точек
        elif isinstance(dxf_obj, (list, tuple)) and len(dxf_obj) >= 3:
            for p in dxf_obj:
                if isinstance(p, (tuple, list)) and len(p) >= 2:
                    vertices.append((float(p[0]), float(p[1])))
        
        # Случай 4: Объект имеет атрибуты x, y (точка)
        elif hasattr(dxf_obj, 'x') and hasattr(dxf_obj, 'y'):
            vertices = [(float(dxf_obj.x), float(dxf_obj.y))]
        
        if len(vertices) < 3:
            return None
        
        # Создаем полигон
        poly = ShapelyPolygon(vertices)
        
        # Если полигон невалидный, пробуем исправить
        if not poly.is_valid:
            poly = poly.buffer(0)
        
        # Если после исправления все еще невалидный, создаем bounding box
        if not poly.is_valid or poly.is_empty:
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            poly = ShapelyPolygon([
                (min_x, min_y), (max_x, min_y),
                (max_x, max_y), (min_x, max_y)
            ])
        
        return poly if not poly.is_empty else None
        
    except Exception as e:
        logger.error(f"Failed to convert DXF to Shapely: {e}")
        return None


def extract_all_geometries(objects_data: List[Any]) -> List[Tuple[int, ShapelyPolygon, dict]]:
    """
    Извлекает все геометрии из списка DXF объектов.
    Возвращает список кортежей (индекс, геометрия, информация).
    """
    geometries = []
    
    for i, obj in enumerate(objects_data):
        if obj is None:
            continue
        
        geom = dxf_object_to_shapely(obj)
        
        if geom is not None and not geom.is_empty:
            bounds = geom.bounds
            info = {
                'index': i,
                'type': get_polygon_type(geom),
                'width': bounds[2] - bounds[0],
                'height': bounds[3] - bounds[1],
                'area': geom.area,
                'vertices': len(list(geom.exterior.coords)) - 1
            }
            geometries.append((i, geom, info))
            logger.info(f"Extracted geometry from object {i}: {info['type']}, area={info['area']:.2f}")
        else:
            logger.warning(f"Could not extract geometry from object {i}")
            # Выводим информацию об объекте для отладки
            if hasattr(obj, 'entity'):
                entity_type = obj.entity.dxftype() if hasattr(obj.entity, 'dxftype') else 'unknown'
                logger.warning(f"  Object {i} entity type: {entity_type}")
            elif hasattr(obj, 'dxftype'):
                logger.warning(f"  Object {i} dxftype: {obj.dxftype()}")
            else:
                logger.warning(f"  Object {i} type: {type(obj)}")
    
    return geometries


def get_polygon_type(geom: ShapelyPolygon) -> str:
    """Определяет тип полигона."""
    if not SHAPELY_AVAILABLE or geom is None or geom.is_empty:
        return "unknown"
    
    try:
        coords = list(geom.exterior.coords)[:-1]
        num_vertices = len(coords)
        
        if num_vertices == 3:
            # Проверяем, треугольник ли это
            return "triangle"
        elif num_vertices == 4:
            # Проверяем, прямоугольник
            bounds = geom.bounds
            rect_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
            if abs(geom.area - rect_area) / rect_area < 0.05:
                return "rectangle"
            else:
                return "quadrilateral"
        else:
            return f"polygon_{num_vertices}"
    except:
        return "unknown"


# ---------------------------------------------------------------------------
# Геометрия тесселяции треугольников
# ---------------------------------------------------------------------------

Vec2 = Tuple[float, float]


def get_triangle_vertices(geom: ShapelyPolygon) -> List[Vec2]:
    """Извлекает вершины треугольника."""
    coords = list(geom.exterior.coords)[:-1]
    if len(coords) != 3:
        raise ValueError(f"Not a triangle, has {len(coords)} vertices")
    return [(float(x), float(y)) for x, y in coords]


def get_longest_edge(verts: List[Vec2]) -> Tuple[int, int, float]:
    """Находит самое длинное ребро треугольника."""
    edges = [
        (0, 1, math.hypot(verts[1][0] - verts[0][0], verts[1][1] - verts[0][1])),
        (1, 2, math.hypot(verts[2][0] - verts[1][0], verts[2][1] - verts[1][1])),
        (2, 0, math.hypot(verts[0][0] - verts[2][0], verts[0][1] - verts[2][1]))
    ]
    return max(edges, key=lambda e: e[2])


def reflect_point_over_line(p: Vec2, a: Vec2, b: Vec2) -> Vec2:
    """Отражает точку относительно прямой AB."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    
    if length_sq < 1e-12:
        return p
    
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    proj_x = a[0] + t * dx
    proj_y = a[1] + t * dy
    
    return (2 * proj_x - p[0], 2 * proj_y - p[1])


def get_tessellation_params(geom: ShapelyPolygon) -> Optional[dict]:
    """Создает параметры для тесселяции треугольника."""
    try:
        verts = get_triangle_vertices(geom)
        edge1, edge2, base_length = get_longest_edge(verts)
        
        base_verts = (verts[edge1], verts[edge2])
        apex_idx = 3 - edge1 - edge2
        apex = verts[apex_idx]
        
        # Вычисляем высоту
        x1, y1 = base_verts[0]
        x2, y2 = base_verts[1]
        x3, y3 = apex
        area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2
        height = 2 * area / base_length if base_length > 0 else 0
        
        # Отражаем вершину
        reflected_apex = reflect_point_over_line(apex, base_verts[0], base_verts[1])
        
        # Нормализуем координаты
        min_y = min(base_verts[0][1], base_verts[1][1])
        
        original_verts = [(v[0] - base_verts[0][0], v[1] - min_y) for v in verts]
        reflected_verts = [
            (0, 0),
            (base_length, 0),
            (reflected_apex[0] - base_verts[0][0], reflected_apex[1] - min_y)
        ]
        
        return {
            'original': original_verts,
            'reflected': reflected_verts,
            'base_length': base_length,
            'height': height,
        }
        
    except Exception as e:
        logger.error(f"Tessellation error: {e}")
        return None


# ---------------------------------------------------------------------------
# Основной класс оптимизатора
# ---------------------------------------------------------------------------

class AdvancedNestingOptimizer:
    """Продвинутый алгоритм раскроя."""
    
    def __init__(
        self,
        sheet_width: float,
        sheet_height: float,
        spacing: float = 5.0,
        rotation_step: float = 15.0,
    ):
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.spacing = spacing
        self.rotation_step = rotation_step
    
    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Выполняет оптимизацию раскроя."""
        if not SHAPELY_AVAILABLE:
            return self._create_empty_result(quantity, "Shapely not available")
        
        try:
            # Нормализуем геометрию
            bounds = part_geometry.bounds
            cx = (bounds[0] + bounds[2]) / 2
            cy = (bounds[1] + bounds[3]) / 2
            normalized = translate(part_geometry, xoff=-cx, yoff=-cy)
            
            # Определяем тип
            coords = list(normalized.exterior.coords)
            
            if len(coords) - 1 == 3:
                return self._optimize_triangle(normalized, quantity)
            else:
                return self._optimize_general(normalized, quantity)
                
        except Exception as e:
            logger.error(f"Optimization error: {e}")
            return self._create_empty_result(quantity, str(e))
    
    def _create_empty_result(self, quantity: int, error_msg: str) -> NestingResult:
        return NestingResult(
            sheets=[], total_parts=quantity, parts_placed=0, parts_not_placed=quantity,
            total_material_used=0.0, total_waste=0.0, average_efficiency=0.0,
            algorithm_used=f"Failed: {error_msg}"
        )
    
    def _optimize_triangle(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Оптимизирует раскрой треугольников."""
        best_result = None
        best_count = 0
        
        for base_angle in [0, 90, 180, 270]:
            try:
                rotated = rotate(part_geometry, base_angle, origin="centroid")
                
                params = get_tessellation_params(rotated)
                if not params:
                    continue
                
                result = self._place_triangles_by_tessellation(
                    rotated, params, quantity, base_angle
                )
                
                if result.parts_placed > best_count:
                    best_count = result.parts_placed
                    best_result = result
                    
                if best_count == quantity:
                    break
                    
            except Exception as exc:
                logger.warning(f"Tessellation at {base_angle}° failed: {exc}")
                continue
        
        if best_result is None or best_result.parts_placed == 0:
            return self._optimize_general(part_geometry, quantity)
        
        return best_result
    
    def _place_triangles_by_tessellation(
        self, part_geometry: ShapelyPolygon, params: dict,
        quantity: int, base_angle: float
    ) -> NestingResult:
        """Размещает треугольники с использованием тесселяции."""
        sheets: List[Sheet] = []
        parts_placed = 0
        part_area = part_geometry.area
        
        base_length = params['base_length']
        height = params['height']
        
        if base_length <= 0 or height <= 0:
            return self._create_empty_result(quantity, "Invalid triangle dimensions")
        
        col_step = base_length + self.spacing
        row_step = height + self.spacing
        
        cols_per_row = max(1, int((self.sheet_width - self.spacing * 2) / col_step))
        rows = max(1, int((self.sheet_height - self.spacing * 2) / row_step))
        
        part_id = 1
        
        for row in range(rows):
            if part_id > quantity:
                break
            
            for col in range(cols_per_row):
                if part_id > quantity:
                    break
                
                if not sheets or len(sheets[-1].parts) >= 100:
                    sheets.append(Sheet(
                        sheet_number=len(sheets) + 1,
                        width=self.sheet_width,
                        height=self.sheet_height
                    ))
                
                current_sheet = sheets[-1]
                
                x = self.spacing + col * col_step
                y = self.spacing + row * row_step
                
                if x + base_length <= self.sheet_width - self.spacing and y + height <= self.sheet_height - self.spacing:
                    
                    # Оригинальный треугольник
                    verts = params['original']
                    geom1 = ShapelyPolygon([(x + v[0], y + v[1]) for v in verts])
                    
                    if self._can_place_on_sheet(current_sheet, geom1):
                        current_sheet.parts.append(PlacedPart(
                            part_id=part_id,
                            part_name=f"Деталь #{part_id}",
                            x=x, y=y,
                            rotation=base_angle,
                            geometry=geom1,
                            bounding_box=geom1.bounds
                        ))
                        current_sheet.used_area += part_area
                        parts_placed += 1
                        part_id += 1
                    
                    # Отраженный треугольник
                    if part_id <= quantity:
                        verts_r = params['reflected']
                        geom2 = ShapelyPolygon([(x + v[0], y + v[1]) for v in verts_r])
                        
                        if self._can_place_on_sheet(current_sheet, geom2):
                            current_sheet.parts.append(PlacedPart(
                                part_id=part_id,
                                part_name=f"Деталь #{part_id}",
                                x=x, y=y,
                                rotation=base_angle + 180,
                                geometry=geom2,
                                bounding_box=geom2.bounds
                            ))
                            current_sheet.used_area += part_area
                            parts_placed += 1
                            part_id += 1
        
        for sheet in sheets:
            if sheet.total_area > 0:
                sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
        
        total_material = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        avg_eff = sum(s.efficiency for s in sheets) / len(sheets) if sheets else 0.0
        
        return NestingResult(
            sheets=sheets,
            total_parts=quantity,
            parts_placed=parts_placed,
            parts_not_placed=quantity - parts_placed,
            total_material_used=total_material,
            total_waste=total_waste,
            average_efficiency=avg_eff,
            algorithm_used=f"Triangle Tessellation"
        )
    
    def _optimize_general(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Общий алгоритм для произвольных фигур."""
        sheets: List[Sheet] = []
        parts_placed = 0
        
        for part_num in range(1, quantity + 1):
            placed = False
            
            for sheet in sheets:
                if self._try_place_general(sheet, part_num, part_geometry):
                    placed = True
                    parts_placed += 1
                    break
            
            if not placed:
                new_sheet = Sheet(
                    sheet_number=len(sheets) + 1,
                    width=self.sheet_width,
                    height=self.sheet_height
                )
                if self._try_place_general(new_sheet, part_num, part_geometry):
                    sheets.append(new_sheet)
                    parts_placed += 1
                else:
                    break
        
        for sheet in sheets:
            if sheet.total_area > 0:
                sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
        
        total_material = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        avg_eff = sum(s.efficiency for s in sheets) / len(sheets) if sheets else 0.0
        
        return NestingResult(
            sheets=sheets,
            total_parts=quantity,
            parts_placed=parts_placed,
            parts_not_placed=quantity - parts_placed,
            total_material_used=total_material,
            total_waste=total_waste,
            average_efficiency=avg_eff,
            algorithm_used="Bottom-Left Packing"
        )
    
    def _try_place_general(self, sheet: Sheet, part_id: int, geometry: ShapelyPolygon) -> bool:
        """Пытается разместить деталь на листе."""
        best = None
        best_score = float("inf")
        
        angles = [0, 45, 90, 135, 180, 225, 270, 315]
        
        for angle in angles:
            rotated = rotate(geometry, angle, origin="centroid")
            
            for x, y in self._get_bottom_left_positions(sheet, rotated):
                test_geom = translate(rotated, xoff=x, yoff=y)
                
                if self._can_place_on_sheet(sheet, test_geom):
                    score = self._evaluate_placement(sheet, test_geom)
                    
                    if score < best_score:
                        best_score = score
                        best = (x, y, angle, rotated)
                    
                    if not sheet.parts:
                        break
        
        if best is None:
            return False
        
        x, y, angle, final_geom = best
        placed_geom = translate(final_geom, xoff=x, yoff=y)
        
        sheet.parts.append(PlacedPart(
            part_id=part_id,
            part_name=f"Деталь #{part_id}",
            x=x, y=y,
            rotation=angle,
            geometry=placed_geom,
            bounding_box=placed_geom.bounds
        ))
        sheet.used_area += geometry.area
        
        return True
    
    def _get_bottom_left_positions(self, sheet: Sheet, geometry: ShapelyPolygon) -> List[Tuple[float, float]]:
        """Генерирует позиции для Bottom-Left алгоритма."""
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]
        
        positions = []
        
        if not sheet.parts:
            positions.append((self.spacing - bounds[0], self.spacing - bounds[1]))
            return positions
        
        step = max(5, int(min(part_width, part_height) / 10))
        
        # Вдоль нижней границы
        for x in range(int(self.spacing), int(self.sheet_width - part_width - self.spacing + 1), step):
            positions.append((x - bounds[0], self.spacing - bounds[1]))
        
        # Вдоль левой границы
        for y in range(int(self.spacing), int(self.sheet_height - part_height - self.spacing + 1), step):
            positions.append((self.spacing - bounds[0], y - bounds[1]))
        
        # Около существующих деталей
        for part in sheet.parts:
            pb = part.bounding_box
            
            # Справа
            x_right = pb[2] + self.spacing
            if x_right + part_width <= self.sheet_width - self.spacing:
                positions.append((x_right - bounds[0], pb[1] - bounds[1]))
                positions.append((x_right - bounds[0], pb[3] - part_height - bounds[1]))
            
            # Сверху
            y_top = pb[3] + self.spacing
            if y_top + part_height <= self.sheet_height - self.spacing:
                positions.append((pb[0] - bounds[0], y_top - bounds[1]))
                positions.append((pb[2] - part_width - bounds[0], y_top - bounds[1]))
        
        # Удаляем дубликаты
        positions = list(dict.fromkeys(positions))
        positions.sort(key=lambda p: (p[1], p[0]))
        
        return positions[:200]
    
    def _evaluate_placement(self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        """Оценивает качество размещения."""
        bounds = geometry.bounds
        return bounds[1] * 1000 + bounds[0]
    
    def _can_place_on_sheet(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        """Проверяет возможность размещения."""
        bounds = geometry.bounds
        
        # Проверка границ
        if (bounds[0] < self.spacing or bounds[1] < self.spacing or 
            bounds[2] > self.sheet_width - self.spacing or 
            bounds[3] > self.sheet_height - self.spacing):
            return False
        
        # Проверка пересечений
        for part in sheet.parts:
            if geometry.distance(part.geometry) < self.spacing:
                return False
        
        return True


# ---------------------------------------------------------------------------
# Streamlit интерфейс
# ---------------------------------------------------------------------------

def render_nesting_optimizer_tab(objects_data: List[Any] = None):
    """Отрисовывает вкладку оптимизации раскроя."""
    try:
        import streamlit as st
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon
        import numpy as np
        import pandas as pd
    except ImportError as e:
        print(f"Import error: {e}")
        return
    
    st.markdown("## 🔲 Продвинутая оптимизация раскроя")
    st.markdown("**Плотная упаковка деталей с учетом реальной формы и поворотов.**")
    
    if not SHAPELY_AVAILABLE:
        st.error("❌ Библиотека **shapely** не установлена.\n\nВыполните: `pip install shapely`")
        return
    
    if not objects_data:
        st.warning("⚠️ Нет данных для оптимизации. Загрузите и обработайте DXF файл.")
        return
    
    st.success(f"✅ Загружено объектов: {len(objects_data)}")
    
    # Извлекаем все геометрии
    with st.spinner('🔍 Анализ геометрии чертежа...'):
        geometries = extract_all_geometries(objects_data)
    
    if not geometries:
        st.error("❌ Не удалось определить геометрию ни одного объекта.")
        
        # Показываем отладочную информацию
        with st.expander("🔧 Отладочная информация"):
            st.write("Типы объектов в данных:")
            for i, obj in enumerate(objects_data[:5]):  # Показываем первые 5
                obj_type = type(obj).__name__
                st.write(f"  Объект {i}: {obj_type}")
                if hasattr(obj, 'entity'):
                    if hasattr(obj.entity, 'dxftype'):
                        st.write(f"    Тип DXF: {obj.entity.dxftype()}")
        return
    
    # Создаем DataFrame с информацией
    info_data = []
    for idx, geom, info in geometries:
        info_data.append({
            '№': idx + 1,
            'Тип': info['type'],
            'Вершин': info['vertices'],
            'Ширина (мм)': f"{info['width']:.1f}",
            'Высота (мм)': f"{info['height']:.1f}",
            'Площадь (мм²)': f"{info['area']:.0f}"
        })
    
    st.markdown("### 📐 Доступные объекты")
    st.dataframe(pd.DataFrame(info_data), use_container_width=True, hide_index=True)
    
    # Выбор детали
    st.markdown("### 🎯 Выбор детали")
    
    selected_idx = st.selectbox(
        "Выберите объект для раскроя:",
        options=range(len(geometries)),
        format_func=lambda i: f"Объект #{geometries[i][0] + 1} — {geometries[i][2]['type']} ({geometries[i][2]['width']:.1f}×{geometries[i][2]['height']:.1f} мм)"
    )
    
    selected_geom = geometries[selected_idx][1]
    selected_info = geometries[selected_idx][2]
    
    # Информация о выбранной детали
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Тип", selected_info['type'])
    with col2:
        st.metric("Ширина", f"{selected_info['width']:.2f} мм")
    with col3:
        st.metric("Высота", f"{selected_info['height']:.2f} мм")
    with col4:
        st.metric("Площадь", f"{selected_info['area']/1e6:.4f} м²")
    
    # Предпросмотр
    with st.expander("🔍 Предпросмотр геометрии", expanded=False):
        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor('#FFFFFF')
        ax.set_facecolor('#F8F8F8')
        
        bounds = selected_geom.bounds
        coords = list(selected_geom.exterior.coords)
        
        if len(coords) > 2:
            polygon = MplPolygon(
                coords,
                linewidth=2, edgecolor='#0000FF', facecolor='#ADD8E6', alpha=0.7
            )
            ax.add_patch(polygon)
        
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)
        ax.set_title("Геометрия детали", fontsize=14, fontweight='bold')
        ax.set_xlabel('X (мм)')
        ax.set_ylabel('Y (мм)')
        
        margin = max(selected_info['width'], selected_info['height']) * 0.1
        ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
        ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
        
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)
    
    st.markdown("---")
    
    # Параметры раскроя
    st.markdown("### ⚙️ Параметры раскроя")
    
    col1, col2 = st.columns(2)
    
    with col1:
        sheet_width = st.number_input("Ширина листа (мм)", value=3000.0, step=100.0, min_value=100.0)
        sheet_height = st.number_input("Высота листа (мм)", value=1500.0, step=100.0, min_value=100.0)
    
    with col2:
        quantity = st.number_input("Количество деталей", value=20, min_value=1, max_value=500, step=1)
        spacing = st.number_input("Отступ между деталями (мм)", value=5.0, min_value=0.0, max_value=50.0, step=1.0)
    
    st.markdown("---")
    
    # Запуск оптимизации
    if st.button("🚀 Запустить оптимизацию", type="primary", use_container_width=True):
        with st.spinner(f'⏳ Оптимизация размещения {quantity} деталей...'):
            try:
                optimizer = AdvancedNestingOptimizer(
                    sheet_width, sheet_height, spacing
                )
                
                result = optimizer.optimize(selected_geom, quantity)
                
                st.session_state['nesting_result'] = result
                
                st.success("✅ Оптимизация завершена!")
                st.balloons()
                
            except Exception as e:
                st.error(f"❌ Ошибка при оптимизации: {e}")
                import traceback
                st.code(traceback.format_exc())
                return
    
    # Отображение результатов
    if 'nesting_result' in st.session_state:
        result = st.session_state['nesting_result']
        
        st.markdown("---")
        st.markdown("### 📊 Результаты оптимизации")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📄 Листов", len(result.sheets))
        with col2:
            st.metric("✅ Размещено", f"{result.parts_placed}/{result.total_parts}")
        with col3:
            st.metric("❌ Не поместилось", result.parts_not_placed)
        with col4:
            st.metric("📈 Эффективность", f"{result.average_efficiency:.1f}%")
        with col5:
            st.metric("♻️ Отходы", f"{result.total_waste/1e6:.2f} м²")
        
        st.info(f"**Алгоритм:** {result.algorithm_used}")
        
        if result.parts_not_placed > 0:
            st.warning(f"⚠️ **{result.parts_not_placed}** деталей не поместились!")
        
        # Визуализация листов
        if result.sheets:
            st.markdown("### 🎨 Визуализация раскроя")
            
            for sheet in result.sheets[:3]:  # Показываем первые 3 листа
                fig, ax = plt.subplots(figsize=(12, 8))
                fig.patch.set_facecolor('#FFFFFF')
                ax.set_facecolor('#F8F8F8')
                
                # Границы
                ax.add_patch(MplPolygon(
                    [(0, 0), (sheet.width, 0), (sheet.width, sheet.height), (0, sheet.height)],
                    fill=False, edgecolor='red', linewidth=2, linestyle='--'
                ))
                
                # Детали
                colors = plt.cm.tab20(np.linspace(0, 1, len(sheet.parts)))
                for i, part in enumerate(sheet.parts):
                    coords = list(part.geometry.exterior.coords)
                    if len(coords) > 2:
                        ax.add_patch(MplPolygon(
                            coords, facecolor=colors[i], edgecolor='darkblue', alpha=0.7, linewidth=1
                        ))
                        centroid = part.geometry.centroid
                        ax.text(centroid.x, centroid.y, str(part.part_id),
                               ha='center', va='center', fontsize=8, fontweight='bold')
                
                ax.set_xlim(-50, sheet.width + 50)
                ax.set_ylim(-50, sheet.height + 50)
                ax.set_aspect('equal')
                ax.grid(True, alpha=0.3)
                ax.set_title(f"Лист #{sheet.sheet_number} — {len(sheet.parts)} деталей — Эффективность: {sheet.efficiency:.1f}%",
                           fontsize=12, fontweight='bold')
                ax.set_xlabel("X (мм)")
                ax.set_ylabel("Y (мм)")
                
                st.pyplot(fig, use_container_width=True)
                plt.close(fig)
            
            if len(result.sheets) > 3:
                st.info(f"... и еще {len(result.sheets) - 3} листов")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Модуль оптимизации раскроя загружен успешно")
    print(f"Shapely доступен: {SHAPELY_AVAILABLE}")
