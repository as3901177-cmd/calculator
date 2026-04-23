"""
Продвинутый алгоритм раскроя с поддержкой произвольных треугольников.
Версия 2.1 - с полным Streamlit интерфейсом.
"""

import math
from typing import List, Optional, Tuple, Any
from dataclasses import dataclass, field
import logging
from enum import Enum

# Безопасный импорт Shapely
try:
    from shapely.geometry import Polygon as ShapelyPolygon, Point
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
    ACUTE = "acute"          # Остроугольный
    RIGHT = "right"          # Прямоугольный
    OBTUSE = "obtuse"        # Тупоугольный
    EQUILATERAL = "equilateral"  # Равносторонний
    ISOSCELES = "isosceles"      # Равнобедренный


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
        """Перестраивает пространственный индекс."""
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
# Геометрия тесселяции треугольников
# ---------------------------------------------------------------------------

Vec2 = Tuple[float, float]


def classify_triangle(verts: List[Vec2]) -> TriangleType:
    """Классифицирует треугольник по углам."""
    # Вычисляем квадраты длин сторон
    a2 = (verts[1][0] - verts[2][0])**2 + (verts[1][1] - verts[2][1])**2
    b2 = (verts[0][0] - verts[2][0])**2 + (verts[0][1] - verts[2][1])**2
    c2 = (verts[0][0] - verts[1][0])**2 + (verts[0][1] - verts[1][1])**2
    
    eps = 1e-6
    is_isosceles = abs(a2 - b2) < eps or abs(b2 - c2) < eps or abs(c2 - a2) < eps
    is_equilateral = abs(a2 - b2) < eps and abs(b2 - c2) < eps
    
    if is_equilateral:
        return TriangleType.EQUILATERAL
    
    sides = sorted([a2, b2, c2])
    
    if abs(sides[0] + sides[1] - sides[2]) < eps:
        return TriangleType.RIGHT
    elif sides[0] + sides[1] < sides[2]:
        return TriangleType.OBTUSE
    else:
        if is_isosceles:
            return TriangleType.ISOSCELES
        return TriangleType.ACUTE


def get_triangle_vertices(geom: ShapelyPolygon) -> List[Vec2]:
    """Извлекает вершины треугольника."""
    coords = list(geom.exterior.coords)[:-1]
    if len(coords) != 3:
        raise ValueError("Not a triangle")
    return [(float(x), float(y)) for x, y in coords]


def get_longest_edge(verts: List[Vec2]) -> Tuple[int, int, float]:
    """Находит самое длинное ребро треугольника."""
    edges = [
        (0, 1, math.hypot(verts[1][0] - verts[0][0], verts[1][1] - verts[0][1])),
        (1, 2, math.hypot(verts[2][0] - verts[1][0], verts[2][1] - verts[1][1])),
        (2, 0, math.hypot(verts[0][0] - verts[2][0], verts[0][1] - verts[2][1]))
    ]
    return max(edges, key=lambda e: e[2])


def get_triangle_height(verts: List[Vec2], base_idx1: int, base_idx2: int) -> float:
    """Вычисляет высоту треугольника к указанному основанию."""
    apex_idx = 3 - base_idx1 - base_idx2
    
    x1, y1 = verts[base_idx1]
    x2, y2 = verts[base_idx2]
    x3, y3 = verts[apex_idx]
    
    area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2
    base_length = math.hypot(x2 - x1, y2 - y1)
    
    return 2 * area / base_length if base_length > 0 else 0


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
        triangle_type = classify_triangle(verts)
        
        edge1, edge2, base_length = get_longest_edge(verts)
        
        base_verts = (verts[edge1], verts[edge2])
        apex_idx = 3 - edge1 - edge2
        apex = verts[apex_idx]
        height = get_triangle_height(verts, edge1, edge2)
        
        reflected_apex = reflect_point_over_line(apex, base_verts[0], base_verts[1])
        
        min_y = min(base_verts[0][1], base_verts[1][1])
        
        normalized_verts = [(v[0] - base_verts[0][0], v[1] - min_y) for v in verts]
        
        reflected_verts = [
            (0, 0),
            (base_length, 0),
            (reflected_apex[0] - base_verts[0][0], reflected_apex[1] - min_y)
        ]
        
        return {
            'original': normalized_verts,
            'reflected': reflected_verts,
            'base_length': base_length,
            'height': height,
            'triangle_type': triangle_type,
            'base_vector': (base_length, 0),
            'height_vector': (0, height)
        }
        
    except Exception as e:
        logger.error(f"Tessellation error: {e}")
        return None


# ---------------------------------------------------------------------------
# Конвертация DXF → Shapely
# ---------------------------------------------------------------------------

