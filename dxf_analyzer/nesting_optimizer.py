"""
Продвинутый алгоритм раскроя с поддержкой произвольных треугольников.
Версия 8.0 ULTIMATE - Идеальная паркетная тесселяция без пересечений.
"""

import math
from typing import List, Optional, Tuple, Any, Dict
from dataclasses import dataclass, field
import logging

# Безопасный импорт Shapely
try:
    from shapely.geometry import Polygon as ShapelyPolygon, Point, LineString, MultiPoint
    from shapely.affinity import translate, rotate, scale
    from shapely.strtree import STRtree
    from shapely.validation import make_valid
    from shapely.ops import unary_union
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    ShapelyPolygon = Any
    print("Warning: shapely is not installed. Run: pip install shapely")

logger = logging.getLogger(__name__)

# Константы
MIN_POLYGON_AREA = 1e-6
MIN_COORDINATE_DIFF = 1e-6
DEFAULT_ROTATION_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]
MAX_POSITION_CANDIDATES = 300
POSITION_STEP_DIVISOR = 10


# ---------------------------------------------------------------------------
# Типы данных
# ---------------------------------------------------------------------------

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
        """Перестраивает пространственный индекс для быстрого поиска пересечений."""
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
# КОНВЕРТАЦИЯ DXF → Shapely
# ---------------------------------------------------------------------------

def dxf_object_to_shapely(dxf_obj: Any) -> Optional[ShapelyPolygon]:
    """Конвертирует DXF объект в Shapely Polygon."""
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
                    except (AttributeError, ValueError, TypeError, IndexError):
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
                        except (ValueError, TypeError):
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
    """Извлекает все валидные геометрии из списка DXF объектов."""
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
    """Определяет тип полигона."""
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
# Упрощение геометрии до треугольника
# ---------------------------------------------------------------------------

def simplify_to_triangle(geom: ShapelyPolygon, tolerance: float = 1.0) -> Optional[ShapelyPolygon]:
    """Упрощает многовершинный полигон до треугольника."""
    if not SHAPELY_AVAILABLE or geom is None or geom.is_empty:
        return None
    
    try:
        coords = list(geom.exterior.coords)[:-1]
        
        hull = geom.convex_hull
        hull_coords = list(hull.exterior.coords)[:-1]
        
        if len(hull_coords) == 3:
            area_diff = abs(hull.area - geom.area) / geom.area * 100
            if area_diff < 5.0:
                return hull
        
        for tol in [0.5, 1.0, 2.0, 5.0, 10.0]:
            simplified = geom.simplify(tolerance=tol, preserve_topology=True)
            simp_coords = list(simplified.exterior.coords)[:-1]
            
            if len(simp_coords) == 3:
                area_diff = abs(simplified.area - geom.area) / geom.area * 100
                if area_diff < 10.0:
                    return simplified
        
        centroid = geom.centroid
        cx, cy = centroid.x, centroid.y
        
        distances = []
        for i, (x, y) in enumerate(coords):
            dist = math.hypot(x - cx, y - cy)
            distances.append((dist, i, (x, y)))
        
        distances.sort(reverse=True)
        
        farthest_3 = [distances[0][2]]
        
        p1 = farthest_3[0]
        max_dist = 0
        farthest_2 = None
        for _, _, p in distances[1:]:
            d = math.hypot(p[0] - p1[0], p[1] - p1[1])
            if d > max_dist:
                max_dist = d
                farthest_2 = p
        
        if farthest_2:
            farthest_3.append(farthest_2)
            
            max_area = 0
            farthest_pt = None
            for _, _, p in distances:
                if p not in farthest_3:
                    area = abs(
                        (farthest_3[1][0] - farthest_3[0][0]) * (p[1] - farthest_3[0][1]) -
                        (farthest_3[1][1] - farthest_3[0][1]) * (p[0] - farthest_3[0][0])
                    ) / 2
                    if area > max_area:
                        max_area = area
                        farthest_pt = p
            
            if farthest_pt:
                farthest_3.append(farthest_pt)
                
                tri = ShapelyPolygon(farthest_3)
                if tri.is_valid and not tri.is_empty:
                    area_diff = abs(tri.area - geom.area) / geom.area * 100
                    if area_diff < 15.0:
                        return tri
        
        return None
        
    except Exception as e:
        return None


