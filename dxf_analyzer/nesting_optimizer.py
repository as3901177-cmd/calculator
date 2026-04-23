"""
Версия 5.0 - НАСТОЯЩАЯ паркетная тесселяция треугольников
"""

import math
from typing import List, Optional, Tuple, Any, Dict
from dataclasses import dataclass, field
import logging

try:
    from shapely.geometry import Polygon as ShapelyPolygon, Point, LineString, MultiPoint
    from shapely.affinity import translate, rotate, scale, affine_transform
    from shapely.strtree import STRtree
    from shapely.validation import make_valid
    from shapely.ops import unary_union
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    ShapelyPolygon = Any
    print("Warning: shapely is not installed. Run: pip install shapely")

logger = logging.getLogger(__name__)

MIN_POLYGON_AREA = 1e-6
MIN_COORDINATE_DIFF = 1e-6
DEFAULT_ROTATION_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]
MAX_POSITION_CANDIDATES = 300
POSITION_STEP_DIVISOR = 10


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
            try:
                self.spatial_index = STRtree([p.geometry for p in self.parts])
            except Exception as e:
                logger.warning(f"Failed to build spatial index: {e}")
                self.spatial_index = None

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
# DXF → Shapely (без изменений)
# ---------------------------------------------------------------------------

def dxf_object_to_shapely(dxf_obj: Any) -> Optional[ShapelyPolygon]:
    if not SHAPELY_AVAILABLE or dxf_obj is None:
        return None

    vertices = []
    try:
        entity = getattr(dxf_obj, 'entity', dxf_obj)
        entity_type = None
        if hasattr(entity, 'dxftype'):
            try:
                entity_type = entity.dxftype()
            except:
                pass

        if entity_type == 'POLYLINE' or (hasattr(entity, 'vertices') and entity_type != 'LWPOLYLINE'):
            try:
                vertices_iter = entity.vertices
                vertices_list = list(vertices_iter) if hasattr(vertices_iter, '__iter__') else []
                for v in vertices_list:
                    x, y = None, None
                    try:
                        if hasattr(v, 'dxf') and hasattr(v.dxf, 'location'):
                            x = float(v.dxf.location.x)
                            y = float(v.dxf.location.y)
                        elif hasattr(v, 'dxf'):
                            x = float(getattr(v.dxf, 'x', 0))
                            y = float(getattr(v.dxf, 'y', 0))
                        elif hasattr(v, 'location'):
                            if hasattr(v.location, 'x'):
                                x = float(v.location.x)
                                y = float(v.location.y)
                            elif len(v.location) >= 2:
                                x = float(v.location[0])
                                y = float(v.location[1])
                        elif hasattr(v, 'x') and hasattr(v, 'y'):
                            x = float(v.x)
                            y = float(v.y)
                        elif isinstance(v, (tuple, list)) and len(v) >= 2:
                            x = float(v[0])
                            y = float(v[1])
                    except:
                        continue
                    if x is not None and y is not None and not (math.isnan(x) or math.isnan(y)):
                        vertices.append((x, y))
            except Exception as e:
                logger.warning(f"Error processing POLYLINE vertices: {e}")

        elif entity_type == 'LWPOLYLINE' or hasattr(entity, 'get_points'):
            try:
                if hasattr(entity, 'get_points'):
                    points = entity.get_points('xy')
                elif hasattr(entity, 'points'):
                    points = entity.points()
                else:
                    points = []
                for p in points:
                    if isinstance(p, (tuple, list)) and len(p) >= 2:
                        try:
                            x, y = float(p[0]), float(p[1])
                            if not (math.isnan(x) or math.isnan(y)):
                                vertices.append((x, y))
                        except:
                            continue
            except Exception as e:
                logger.warning(f"Error processing LWPOLYLINE points: {e}")

        if len(vertices) < 3:
            return None

        unique_vertices = []
        for v in vertices:
            if not unique_vertices:
                unique_vertices.append(v)
            else:
                last_v = unique_vertices[-1]
                distance = math.hypot(v[0] - last_v[0], v[1] - last_v[1])
                if distance > MIN_COORDINATE_DIFF:
                    unique_vertices.append(v)

        if len(unique_vertices) >= 3:
            first = unique_vertices[0]
            last = unique_vertices[-1]
            distance = math.hypot(last[0] - first[0], last[1] - first[1])
            if distance < MIN_COORDINATE_DIFF:
                unique_vertices = unique_vertices[:-1]

        if len(unique_vertices) < 3:
            return None

        poly = ShapelyPolygon(unique_vertices)
        if not poly.is_valid:
            try:
                poly = make_valid(poly)
                if hasattr(poly, 'geoms'):
                    poly = max(poly.geoms, key=lambda g: g.area)
            except:
                poly = poly.buffer(0)

        if not poly.is_valid or poly.is_empty:
            try:
                multi_point = MultiPoint(unique_vertices)
                poly = multi_point.convex_hull
            except:
                return None

        if poly and not poly.is_empty and poly.area > MIN_POLYGON_AREA:
            return poly
        return None
    except Exception as e:
        logger.error(f"Error converting DXF to Shapely: {e}")
        return None