def dxf_object_to_shapely(dxf_obj: Any) -> Optional[ShapelyPolygon]:
    """Конвертирует DXF объект в Shapely Polygon."""
    if not SHAPELY_AVAILABLE or dxf_obj is None:
        return None
    
    try:
        if hasattr(dxf_obj, 'entity'):
            entity = dxf_obj.entity
            if hasattr(entity, 'vertices'):
                vertices = [(float(v.dxf.x), float(v.dxf.y)) for v in entity.vertices]
            elif hasattr(entity, 'points'):
                vertices = [(float(p[0]), float(p[1])) for p in entity.points()]
            else:
                return None
        else:
            if hasattr(dxf_obj, 'vertices'):
                vertices = [(float(v.dxf.x), float(v.dxf.y)) for v in dxf_obj.vertices]
            elif hasattr(dxf_obj, 'points'):
                vertices = [(float(p[0]), float(p[1])) for p in dxf_obj.points()]
            else:
                return None
        
        if len(vertices) < 3:
            return None
        
        poly = ShapelyPolygon(vertices)
        return poly if poly.is_valid else poly.buffer(0)
        
    except Exception as e:
        logger.error(f"Failed to convert DXF to Shapely: {e}")
        return None


def get_polygon_type(geom: ShapelyPolygon) -> str:
    """Определяет тип полигона."""
    if not SHAPELY_AVAILABLE or geom is None:
        return "unknown"
    
    try:
        coords = list(geom.exterior.coords)[:-1]
        if len(coords) == 3:
            verts = get_triangle_vertices(geom)
            triangle_type = classify_triangle(verts)
            return f"triangle ({triangle_type.value})"
        elif len(coords) == 4:
            return "quadrilateral"
        else:
            return f"polygon ({len(coords)} sides)"
    except:
        return "unknown"


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
        self.shape_type: Optional[str] = None
        self.optimal_rotations: Optional[List[float]] = None
    
    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Выполняет оптимизацию раскроя."""
        if not SHAPELY_AVAILABLE:
            return self._create_empty_result(quantity, "Shapely not available")
        
        try:
            normalized = self._normalize_geometry(part_geometry)
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
    
    def _normalize_geometry(self, geom: ShapelyPolygon) -> ShapelyPolygon:
        """Нормализует геометрию."""
        b = geom.bounds
        cx = (b[0] + b[2]) / 2
        cy = (b[1] + b[3]) / 2
        return translate(geom, xoff=-cx, yoff=-cy)
    
    def _optimize_triangle(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Оптимизирует раскрой треугольников."""
        best_result = None
        best_count = 0
        
        for base_angle in [0, 60, 90, 120, 180]:
            try:
                rotated = rotate(part_geometry, base_angle, origin="centroid")
                rotated = self._normalize_geometry(rotated)
                
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
        
        col_step = base_length + self.spacing
        row_step = height + self.spacing
        
        cols_per_row = max(1, int((self.sheet_width - self.spacing * 2) / col_step))
        rows = max(1, int((self.sheet_height - self.spacing * 2) / row_step))
        
        part_id = 1
        
        for row in range(rows):
            if part_id > quantity:
                break
            
            col_offset = 0.5 if (params['triangle_type'] == TriangleType.EQUILATERAL and row % 2 == 1) else 0
            
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
                
                x = self.spacing + col * col_step + (col_offset * col_step if col_offset else 0)
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
            sheet.efficiency = (sheet.used_area / sheet.total_area) * 100 if sheet.total_area > 0 else 0
        
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
            algorithm_used=f"Triangle Tessellation ({params['triangle_type'].value})"
        )
    
    def _optimize_general(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Общий алгоритм для произвольных фигур."""
        self.optimal_rotations = [0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180]
        
        sheets: List[Sheet] = []
        parts_placed = 0
        
        for part_num in range(1, quantity + 1):
            placed = False
            
            for sheet in sheets:
                if self._try_place_general(sheet, part_num, part_geometry):
                    placed = True
                    parts_placed += 1
                    sheet.rebuild_spatial_index()
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
            sheet.efficiency = (sheet.used_area / sheet.total_area) * 100 if sheet.total_area > 0 else 0
        
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
            algorithm_used="Bottom-Left Packing (General)"
        )
    
    def _try_place_general(self, sheet: Sheet, part_id: int, geometry: ShapelyPolygon) -> bool:
        """Пытается разместить деталь на листе."""
        best = None
        best_score = float("inf")
        
        for angle in self.optimal_rotations:
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
        
        # Вдоль границ
        for x in range(int(self.spacing), int(self.sheet_width - part_width - self.spacing + 1), step):
            positions.append((x - bounds[0], self.spacing - bounds[1]))
        
        for y in range(int(self.spacing), int(self.sheet_height - part_height - self.spacing + 1), step):
            positions.append((self.spacing - bounds[0], y - bounds[1]))
        
        # Около существующих деталей
        for part in sheet.parts:
            pb = part.bounding_box
            
            x_right = pb[2] + self.spacing
            if x_right + part_width <= self.sheet_width - self.spacing:
                positions.append((x_right - bounds[0], pb[1] - bounds[1]))
                positions.append((x_right - bounds[0], pb[3] - part_height - bounds[1]))
            
            y_top = pb[3] + self.spacing
            if y_top + part_height <= self.sheet_height - self.spacing:
                positions.append((pb[0] - bounds[0], y_top - bounds[1]))
                positions.append((pb[2] - part_width - bounds[0], y_top - bounds[1]))
            
            x_left = pb[0] - part_width - self.spacing
            if x_left >= self.spacing:
                positions.append((x_left - bounds[0], pb[1] - bounds[1]))
            
            y_bottom = pb[1] - part_height - self.spacing
            if y_bottom >= self.spacing:
                positions.append((pb[0] - bounds[0], y_bottom - bounds[1]))
        
        positions = list(dict.fromkeys(positions))
        positions.sort(key=lambda p: (p[1], p[0]))
        
        return positions[:200]
    
    def _evaluate_placement(self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        """Оценивает качество размещения."""
        bounds = geometry.bounds
        score = bounds[1] * 1000 + bounds[0]
        
        if sheet.parts:
            min_distance = min(geometry.distance(p.geometry) for p in sheet.parts)
            if min_distance < self.spacing * 1.5:
                score -= 100
        
        return score
    
    def _fits_on_sheet(self, geometry: ShapelyPolygon) -> bool:
        """Проверяет, помещается ли геометрия на лист."""
        bounds = geometry.bounds
        return (bounds[0] >= self.spacing and 
                bounds[1] >= self.spacing and 
                bounds[2] <= self.sheet_width - self.spacing and 
                bounds[3] <= self.sheet_height - self.spacing)
    
    def _can_place_on_sheet(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        """Проверяет возможность размещения."""
        if not self._fits_on_sheet(geometry):
            return False
        
        for part in sheet.parts:
            if geometry.distance(part.geometry) < self.spacing:
                return False
        
        return True


# ---------------------------------------------------------------------------
# Полный Streamlit интерфейс
# ---------------------------------------------------------------------------

def render_nesting_optimizer_tab(objects_data: List[Any] = None):
    """Отрисовывает вкладку оптимизации раскроя в Streamlit."""
    try:
        import streamlit as st
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon
        import numpy as np
        
        st.markdown("## 🔲 Продвинутая оптимизация раскроя")
        st.markdown("**Плотная упаковка деталей с учетом реальной формы и поворотов.**")
        
        if not SHAPELY_AVAILABLE:
            st.error("❌ Библиотека **shapely** не установлена.\n\nВыполните: `pip install shapely`")
            return
        
        if not objects_data:
            st.warning("⚠️ Нет данных для оптимизации. Загрузите и обработайте DXF файл.")
            return
        
        st.success(f"✅ Загружено объектов: {len(objects_data)}")
        
        # Извлекаем геометрию из DXF объектов
        with st.spinner('🔍 Анализ геометрии чертежа...'):
            shapely_geoms = []
            geometry_info = []
            
            for i, obj in enumerate(objects_data):
                geom = dxf_object_to_shapely(obj)
                if geom is not None:
                    shapely_geoms.append(geom)
                    bounds = geom.bounds
                    geometry_info.append({
                        'index': i + 1,
                        'type': get_polygon_type(geom),
                        'width': bounds[2] - bounds[0],
                        'height': bounds[3] - bounds[1],
                        'area': geom.area
                    })
        
        if not shapely_geoms:
            st.error("❌ Не удалось определить геометрию ни одного объекта.")
            return
        
        # Отображаем информацию об объектах
        st.markdown("### 📐 Доступные объекты")
        
        df_info = pd.DataFrame(geometry_info)
        df_info.columns = ['№', 'Тип', 'Ширина (мм)', 'Высота (мм)', 'Площадь (мм²)']
        st.dataframe(df_info, use_container_width=True, hide_index=True)
        
        # Выбор детали для раскроя
        st.markdown("### 🎯 Выбор детали")
        
        selected_idx = st.selectbox(
            "Выберите объект для раскроя:",
            options=range(len(shapely_geoms)),
            format_func=lambda i: f"Объект #{i+1} — {geometry_info[i]['type']} ({geometry_info[i]['width']:.1f}×{geometry_info[i]['height']:.1f} мм)"
        )
        
        selected_geom = shapely_geoms[selected_idx]
        bounds = selected_geom.bounds
        geom_width = bounds[2] - bounds[0]
        geom_height = bounds[3] - bounds[1]
        geom_area = selected_geom.area
        
        # Отображаем информацию о выбранной детали
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Тип", geometry_info[selected_idx]['type'])
        with col2:
            st.metric("Ширина", f"{geom_width:.2f} мм")
        with col3:
            st.metric("Высота", f"{geom_height:.2f} мм")
        with col4:
            st.metric("Площадь", f"{geom_area/1e6:.4f} м²")
        
        # Предпросмотр геометрии
        with st.expander("🔍 Предпросмотр геометрии", expanded=False):
            fig, ax = plt.subplots(figsize=(10, 8))
            fig.patch.set_facecolor('#FFFFFF')
            ax.set_facecolor('#F8F8F8')
            
            coords = list(selected_geom.exterior.coords)
            if len(coords) > 2:
                polygon = MplPolygon(
                    coords,
                    linewidth=2, edgecolor='#0000FF', facecolor='#ADD8E6', alpha=0.7
                )
                ax.add_patch(polygon)
            
            ax.set_aspect('equal')
            ax.grid(True, alpha=0.3)
            ax.set_title(f"Геометрия детали", fontsize=14, fontweight='bold')
            ax.set_xlabel('X (мм)')
            ax.set_ylabel('Y (мм)')
            
            margin = max(geom_width, geom_height) * 0.1
            ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
            ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
            
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        
        st.markdown("---")
        
        # Параметры раскроя
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
                min_value=1, max_value=500,
                value=20, step=1
            )
            spacing = st.number_input(
                "Минимальный отступ (мм)",
                min_value=0.0, max_value=50.0,
                value=5.0, step=1.0
            )
            rotation_step = st.slider(
                "Точность поворота (°)",
                min_value=15.0, max_value=90.0,
                value=45.0, step=15.0
            )
        
        st.markdown("---")
        
        # Кнопка запуска
        if st.button("🚀 Запустить оптимизацию", type="primary", use_container_width=True):
            with st.spinner(f'⏳ Оптимизация размещения {quantity} деталей...'):
                try:
                    optimizer = AdvancedNestingOptimizer(
                        sheet_width, sheet_height, spacing, rotation_step
                    )
                    
                    result = optimizer.optimize(selected_geom, quantity)
                    
                    st.session_state['nesting_result'] = result
                    
                    st.success("✅ Оптимизация завершена!")
                    st.balloons()
                    
                except Exception as e:
                    st.error(f"❌ Ошибка при оптимизации: {e}")
                    logger.exception("Optimization error")
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
                st.metric("✅ Размещено", f"{result.parts_placed}/{result.total_parts}")
            with col_r3:
                st.metric("❌ Не поместилось", result.parts_not_placed)
            with col_r4:
                st.metric("📈 Эффективность", f"{result.average_efficiency:.1f}%")
            with col_r5:
                total_waste_m2 = result.total_waste / 1e6
                st.metric("♻️ Отходы", f"{total_waste_m2:.2f} м²")
            
            st.info(f"**Алгоритм:** {result.algorithm_used}")
            
            if result.parts_not_placed > 0:
                st.warning(f"⚠️ **{result.parts_not_placed}** деталей не поместились! Увеличьте размер листа или уменьшите количество.")
            
            st.markdown("---")
            
            # Сводка по листам
            if result.sheets:
                st.markdown("### 📋 Сводка по листам")
                
                summary_rows = []
                for sheet in result.sheets:
                    summary_rows.append({
                        'Лист №': sheet.sheet_number,
                        'Деталей': len(sheet.parts),
                        'Использовано (м²)': round(sheet.used_area / 1e6, 4),
                        'Отходы (м²)': round(sheet.waste_area / 1e6, 4),
                        'Эффективность (%)': round(sheet.efficiency, 2)
                    })
                
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
                
                sheet = result.sheets[sheet_to_view]
                
                # Создаем визуализацию
                fig, ax = plt.subplots(figsize=(14, 10), dpi=100)
                fig.patch.set_facecolor('#FFFFFF')
                ax.set_facecolor('#F8F8F8')
                
                # Границы листа
                ax.add_patch(MplPolygon(
                    [(0, 0), (sheet.width, 0), (sheet.width, sheet.height), (0, sheet.height)],
                    fill=False, edgecolor='#FF0000', linewidth=3, linestyle='--'
                ))
                
                if not sheet.parts:
                    ax.text(sheet.width/2, sheet.height/2, 'Нет деталей', 
                           ha='center', va='center', fontsize=20, color='gray')
                else:
                    colors = plt.cm.tab20(np.linspace(0, 1, len(sheet.parts)))
                    
                    for i, part in enumerate(sheet.parts):
                        coords = list(part.geometry.exterior.coords)
                        ax.add_patch(MplPolygon(
                            coords, facecolor=colors[i], edgecolor='darkblue', 
                            alpha=0.7, linewidth=1