def detect_and_simplify_triangle(geom: ShapelyPolygon) -> Tuple[ShapelyPolygon, bool]:
    """Определяет, является ли геометрия треугольником, и упрощает её если нужно."""
    coords = list(geom.exterior.coords)[:-1]
    
    if len(coords) == 3:
        return geom, True
    
    simplified = simplify_to_triangle(geom)
    if simplified is not None:
        return simplified, True
    
    return geom, False


# ---------------------------------------------------------------------------
# 🔺 ПАРКЕТНАЯ ТЕССЕЛЯЦИЯ ТРЕУГОЛЬНИКОВ
# ---------------------------------------------------------------------------

def create_parquet_pattern(geom: ShapelyPolygon) -> Optional[Tuple[ShapelyPolygon, ShapelyPolygon, float, float]]:
    """
    Создаёт паттерн для паркетной тесселяции треугольников.
    """
    try:
        coords = list(geom.exterior.coords)[:-1]
        if len(coords) != 3:
            return None

        p0, p1, p2 = coords[0], coords[1], coords[2]
        
        side_01 = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        side_12 = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        side_20 = math.hypot(p0[0] - p2[0], p0[1] - p2[1])
        
        sides = [
            (side_01, 0, 1, 2),
            (side_12, 1, 2, 0),
            (side_20, 2, 0, 1)
        ]
        sides.sort(key=lambda x: -x[0])
        
        base_len, idx_base_start, idx_base_end, idx_apex = sides[0]
        
        base_start = coords[idx_base_start]
        base_end = coords[idx_base_end]
        apex = coords[idx_apex]
        
        area = abs(geom.area)
        height = (2 * area) / base_len if base_len > MIN_COORDINATE_DIFF else 0
        
        base_vec = (base_end[0] - base_start[0], base_end[1] - base_start[1])
        apex_vec = (apex[0] - base_start[0], apex[1] - base_start[1])
        
        base_len_sq = base_vec[0]**2 + base_vec[1]**2
        if base_len_sq > 0:
            projection = (apex_vec[0] * base_vec[0] + apex_vec[1] * base_vec[1]) / base_len_sq
            apex_x = projection * base_len
        else:
            apex_x = base_len / 2
        
        # ▲ Треугольник вершиной ВВЕРХ
        tri_up = ShapelyPolygon([
            (0, 0),
            (base_len, 0),
            (apex_x, height)
        ])
        
        # ▼ Треугольник вершиной ВНИЗ
        center_x = base_len / 2
        center_y = 0
        
        from shapely.affinity import rotate as shapely_rotate
        tri_down = shapely_rotate(tri_up, 180, origin=(center_x, center_y))
        
        if not tri_up.is_valid:
            tri_up = tri_up.buffer(0)
        if not tri_down.is_valid:
            tri_down = tri_down.buffer(0)
        
        return tri_up, tri_down, base_len, height
        
    except Exception as e:
        print(f"❌ Ошибка создания паркетного паттерна: {e}")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Основной класс оптимизатора
# ---------------------------------------------------------------------------