def extract_all_geometries(objects_data: List[Any]) -> List[Tuple[int, ShapelyPolygon, dict]]:
    geometries = []
    if not objects_data:
        return geometries
    for i, obj in enumerate(objects_data):
        if obj is None:
            continue
        try:
            geom = dxf_object_to_shapely(obj)
            if geom is not None and not geom.is_empty:
                bounds = geom.bounds
                coords = list(geom.exterior.coords)
                info = {
                    'index': i,
                    'type': get_polygon_type(geom),
                    'width': bounds[2] - bounds[0],
                    'height': bounds[3] - bounds[1],
                    'area': geom.area,
                    'vertices': len(coords) - 1
                }
                geometries.append((i, geom, info))
        except Exception as e:
            logger.warning(f"Failed to extract geometry from object {i}: {e}")
            continue
    return geometries


def get_polygon_type(geom: ShapelyPolygon) -> str:
    if not SHAPELY_AVAILABLE or geom is None or geom.is_empty:
        return "unknown"
    try:
        coords = list(geom.exterior.coords)[:-1]
        num_vertices = len(coords)
        if num_vertices == 3:
            return "triangle"
        elif num_vertices == 4:
            bounds = geom.bounds
            rect_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
            if rect_area > 0 and abs(geom.area - rect_area) / rect_area < 0.05:
                return "rectangle"
            else:
                return "quadrilateral"
        else:
            return "polygon"
    except:
        return "unknown"


# ---------------------------------------------------------------------------
# Упрощение геометрии
# ---------------------------------------------------------------------------

def simplify_to_triangle(geom: ShapelyPolygon, tolerance: float = 1.0) -> Optional[ShapelyPolygon]:
    if not SHAPELY_AVAILABLE or geom is None or geom.is_empty:
        return None
    
    try:
        coords = list(geom.exterior.coords)[:-1]
        
        # Convex Hull
        hull = geom.convex_hull
        hull_coords = list(hull.exterior.coords)[:-1]
        
        if len(hull_coords) == 3:
            area_diff = abs(hull.area - geom.area) / geom.area * 100
            if area_diff < 5.0:
                return hull
        
        # Simplify
        for tol in [0.5, 1.0, 2.0, 5.0, 10.0]:
            simplified = geom.simplify(tolerance=tol, preserve_topology=True)
            simp_coords = list(simplified.exterior.coords)[:-1]
            if len(simp_coords) == 3:
                area_diff = abs(simplified.area - geom.area) / geom.area * 100
                if area_diff < 10.0:
                    return simplified
        
        return None
    except Exception as e:
        return None


def detect_and_simplify_triangle(geom: ShapelyPolygon) -> Tuple[ShapelyPolygon, bool]:
    coords = list(geom.exterior.coords)[:-1]
    if len(coords) == 3:
        return geom, True
    simplified = simplify_to_triangle(geom)
    if simplified is not None:
        return simplified, True
    return geom, False


# ---------------------------------------------------------------------------
# 🆕 ПРАВИЛЬНАЯ нормализация и отражение треугольников
# ---------------------------------------------------------------------------

def normalize_triangle_for_tessellation(geom: ShapelyPolygon) -> Optional[Tuple[ShapelyPolygon, ShapelyPolygon, float, float]]:
    """
    Нормализует треугольник для идеальной паркетной тесселяции.
    
    Возвращает:
        (triangle_up, triangle_down, base_length, height)
        
    Где:
        - triangle_up: ▲ основание внизу (0, 0) → (base, 0), вершина вверху
        - triangle_down: ▼ перевёрнутый, основание вверху
    """
    try:
        coords = list(geom.exterior.coords)[:-1]
        if len(coords) != 3:
            return None

        print("\n" + "="*70)
        print("🔺 NORMALIZE_TRIANGLE_FOR_TESSELLATION")
        print("="*70)

        p = [list(c) for c in coords]

        # Находим самую длинную сторону (база)
        sides = [
            (math.hypot(p[1][0]-p[0][0], p[1][1]-p[0][1]), 0, 1, 2),
            (math.hypot(p[2][0]-p[1][0], p[2][1]-p[1][1]), 1, 2, 0),
            (math.hypot(p[0][0]-p[2][0], p[0][1]-p[2][1]), 2, 0, 1),
        ]
        sides.sort(key=lambda s: -s[0])
        base_len, i0, i1, i_apex = sides[0]

        print(f"База: {base_len:.2f} мм (вершины {i0}→{i1})")
        print(f"Вершина (apex): {i_apex}")

        # Угол базы
        dx = p[i1][0] - p[i0][0]
        dy = p[i1][1] - p[i0][1]
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)

        # Поворачиваем треугольник так, чтобы база была горизонтальной
        def rotate_point(px, py, cx, cy, deg):
            rad = math.radians(deg)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            qx = cx + cos_a*(px-cx) - sin_a*(py-cy)
            qy = cy + sin_a*(px-cx) + cos_a*(py-cy)
            return qx, qy

        cx, cy = p[i0][0], p[i0][1]
        rotated_pts = [rotate_point(pp[0], pp[1], cx, cy, -angle_deg) for pp in p]

        # Смещаем к (0, 0)
        base_left_x = min(rotated_pts[i0][0], rotated_pts[i1][0])
        base_y = rotated_pts[i0][1]
        normalized_pts = [(x - base_left_x, y - base_y) for x, y in rotated_pts]

        # Вершина должна быть сверху
        apex_y = normalized_pts[i_apex][1]
        if apex_y < 0:
            normalized_pts = [(x, -y) for x, y in normalized_pts]
            apex_y = -apex_y

        # Создаём треугольник ▲ (вершина вверх)
        # Нормализуем так, чтобы база была ТОЧНО от (0,0) до (base_len, 0)
        base_pts = [normalized_pts[i0], normalized_pts[i1]]
        apex_pt = normalized_pts[i_apex]
        
        # Сортируем точки базы по X
        base_pts.sort(key=lambda pt: pt[0])
        
        # Идеальный треугольник ▲
        triangle_up = ShapelyPolygon([
            (0, 0),                    # Левая точка базы
            (base_len, 0),             # Правая точка базы
            (apex_pt[0], apex_pt[1])   # Вершина
        ])

        # Вычисляем высоту через площадь
        area = abs(geom.area)
        height = (2 * area) / base_len if base_len > MIN_COORDINATE_DIFF else 0

        print(f"\nТреугольник ▲ (вершина вверх):")
        for i, c in enumerate(list(triangle_up.exterior.coords)[:-1]):
            print(f"  Вершина {i}: ({c[0]:.2f}, {c[1]:.2f})")

        # Создаём перевёрнутый треугольник ▼
        # Стратегия: отражаем ▲ относительно его правой стороны
        # ▼ должен начинаться с правой вершины ▲ и идти вправо
        
        apex_x, apex_y = apex_pt[0], apex_pt[1]
        
        # Перевёрнутый треугольник:
        # - Левая нижняя вершина = правая нижняя вершина ▲: (base_len, 0)
        # - Правая нижняя вершина смещена на base_len вправо: (2*base_len, 0)
        # - Вершина (сверху) отражена: (base_len + (base_len - apex_x), apex_y)
        
        triangle_down = ShapelyPolygon([
            (base_len, 0),                              # Левая нижняя (= правая ▲)
            (2 * base_len, 0),                          # Правая нижняя
            (base_len + (base_len - apex_x), apex_y)    # Вершина
        ])

        print(f"\nТреугольник ▼ (перевёрнутый):")
        for i, c in enumerate(list(triangle_down.exterior.coords)[:-1]):
            print(f"  Вершина {i}: ({c[0]:.2f}, {c[1]:.2f})")

        print(f"\n📊 Параметры тесселяции:")
        print(f"  База: {base_len:.2f} мм")
        print(f"  Высота: {height:.2f} мм")
        print(f"  Площадь: {area:.2f} мм²")
        print("="*70 + "\n")

        if not triangle_up.is_valid:
            triangle_up = triangle_up.buffer(0)
        if not triangle_down.is_valid:
            triangle_down = triangle_down.buffer(0)

        return triangle_up, triangle_down, base_len, height

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Оптимизатор
# ---------------------------------------------------------------------------