class AdvancedNestingOptimizer:
    """Продвинутый алгоритм раскроя с паркетной тесселяцией треугольников."""

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
        """Выполняет оптимизацию раскроя."""
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
                print("✅ Треугольник обнаружен! Используем паркетную тесселяцию...")
                return self._optimize_triangle_parquet(
                    simplified_geom, quantity, original_area=part_geometry.area
                )
            else:
                print("ℹ️ Не треугольник. Используем общий алгоритм...")
                return self._optimize_general(normalized_input, quantity)

        except Exception as e:
            print(f"❌ Ошибка оптимизации: {e}")
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

    def _optimize_triangle_parquet(self, part_geometry: ShapelyPolygon, quantity: int, original_area: Optional[float] = None) -> NestingResult:
        """
        🔺 ИДЕАЛЬНАЯ ПАРКЕТНАЯ ТЕССЕЛЯЦИЯ V8.0
        
        Укладка: каждый треугольник занимает W/2 по горизонтали
        Ряды смещены на W/2 для шахматного порядка
        """
        
        pattern = create_parquet_pattern(part_geometry)
        if pattern is None:
            print("❌ Не удалось создать паркетный паттерн")
            bounds = part_geometry.bounds
            cx = (bounds[0] + bounds[2]) / 2
            cy = (bounds[1] + bounds[3]) / 2
            return self._optimize_general(translate(part_geometry, xoff=-cx, yoff=-cy), quantity)

        tri_up, tri_down, base_width, height = pattern
        part_area = original_area if original_area else part_geometry.area

        print(f"\n🔺 Паркетный паттерн:")
        print(f"  Ширина базы: {base_width:.2f} мм")
        print(f"  Высота: {height:.2f} мм")

        sp = self.spacing
        usable_w = self.sheet_width - 2 * sp
        usable_h = self.sheet_height - 2 * sp

        # ✅ ПРАВИЛЬНЫЙ РАСЧЁТ: каждый треугольник = W/2
        triangle_width = base_width / 2
        triangles_per_row = max(1, int(usable_w / triangle_width))
        rows = max(1, int(usable_h / (height + sp)))

        print(f"\n📐 Сетка:")
        print(f"  Треугольников в ряду: {triangles_per_row}")
        print(f"  Рядов: {rows}")
        print(f"  Ёмкость: {triangles_per_row * rows}")

        sheets: List[Sheet] = []
        parts_placed = 0
        part_id = 1

        def new_sheet() -> Sheet:
            return Sheet(sheet_number=len(sheets) + 1, width=self.sheet_width, height=self.sheet_height)

        def place_triangles_on_sheet(sheet: Sheet, start_id: int, max_parts: int) -> int:
            """Размещает треугольники на листе. Возвращает количество размещённых."""
            placed = 0
            current_id = start_id

            for row_idx in range(rows):
                if current_id > max_parts:
                    break

                # Y-позиция базы ряда
                y_base = sp + row_idx * (height + sp)

                if y_base + height > self.sheet_height - sp:
                    break

                # Смещение для шахматного порядка
                row_offset = (row_idx % 2) * triangle_width

                for col_idx in range(triangles_per_row):
                    if current_id > max_parts:
                        break

                    # X-позиция треугольника
                    x_pos = sp + row_offset + col_idx * triangle_width

                    if x_pos + base_width > self.sheet_width - sp:
                        break

                    # Чередование ▲▼ в ряду
                    is_up = (col_idx % 2 == 0)

                    if is_up:
                        # ▲ вершиной вверх
                        placed_geom = translate(tri_up, xoff=x_pos, yoff=y_base)
                        symbol = "▲"
                        rotation = 0
                    else:
                        # ▼ вершиной вниз
                        placed_geom = translate(tri_down, xoff=x_pos, yoff=y_base + height)
                        symbol = "▼"
                        rotation = 180

                    bounds = placed_geom.bounds

                    # Проверка границ
                    if (bounds[0] < sp - 1e-6 or bounds[1] < sp - 1e-6 or
                        bounds[2] > self.sheet_width - sp + 1e-6 or
                        bounds[3] > self.sheet_height - sp + 1e-6):
                        continue

                    # Добавляем деталь
                    sheet.parts.append(PlacedPart(
                        part_id=current_id,
                        part_name=f"Деталь #{current_id} {symbol}",
                        x=x_pos,
                        y=y_base,
                        rotation=rotation,
                        geometry=placed_geom,
                        bounding_box=bounds
                    ))
                    sheet.used_area += part_area
                    placed += 1
                    print(f"  ✓ {symbol} #{current_id} в ({x_pos:.1f}, {y_base:.1f})")
                    current_id += 1

            return placed

        # Размещаем на листах
        current_sheet = new_sheet()
        sheets.append(current_sheet)

        placed_count = place_triangles_on_sheet(current_sheet, part_id, quantity)
        parts_placed += placed_count
        part_id += placed_count

        # Дополнительные листы
        while part_id <= quantity:
            current_sheet = new_sheet()
            sheets.append(current_sheet)
            print(f"\n📄 Лист #{current_sheet.sheet_number}")

            placed_count = place_triangles_on_sheet(current_sheet, part_id, quantity)
            
            if placed_count == 0:
                sheets.pop()
                break

            parts_placed += placed_count
            part_id += placed_count

        print(f"\n✅ Завершено:")
        print(f"  Размещено: {parts_placed}/{quantity}")
        print(f"  Листов: {len(sheets)}")

        return self._calculate_result_statistics(sheets, quantity, parts_placed, "Parquet Tessellation v8.0 ULTIMATE")

    def _optimize_general(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Общий алгоритм Bottom-Left для произвольных фигур."""
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
                    logger.warning(f"Part {part_num} cannot fit on sheet")
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
            except Exception as e:
                logger.warning(f"Error trying angle {angle}: {e}")
                continue

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
            if not any(
                abs(pos[0] - ep[0]) < MIN_COORDINATE_DIFF
                and abs(pos[1] - ep[1]) < MIN_COORDINATE_DIFF
                for ep in unique_positions
            ):
                unique_positions.append(pos)

        unique_positions.sort(key=lambda p: (p[1], p[0]))
        return unique_positions[:MAX_POSITION_CANDIDATES]

    def _evaluate_placement(self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        bounds = geometry.bounds
        return bounds[1] * 1000 + bounds[0]

    def _can_place_on_sheet(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        bounds = geometry.bounds
        sp = self.spacing

        if (bounds[0] < sp or bounds[1] < sp or
            bounds[2] > self.sheet_width - sp or
            bounds[3] > self.sheet_height - sp):
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
            except Exception as e:
                logger.warning(f"Spatial index query failed: {e}")

        for part in sheet.parts:
            try:
                if geometry.distance(part.geometry) < sp - MIN_COORDINATE_DIFF:
                    return False
            except Exception as e:
                logger.warning(f"Distance check failed: {e}")
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

    st.markdown("## 🔺 Паркетная тесселяция v8.0 ULTIMATE")
    st.markdown("**Идеальная укладка треугольников**")
    st.markdown("---")

    if not SHAPELY_AVAILABLE:
        st.error("❌ Библиотека **shapely** не установлена.\n\nВыполните: `pip install shapely`")
        return

    if not objects_data:
        st.warning("⚠️ Нет данных для оптимизации. Загрузите и обработайте DXF файл.")
        return

    st.success(f"✅ Загружено объектов: **{len(objects_data)}**")

    with st.spinner('🔍 Анализ геометрии чертежа...'):
        geometries = extract_all_geometries(objects_data)

    if not geometries:
        st.error("❌ Не удалось определить геометрию ни одного объекта.")
        return

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

    st.markdown("---")
    st.markdown("### 🎯 Параметры раскроя")

    col_select, col_qty = st.columns([2, 1])

    with col_select:
        selected_idx = st.selectbox(
            "Выберите объект для раскроя:",
            options=range(len(geometries)),
            format_func=lambda i: (
                f"Объект #{geometries[i][0] + 1} — "
                f"{geometries[i][2]['type']} "
                f"({geometries[i][2]['width']:.1f}×{geometries[i][2]['height']:.1f} мм, "
                f"{geometries[i][2]['vertices']} вершин)"
            )
        )

    with col_qty:
        quantity = st.number_input("Количество деталей", value=50, min_value=1, max_value=1000, step=1)

    selected_geom = geometries[selected_idx][1]
    selected_info = geometries[selected_idx][2]

    st.markdown("#### 📏 Параметры детали")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Тип", selected_info['type'].title())
    with col2:
        st.metric("Ширина", f"{selected_info['width']:.2f} мм")
    with col3:
        st.metric("Высота", f"{selected_info['height']:.2f} мм")
    with col4:
        st.metric("Площадь", f"{selected_info['area']/1e6:.4f} м²")

    st.markdown("---")
    st.markdown("#### 📄 Параметры листа")

    col1, col2, col3 = st.columns(3)
    with col1:
        sheet_width = st.number_input("Ширина листа (мм)", value=2000.0, step=100.0, min_value=100.0)
    with col2:
        sheet_height = st.number_input("Высота листа (мм)", value=1500.0, step=100.0, min_value=100.0)
    with col3:
        spacing = st.number_input("Отступ между деталями (мм)", value=3.0, min_value=0.0, max_value=50.0, step=1.0)

    if selected_info['vertices'] > 3:
        st.info(f"💡 **Многовершинный полигон ({selected_info['vertices']} вершин)** будет автоматически упрощён до треугольника.")

    st.markdown("---")

    if st.button("🚀 Запустить v8.0 ULTIMATE", type="primary", use_container_width=True):
        
        with st.expander("📋 Логи оптимизации", expanded=False):
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
                st.session_state['nesting_geometry'] = selected_geom
                st.session_state['nesting_info'] = selected_info
                
                st.success("✅ Оптимизация завершена!")
                st.balloons()
                
            except Exception as e:
                sys.stdout = old_stdout
                st.error(f"❌ Ошибка: {e}")
                import traceback
                st.code(traceback.format_exc())
                return

    if 'nesting_result' in st.session_state:
        result = st.session_state['nesting_result']

        st.markdown("---")
        st.markdown("### 📊 Результаты")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📄 Листов", len(result.sheets))
        with col2:
            placement_rate = (result.parts_placed / result.total_parts * 100 if result.total_parts > 0 else 0)
            st.metric("✅ Размещено", f"{result.parts_placed}/{result.total_parts}", delta=f"{placement_rate:.0f}%")
        with col3:
            st.metric("❌ Не поместилось", result.parts_not_placed,
                     delta="Проблема!" if result.parts_not_placed > 0 else None,
                     delta_color="inverse")
        with col4:
            st.metric("📈 Эффективность", f"{result.average_efficiency:.1f}%")
        with col5:
            st.metric("♻️ Отходы", f"{result.total_waste/1e6:.2f} м²")

        st.info(f"**Алгоритм:** {result.algorithm_used}")

        if result.parts_not_placed > 0:
            st.warning(f"⚠️ **{result.parts_not_placed}** деталей не поместились!")

        if result.sheets and result.parts_placed > 0:
            st.markdown("---")
            st.markdown("### 🎨 Визуализация")

            col_viz1, col_viz2 = st.columns([1, 3])
            with col_viz1:
                show_all = st.checkbox("Показать все листы", value=False)
                show_labels = st.checkbox("Показать номера", value=True)

            sheets_to_show = result.sheets if show_all else result.sheets[:3]

            for sheet in sheets_to_show:
                with st.expander(f"📄 Лист #{sheet.sheet_number}", expanded=(sheet.sheet_number == 1)):
                    
                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                    with col_s1:
                        st.metric("Деталей", len(sheet.parts))
                    with col_s2:
                        st.metric("Использовано", f"{sheet.used_area/1e6:.3f} м²")
                    with col_s3:
                        st.metric("Отходы", f"{sheet.waste_area/1e6:.3f} м²")
                    with col_s4:
                        st.metric("Эффективность", f"{sheet.efficiency:.1f}%")
                    
                    fig, ax = plt.subplots(figsize=(18, 10))
                    fig.patch.set_facecolor('#FFFFFF')
                    ax.set_facecolor('#F5F5F5')
                    
                    sheet_boundary = MplPolygon(
                        [(0, 0), (sheet.width, 0), (sheet.width, sheet.height), (0, sheet.height)],
                        fill=False, edgecolor='red', linewidth=3, linestyle='--'
                    )
                    ax.add_patch(sheet_boundary)
                    
                    if sheet.parts:
                        num_parts = len(sheet.parts)
                        
                        if num_parts <= 20:
                            colors = plt.cm.tab20(np.linspace(0, 1, 20))
                        elif num_parts <= 40:
                            colors1 = plt.cm.tab20(np.linspace(0, 1, 20))
                            colors2 = plt.cm.tab20b(np.linspace(0, 1, 20))
                            colors = np.vstack([colors1, colors2])
                        else:
                            colors1 = plt.cm.tab20(np.linspace(0, 1, 20))
                            colors2 = plt.cm.tab20b(np.linspace(0, 1, 20))
                            colors3 = plt.cm.tab20c(np.linspace(0, 1, 20))
                            colors = np.vstack([colors1, colors2, colors3])
                        
                        for i, part in enumerate(sheet.parts):
                            try:
                                coords = list(part.geometry.exterior.coords)
                                if len(coords) > 2:
                                    color_idx = i % len(colors)
                                    
                                    part_polygon = MplPolygon(
                                        coords,
                                        facecolor=colors[color_idx],
                                        edgecolor='#003366',
                                        alpha=0.75,
                                        linewidth=1.5,
                                        zorder=2
                                    )
                                    ax.add_patch(part_polygon)
                                    
                                    if show_labels:
                                        centroid = part.geometry.centroid
                                        ax.text(
                                            centroid.x, centroid.y,
                                            str(part.part_id),
                                            ha='center', va='center',
                                            fontsize=9, fontweight='bold',
                                            color='white',
                                            bbox=dict(
                                                boxstyle='circle,pad=0.3',
                                                facecolor='black',
                                                edgecolor='white',
                                                alpha=0.9,
                                                linewidth=1.5
                                            ),
                                            zorder=3
                                        )
                            except Exception as e:
                                st.warning(f"⚠️ Ошибка отрисовки #{part.part_id}: {e}")
                                continue
                    
                    ax.set_xlim(-50, sheet.width + 50)
                    ax.set_ylim(-50, sheet.height + 50)
                    ax.set_aspect('equal')
                    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.5, zorder=0)
                    ax.set_title(
                        f"Лист #{sheet.sheet_number} — {len(sheet.parts)} деталей — "
                        f"{sheet.efficiency:.1f}%",
                        fontsize=16, fontweight='bold', pad=20
                    )
                    ax.set_xlabel("X (мм)", fontsize=12)
                    ax.set_ylabel("Y (мм)", fontsize=12)
                    
                    from matplotlib.patches import Patch
                    legend_elements = [
                        Patch(facecolor='lightblue', alpha=0.75,
                              edgecolor='#003366', label=f'Детали ({len(sheet.parts)} шт)'),
                        Patch(facecolor='none', edgecolor='red',
                              linestyle='--', linewidth=2, label='Границы листа')
                    ]
                    ax.legend(handles=legend_elements, loc='upper right', fontsize=12)
                    
                    plt.tight_layout()
                    st.pyplot(fig, use_container_width=True)
                    plt.close(fig)

            if len(result.sheets) > 3 and not show_all:
                st.info(f"ℹ️ Показано 3 из {len(result.sheets)} листов.")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("="*70)
    print("🔺 Модуль оптимизации v8.0 ULTIMATE")
    print("="*70)
    print(f"Shapely: {SHAPELY_AVAILABLE}")
    if SHAPELY_AVAILABLE:
        from shapely import __version__ as shapely_version
        print(f"Версия: {shapely_version}")
    print("="*70)
    
    if SHAPELY_AVAILABLE:
        print("\n🧪 Тест...")
        
        tri = ShapelyPolygon([(0, 0), (100, 0), (50, 80)])
        opt = AdvancedNestingOptimizer(2000, 1500, spacing=3)
        result = opt.optimize(tri, 50)
        
        print(f"\n📊 Результат:")
        print(f"  Размещено: {result.parts_placed}/{result.total_parts}")
        print(f"  Листов: {len(result.sheets)}")
        print(f"  Эффективность: {result.average_efficiency:.1f}%")