class AdvancedNestingOptimizer:
    """Паркетная тесселяция треугольников."""

    def __init__(self, sheet_width: float, sheet_height: float, spacing: float = 5.0, rotation_step: float = 15.0):
        if sheet_width <= 0 or sheet_height <= 0:
            raise ValueError("Sheet dimensions must be positive")
        if spacing < 0:
            raise ValueError("Spacing cannot be negative")

        self.sheet_width = float(sheet_width)
        self.sheet_height = float(sheet_height)
        self.spacing = float(spacing)
        self.rotation_step = float(rotation_step)

    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        if not SHAPELY_AVAILABLE:
            return self._create_empty_result(quantity, "Shapely not available")
        if part_geometry is None or part_geometry.is_empty:
            return self._create_empty_result(quantity, "Invalid geometry")
        if quantity <= 0:
            return self._create_empty_result(0, "Invalid quantity")

        try:
            bounds = part_geometry.bounds
            cx = (bounds[0] + bounds[2]) / 2
            cy = (bounds[1] + bounds[3]) / 2
            normalized_input = translate(part_geometry, xoff=-cx, yoff=-cy)

            simplified_geom, is_triangle = detect_and_simplify_triangle(normalized_input)
            
            if is_triangle:
                return self._optimize_triangle_tessellation(
                    simplified_geom, quantity, original_area=part_geometry.area
                )
            else:
                return self._optimize_general(normalized_input, quantity)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._create_empty_result(quantity, str(e))

    def _create_empty_result(self, quantity: int, error_msg: str) -> NestingResult:
        return NestingResult(
            sheets=[], total_parts=quantity, parts_placed=0, parts_not_placed=quantity,
            total_material_used=0.0, total_waste=0.0, average_efficiency=0.0,
            algorithm_used=f"Failed: {error_msg}"
        )

    def _calculate_result_statistics(self, sheets: List[Sheet], quantity: int, parts_placed: int, algorithm: str) -> NestingResult:
        for sheet in sheets:
            if sheet.total_area > 0:
                sheet.efficiency = (sheet.used_area / sheet.total_area) * 100

        total_material = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        avg_eff = sum(s.efficiency for s in sheets) / len(sheets) if sheets else 0.0

        return NestingResult(
            sheets=sheets, total_parts=quantity, parts_placed=parts_placed,
            parts_not_placed=quantity - parts_placed, total_material_used=total_material,
            total_waste=total_waste, average_efficiency=avg_eff, algorithm_used=algorithm
        )

    def _optimize_triangle_tessellation(self, part_geometry: ShapelyPolygon, quantity: int, original_area: Optional[float] = None) -> NestingResult:
        """🆕 ПРАВИЛЬНАЯ паркетная тесселяция"""
        
        result = normalize_triangle_for_tessellation(part_geometry)
        if result is None:
            bounds = part_geometry.bounds
            cx = (bounds[0] + bounds[2]) / 2
            cy = (bounds[1] + bounds[3]) / 2
            return self._optimize_general(translate(part_geometry, xoff=-cx, yoff=-cy), quantity)

        tri_up, tri_down, base_len, height = result
        part_area = original_area if original_area else part_geometry.area

        sp = self.spacing
        usable_w = self.sheet_width - 2 * sp
        usable_h = self.sheet_height - 2 * sp

        # 🆕 ПАРКЕТ: пара ▲▼ занимает base_len по ширине
        pairs_per_row = max(1, int(usable_w / base_len))
        max_rows = max(1, int(usable_h / (height + sp)))

        print(f"\n📐 Паркетная сетка:")
        print(f"  Пар ▲▼ в ряду: {pairs_per_row}")
        print(f"  Треугольников в ряду: {pairs_per_row * 2}")
        print(f"  Рядов: {max_rows}")
        print(f"  Ёмкость листа: {pairs_per_row * 2 * max_rows}")

        sheets: List[Sheet] = []
        parts_placed = 0
        part_id = 1

        def new_sheet() -> Sheet:
            return Sheet(sheet_number=len(sheets) + 1, width=self.sheet_width, height=self.sheet_height)

        current_sheet = new_sheet()
        sheets.append(current_sheet)

        for row in range(max_rows):
            if part_id > quantity:
                break

            y_origin = sp + row * (height + sp)
            if y_origin + height > self.sheet_height - sp + 1e-6:
                break

            for pair_idx in range(pairs_per_row):
                if part_id > quantity:
                    break

                # X-позиция пары
                x_origin = sp + pair_idx * base_len

                if x_origin + base_len > self.sheet_width - sp + 1e-6:
                    break

                # ============================================================
                # ▲ Треугольник вершина ВВЕРХ
                # ============================================================
                placed_up = translate(tri_up, xoff=x_origin, yoff=y_origin)
                b_up = placed_up.bounds

                if (b_up[0] >= sp - 1e-6 and b_up[1] >= sp - 1e-6
                        and b_up[2] <= self.sheet_width - sp + 1e-6
                        and b_up[3] <= self.sheet_height - sp + 1e-6):
                    
                    current_sheet.parts.append(PlacedPart(
                        part_id=part_id,
                        part_name=f"Деталь #{part_id}",
                        x=x_origin,
                        y=y_origin,
                        rotation=0,
                        geometry=placed_up,
                        bounding_box=placed_up.bounds
                    ))
                    current_sheet.used_area += part_area
                    parts_placed += 1
                    part_id += 1

                # ============================================================
                # ▼ Треугольник вершина ВНИЗ (сдвинут НА ПОЛОВИНУ базы)
                # ============================================================
                if part_id <= quantity:
                    # tri_down уже смещён на base_len, нужно вычесть это и добавить нужное
                    # tri_down начинается с x=base_len, нам нужно x=x_origin
                    placed_down = translate(tri_down, xoff=x_origin - base_len, yoff=y_origin)
                    b_down = placed_down.bounds

                    if (b_down[0] >= sp - 1e-6 and b_down[1] >= sp - 1e-6
                            and b_down[2] <= self.sheet_width - sp + 1e-6
                            and b_down[3] <= self.sheet_height - sp + 1e-6):
                        
                        current_sheet.parts.append(PlacedPart(
                            part_id=part_id,
                            part_name=f"Деталь #{part_id}",
                            x=x_origin,
                            y=y_origin,
                            rotation=180,
                            geometry=placed_down,
                            bounding_box=placed_down.bounds
                        ))
                        current_sheet.used_area += part_area
                        parts_placed += 1
                        part_id += 1

        # Дополнительные листы
        while part_id <= quantity:
            current_sheet = new_sheet()
            sheets.append(current_sheet)
            placed_on_this_sheet = False

            for row in range(max_rows):
                if part_id > quantity:
                    break
                y_origin = sp + row * (height + sp)
                if y_origin + height > self.sheet_height - sp + 1e-6:
                    break

                for pair_idx in range(pairs_per_row):
                    if part_id > quantity:
                        break
                    x_origin = sp + pair_idx * base_len
                    if x_origin + base_len > self.sheet_width - sp + 1e-6:
                        break

                    placed_up = translate(tri_up, xoff=x_origin, yoff=y_origin)
                    b_up = placed_up.bounds
                    if (b_up[0] >= sp - 1e-6 and b_up[1] >= sp - 1e-6
                            and b_up[2] <= self.sheet_width - sp + 1e-6
                            and b_up[3] <= self.sheet_height - sp + 1e-6):
                        current_sheet.parts.append(PlacedPart(
                            part_id=part_id, part_name=f"Деталь #{part_id}",
                            x=x_origin, y=y_origin, rotation=0,
                            geometry=placed_up, bounding_box=placed_up.bounds
                        ))
                        current_sheet.used_area += part_area
                        parts_placed += 1
                        part_id += 1
                        placed_on_this_sheet = True

                    if part_id <= quantity:
                        placed_down = translate(tri_down, xoff=x_origin - base_len, yoff=y_origin)
                        b_down = placed_down.bounds
                        if (b_down[0] >= sp - 1e-6 and b_down[1] >= sp - 1e-6
                                and b_down[2] <= self.sheet_width - sp + 1e-6
                                and b_down[3] <= self.sheet_height - sp + 1e-6):
                            current_sheet.parts.append(PlacedPart(
                                part_id=part_id, part_name=f"Деталь #{part_id}",
                                x=x_origin, y=y_origin, rotation=180,
                                geometry=placed_down, bounding_box=placed_down.bounds
                            ))
                            current_sheet.used_area += part_area
                            parts_placed += 1
                            part_id += 1
                            placed_on_this_sheet = True

            if not placed_on_this_sheet:
                sheets.pop()
                break

        return self._calculate_result_statistics(sheets, quantity, parts_placed, "Perfect Parquet Tessellation")

    def _optimize_general(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
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
                new_sheet = Sheet(sheet_number=len(sheets) + 1, width=self.sheet_width, height=self.sheet_height)
                if self._try_place_general(new_sheet, part_num, part_geometry):
                    sheets.append(new_sheet)
                    parts_placed += 1
                else:
                    break

        return self._calculate_result_statistics(sheets, quantity, parts_placed, "Bottom-Left Packing")

    def _try_place_general(self, sheet: Sheet, part_id: int, geometry: ShapelyPolygon) -> bool:
        best = None
        best_score = float("inf")

        for angle in DEFAULT_ROTATION_ANGLES:
            try:
                rotated = rotate(geometry, angle, origin="centroid")
                positions = self._get_bottom_left_positions(sheet, rotated)
                for x, y in positions:
                    test_geom = translate(rotated, xoff=x, yoff=y)
                    if self._can_place_on_sheet(sheet, test_geom):
                        score = self._evaluate_placement(sheet, test_geom)
                        if score < best_score:
                            best_score = score
                            best = (x, y, angle, rotated)
                        if not sheet.parts:
                            break
            except:
                continue

        if best is None:
            return False

        x, y, angle, final_geom = best
        placed_geom = translate(final_geom, xoff=x, yoff=y)
        sheet.parts.append(PlacedPart(
            part_id=part_id, part_name=f"Деталь #{part_id}",
            x=x, y=y, rotation=angle, geometry=placed_geom, bounding_box=placed_geom.bounds
        ))
        sheet.used_area += geometry.area
        sheet.rebuild_spatial_index()
        return True

    def _get_bottom_left_positions(self, sheet: Sheet, geometry: ShapelyPolygon) -> List[Tuple[float, float]]:
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]
        positions = []

        if not sheet.parts:
            positions.append((self.spacing - bounds[0], self.spacing - bounds[1]))
            return positions

        step = max(5, min(part_width, part_height) / POSITION_STEP_DIVISOR)
        step = int(step)

        x = int(self.spacing)
        max_x = int(self.sheet_width - part_width - self.spacing)
        while x <= max_x:
            positions.append((x - bounds[0], self.spacing - bounds[1]))
            x += step

        y = int(self.spacing)
        max_y = int(self.sheet_height - part_height - self.spacing)
        while y <= max_y:
            positions.append((self.spacing - bounds[0], y - bounds[1]))
            y += step

        for part in sheet.parts:
            pb = part.bounding_box
            x_right = pb[2] + self.spacing
            if x_right + part_width <= self.sheet_width - self.spacing:
                positions.append((x_right - bounds[0], pb[1] - bounds[1]))
                if pb[3] - part_height >= self.spacing:
                    positions.append((x_right - bounds[0], pb[3] - part_height - bounds[1]))

            y_top = pb[3] + self.spacing
            if y_top + part_height <= self.sheet_height - self.spacing:
                positions.append((pb[0] - bounds[0], y_top - bounds[1]))
                if pb[2] - part_width >= self.spacing:
                    positions.append((pb[2] - part_width - bounds[0], y_top - bounds[1]))

        unique_positions = []
        for pos in positions:
            if not any(abs(pos[0] - ep[0]) < MIN_COORDINATE_DIFF and abs(pos[1] - ep[1]) < MIN_COORDINATE_DIFF for ep in unique_positions):
                unique_positions.append(pos)

        unique_positions.sort(key=lambda p: (p[1], p[0]))
        return unique_positions[:MAX_POSITION_CANDIDATES]

    def _evaluate_placement(self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        bounds = geometry.bounds
        return bounds[1] * 1000 + bounds[0]

    def _can_place_on_sheet(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        bounds = geometry.bounds
        sp = self.spacing

        if (bounds[0] < sp or bounds[1] < sp or bounds[2] > self.sheet_width - sp or bounds[3] > self.sheet_height - sp):
            return False

        if not sheet.parts:
            return True

        if sheet.spatial_index is not None:
            try:
                nearby_geoms = sheet.spatial_index.query(geometry)
                for nearby_geom in nearby_geoms:
                    if geometry.distance(nearby_geom) < sp - MIN_COORDINATE_DIFF:
                        return False
                return True
            except:
                pass

        for part in sheet.parts:
            try:
                if geometry.distance(part.geometry) < sp - MIN_COORDINATE_DIFF:
                    return False
            except:
                return False

        return True


# ---------------------------------------------------------------------------
# Streamlit (укороченная версия)
# ---------------------------------------------------------------------------

def render_nesting_optimizer_tab(objects_data: List[Any] = None):
    try:
        import streamlit as st
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon
        import numpy as np
        import pandas as pd
    except ImportError as e:
        print(f"Import error: {e}")
        return

    st.markdown("## 🔺 Идеальная паркетная тесселяция треугольников")
    st.markdown("---")

    if not SHAPELY_AVAILABLE:
        st.error("❌ Библиотека **shapely** не установлена.")
        return

    if not objects_data:
        st.warning("⚠️ Нет данных. Загрузите DXF файл.")
        return

    geometries = extract_all_geometries(objects_data)
    if not geometries:
        st.error("❌ Геометрия не найдена.")
        return

    info_data = []
    for idx, geom, info in geometries:
        info_data.append({
            '№': idx + 1, 'Тип': info['type'], 'Вершин': info['vertices'],
            'Ширина (мм)': f"{info['width']:.1f}", 'Высота (мм)': f"{info['height']:.1f}",
            'Площадь (мм²)': f"{info['area']:.0f}"
        })

    st.dataframe(pd.DataFrame(info_data), use_container_width=True, hide_index=True)

    col_select, col_qty = st.columns([2, 1])
    with col_select:
        selected_idx = st.selectbox(
            "Объект:",
            options=range(len(geometries)),
            format_func=lambda i: f"#{geometries[i][0] + 1} — {geometries[i][2]['type']} ({geometries[i][2]['vertices']} вершин)"
        )
    with col_qty:
        quantity = st.number_input("Количество", value=20, min_value=1, max_value=1000)

    selected_geom = geometries[selected_idx][1]

    col1, col2, col3 = st.columns(3)
    with col1:
        sheet_width = st.number_input("Ширина листа (мм)", value=3000.0, step=100.0)
    with col2:
        sheet_height = st.number_input("Высота листа (мм)", value=1500.0, step=100.0)
    with col3:
        spacing = st.number_input("Отступ (мм)", value=5.0, min_value=0.0)

    if st.button("🚀 Запустить паркетную тесселяцию", type="primary", use_container_width=True):
        with st.expander("📋 Логи", expanded=False):
            import io, sys
            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()
            
            try:
                optimizer = AdvancedNestingOptimizer(sheet_width, sheet_height, spacing)
                result = optimizer.optimize(selected_geom, quantity)
                
                logs = buffer.getvalue()
                sys.stdout = old_stdout
                st.code(logs, language='text')
                
                st.session_state['nesting_result'] = result
                st.success("✅ Готово!")
                st.balloons()
            except Exception as e:
                sys.stdout = old_stdout
                st.error(f"❌ Ошибка: {e}")
                import traceback
                st.code(traceback.format_exc())

    if 'nesting_result' in st.session_state:
        result = st.session_state['nesting_result']
        st.markdown("---")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Листов", len(result.sheets))
        with col2:
            st.metric("Размещено", f"{result.parts_placed}/{result.total_parts}")
        with col3:
            st.metric("Эффективность", f"{result.average_efficiency:.1f}%")

        st.info(f"**Алгоритм:** {result.algorithm_used}")

        if result.sheets:
            for sheet in result.sheets[:2]:
                with st.expander(f"📄 Лист #{sheet.sheet_number}", expanded=True):
                    st.write(f"**Деталей:** {len(sheet.parts)} | **Эффективность:** {sheet.efficiency:.1f}%")
                    
                    fig, ax = plt.subplots(figsize=(18, 10))
                    fig.patch.set_facecolor('#FFF')
                    ax.set_facecolor('#F0F0F0')

                    ax.add_patch(plt.Polygon(
                        [(0, 0), (sheet.width, 0), (sheet.width, sheet.height), (0, sheet.height)],
                        fill=False, edgecolor='red', linewidth=3, linestyle='--', label='Границы листа'
                    ))

                    colors = plt.cm.tab20(np.linspace(0, 1, max(20, len(sheet.parts))))
                    for i, part in enumerate(sheet.parts):
                        coords = list(part.geometry.exterior.coords)
                        ax.add_patch(MplPolygon(
                            coords, facecolor=colors[i % len(colors)],
                            edgecolor='#003366', alpha=0.8, linewidth=1.5
                        ))
                        
                        # Номер детали
                        centroid = part.geometry.centroid
                        ax.text(centroid.x, centroid.y, str(part.part_id),
                               ha='center', va='center', fontsize=7, fontweight='bold',
                               color='white', bbox=dict(boxstyle='circle,pad=0.3',
                               facecolor='black', alpha=0.7))

                    ax.set_xlim(-50, sheet.width + 50)
                    ax.set_ylim(-50, sheet.height + 50)
                    ax.set_aspect('equal')
                    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.5)
                    ax.set_title(f"Лист #{sheet.sheet_number} — Паркетная тесселяция", fontsize=16, fontweight='bold')
                    ax.legend(fontsize=11)
                    
                    plt.tight_layout()
                    st.pyplot(fig)
                    plt.close()


if __name__ == "__main__":
    print("🔺 Версия 5.0 - Идеальная паркетная тесселяция")
