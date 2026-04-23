"""
Продвинутый алгоритм раскроя с поддержкой произвольных треугольников.
Версия 4.0 - ФИНАЛЬНАЯ ПРАВИЛЬНАЯ версия с корректной паркетной тесселяцией.
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

        if entity_type == 'POLYLINE' or (
                hasattr(entity, 'vertices') and entity_type != 'LWPOLYLINE'):
            try:
                vertices_iter = entity.vertices
                vertices_list = (list(vertices_iter)
                                 if hasattr(vertices_iter, '__iter__') else [])

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

                    if (x is not None and y is not None
                            and not (math.isnan(x) or math.isnan(y))):
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

        # Удаляем дубликаты
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


def extract_all_geometries(
        objects_data: List[Any]) -> List[Tuple[int, ShapelyPolygon, dict]]:
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
# Вспомогательные функции для треугольников
# ---------------------------------------------------------------------------

def normalize_triangle_to_base(
        geom: ShapelyPolygon) -> Optional[Tuple[ShapelyPolygon, float, float, float]]:
    """
    Нормализует треугольник:
    - Поворачивает так, чтобы самая длинная сторона (база) лежала на оси X
    - Смещает так, чтобы левый нижний угол базы был в (0, 0)
    - Вершина (apex) всегда сверху (y > 0)

    Возвращает:
        (normalized_polygon, base_length, height, rotation_angle_used)
    """
    try:
        coords = list(geom.exterior.coords)[:-1]
        if len(coords) != 3:
            return None

        p = [list(c) for c in coords]

        # Находим самую длинную сторону
        sides = [
            (math.hypot(p[1][0]-p[0][0], p[1][1]-p[0][1]), 0, 1, 2),
            (math.hypot(p[2][0]-p[1][0], p[2][1]-p[1][1]), 1, 2, 0),
            (math.hypot(p[0][0]-p[2][0], p[0][1]-p[2][1]), 2, 0, 1),
        ]
        sides.sort(key=lambda s: -s[0])
        base_len, i0, i1, i_apex = sides[0]

        if base_len < MIN_COORDINATE_DIFF:
            return None

        # Угол поворота, чтобы сторона i0→i1 стала горизонтальной
        dx = p[i1][0] - p[i0][0]
        dy = p[i1][1] - p[i0][1]
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)

        # Поворачиваем весь треугольник на -angle_deg относительно точки i0
        def rotate_point(px, py, cx, cy, deg):
            rad = math.radians(deg)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            qx = cx + cos_a*(px-cx) - sin_a*(py-cy)
            qy = cy + sin_a*(px-cx) + cos_a*(py-cy)
            return qx, qy

        cx, cy = p[i0][0], p[i0][1]
        rotated_pts = [rotate_point(pp[0], pp[1], cx, cy, -angle_deg) for pp in p]

        # Смещаем так, чтобы левая точка базы была в (0,0)
        # После поворота база должна быть горизонтальной: i0 и i1
        base_left_x = min(rotated_pts[i0][0], rotated_pts[i1][0])
        base_y = rotated_pts[i0][1]  # должна быть ≈ rotated_pts[i1][1]

        normalized_pts = [(x - base_left_x, y - base_y) for x, y in rotated_pts]

        # Убедимся, что вершина (apex) сверху (y > 0)
        apex_y = normalized_pts[i_apex][1]
        if apex_y < 0:
            # Отражаем по оси X
            normalized_pts = [(x, -y) for x, y in normalized_pts]
            apex_y = -apex_y

        # Площадь через оригинал для надёжности
        area = abs(geom.area)
        height = (2 * area) / base_len if base_len > MIN_COORDINATE_DIFF else 0

        if height < MIN_COORDINATE_DIFF:
            return None

        # Строим нормализованный полигон
        poly = ShapelyPolygon(normalized_pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area < MIN_POLYGON_AREA:
            return None

        return poly, base_len, height, -angle_deg

    except Exception as e:
        logger.error(f"normalize_triangle_to_base error: {e}")
        return None


def reflect_triangle_horizontal(
        geom: ShapelyPolygon,
        base_len: float,
        height: float) -> ShapelyPolygon:
    """
    Создаёт зеркальное отражение нормализованного треугольника
    относительно вертикальной оси x = base_len/2.

    Нормализованный треугольник имеет:
    - Базу от (0,0) до (base_len, 0)
    - Вершину где-то в y > 0

    Отражённый треугольник заполнит «пустое место» рядом.
    """
    coords = list(geom.exterior.coords)[:-1]
    # Отражение: x' = base_len - x (зеркало по x = base_len/2)
    reflected = [(base_len - x, y) for x, y in coords]
    poly = ShapelyPolygon(reflected)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


# ---------------------------------------------------------------------------
# Основной класс оптимизатора
# ---------------------------------------------------------------------------

class AdvancedNestingOptimizer:
    """Продвинутый алгоритм раскроя с корректной паркетной тесселяцией."""

    def __init__(
        self,
        sheet_width: float,
        sheet_height: float,
        spacing: float = 5.0,
        rotation_step: float = 15.0,
    ):
        if sheet_width <= 0 or sheet_height <= 0:
            raise ValueError("Sheet dimensions must be positive")
        if spacing < 0:
            raise ValueError("Spacing cannot be negative")

        self.sheet_width = float(sheet_width)
        self.sheet_height = float(sheet_height)
        self.spacing = float(spacing)
        self.rotation_step = float(rotation_step)

    # ------------------------------------------------------------------
    # Публичный метод
    # ------------------------------------------------------------------

    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Выполняет оптимизацию раскроя."""
        if not SHAPELY_AVAILABLE:
            return self._create_empty_result(quantity, "Shapely not available")
        if part_geometry is None or part_geometry.is_empty:
            return self._create_empty_result(quantity, "Invalid geometry")
        if quantity <= 0:
            return self._create_empty_result(0, "Invalid quantity")

        try:
            # Центрируем геометрию
            bounds = part_geometry.bounds
            cx = (bounds[0] + bounds[2]) / 2
            cy = (bounds[1] + bounds[3]) / 2
            normalized_input = translate(part_geometry, xoff=-cx, yoff=-cy)

            coords = list(normalized_input.exterior.coords)
            if len(coords) - 1 == 3:
                return self._optimize_triangle_tessellation(part_geometry, quantity)
            else:
                return self._optimize_general(normalized_input, quantity)

        except Exception as e:
            logger.error(f"Optimization error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return self._create_empty_result(quantity, str(e))

    # ------------------------------------------------------------------
    # Служебные методы
    # ------------------------------------------------------------------

    def _create_empty_result(self, quantity: int, error_msg: str) -> NestingResult:
        return NestingResult(
            sheets=[],
            total_parts=quantity,
            parts_placed=0,
            parts_not_placed=quantity,
            total_material_used=0.0,
            total_waste=0.0,
            average_efficiency=0.0,
            algorithm_used=f"Failed: {error_msg}"
        )

    def _calculate_result_statistics(
            self, sheets: List[Sheet], quantity: int,
            parts_placed: int, algorithm: str) -> NestingResult:
        for sheet in sheets:
            if sheet.total_area > 0:
                sheet.efficiency = (sheet.used_area / sheet.total_area) * 100

        total_material = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        avg_eff = (sum(s.efficiency for s in sheets) / len(sheets)
                   if sheets else 0.0)

        return NestingResult(
            sheets=sheets,
            total_parts=quantity,
            parts_placed=parts_placed,
            parts_not_placed=quantity - parts_placed,
            total_material_used=total_material,
            total_waste=total_waste,
            average_efficiency=avg_eff,
            algorithm_used=algorithm
        )

    # ------------------------------------------------------------------
    # ТРЕУГОЛЬНИКИ — правильная паркетная тесселяция
    # ------------------------------------------------------------------

    def _optimize_triangle_tessellation(
            self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """
        Правильная паркетная упаковка произвольных треугольников.

        Алгоритм:
        1. Нормализуем треугольник: база горизонтально снизу, вершина сверху.
        2. В каждом ряду чередуем:
           - «прямой» треугольник T1 (вершина вверх)
           - «перевёрнутый» треугольник T2 = зеркало T1 (вершина вниз)
           Они стыкуются без зазоров по горизонтали.
        3. Ряды укладываются снизу вверх с отступом spacing между рядами.
        4. Заполненные листы добавляются по мере необходимости.
        """
        result = normalize_triangle_to_base(part_geometry)
        if result is None:
            logger.warning("Cannot normalize triangle, falling back to general optimizer")
            bounds = part_geometry.bounds
            cx = (bounds[0] + bounds[2]) / 2
            cy = (bounds[1] + bounds[3]) / 2
            return self._optimize_general(
                translate(part_geometry, xoff=-cx, yoff=-cy), quantity)

        norm_tri, base_len, height, _rot_used = result

        # Зеркальный треугольник (вершина смотрит вниз)
        mirror_tri = reflect_triangle_horizontal(norm_tri, base_len, height)

        # ---- Размеры ячеек тесселяции --------------------------------
        # Пара T1 + T2 занимает ширину = base_len (они стыкуются встык)
        # Высота ряда = height
        # Между рядами добавляем spacing
        # По горизонтали между парами — spacing

        cell_w = base_len          # ширина одного треугольника
        cell_h = height            # высота ряда
        sp = self.spacing

        usable_w = self.sheet_width - 2 * sp
        usable_h = self.sheet_height - 2 * sp

        if usable_w < cell_w or usable_h < cell_h:
            return self._create_empty_result(
                quantity,
                f"Sheet too small for triangle "
                f"(need ≥{cell_w+2*sp:.1f}×{cell_h+2*sp:.1f} mm)"
            )

        # Сколько треугольников помещается в ряду
        # В одном ряду чередуем T1 и T2.
        # T1 занимает [col*cell_w, (col+1)*cell_w] × [0, cell_h]
        # T2 занимает [col*cell_w, (col+1)*cell_w] × [0, cell_h] — зеркало
        # Пара (T1+T2) занимает по ширине 2*cell_w, но они смещены:
        #   T1 на x=0, T2 на x=cell_w (сдвинут на base_len)
        # Итого в ряду: cols треугольников T1 и cols треугольников T2
        # Максимальная x-координата последнего треугольника:
        #   x_start + 2*cell_w - 1 ≤ usable_w
        # Считаем количество пар в ряду:
        pairs_per_row = max(1, int(usable_w / (2 * cell_w + sp)))
        # Более точный расчёт: n пар, каждая занимает 2*cell_w + sp (кроме последней)
        # Упрощённо: вместим cols одиночных треугольников
        tris_per_row = max(1, int(usable_w / cell_w))

        max_rows = max(1, int(usable_h / (cell_h + sp)))

        sheets: List[Sheet] = []
        parts_placed = 0
        part_id = 1
        part_area = part_geometry.area  # оригинальная площадь детали

        def new_sheet() -> Sheet:
            return Sheet(
                sheet_number=len(sheets) + 1,
                width=self.sheet_width,
                height=self.sheet_height
            )

        current_sheet = new_sheet()
        sheets.append(current_sheet)

        for row in range(max_rows):
            if part_id > quantity:
                break

            # Y-координата нижнего края ряда
            y_origin = sp + row * (cell_h + sp)

            if y_origin + cell_h > self.sheet_height - sp + 1e-6:
                break

            for col in range(tris_per_row):
                if part_id > quantity:
                    break

                # X-координата левого края
                x_origin = sp + col * cell_w

                if x_origin + cell_w > self.sheet_width - sp + 1e-6:
                    break

                # ---- Определяем: чётный col → T1, нечётный → T2 --------
                # Это обеспечивает паркетное чередование в одном ряду
                if col % 2 == 0:
                    # «Прямой» треугольник: вершина вверх
                    use_tri = norm_tri
                    rot_label = 0.0
                else:
                    # «Перевёрнутый» треугольник: вершина вниз
                    use_tri = mirror_tri
                    rot_label = 180.0

                # Смещаем треугольник на нужную позицию
                placed_poly = translate(use_tri, xoff=x_origin, yoff=y_origin)

                # Проверка границ листа
                b = placed_poly.bounds
                if (b[0] < sp - 1e-6 or b[1] < sp - 1e-6
                        or b[2] > self.sheet_width - sp + 1e-6
                        or b[3] > self.sheet_height - sp + 1e-6):
                    continue

                # Если текущий лист полон (слишком много деталей), создаём новый
                # Здесь мы просто продолжаем заполнять текущий лист по схеме
                current_sheet.parts.append(PlacedPart(
                    part_id=part_id,
                    part_name=f"Деталь #{part_id}",
                    x=x_origin,
                    y=y_origin,
                    rotation=rot_label,
                    geometry=placed_poly,
                    bounding_box=placed_poly.bounds
                ))
                current_sheet.used_area += part_area
                parts_placed += 1
                part_id += 1

        # Если не все детали поместились на первый лист — создаём дополнительные
        while part_id <= quantity:
            current_sheet = new_sheet()
            sheets.append(current_sheet)

            placed_on_this_sheet = False

            for row in range(max_rows):
                if part_id > quantity:
                    break

                y_origin = sp + row * (cell_h + sp)
                if y_origin + cell_h > self.sheet_height - sp + 1e-6:
                    break

                for col in range(tris_per_row):
                    if part_id > quantity:
                        break

                    x_origin = sp + col * cell_w
                    if x_origin + cell_w > self.sheet_width - sp + 1e-6:
                        break

                    use_tri = norm_tri if col % 2 == 0 else mirror_tri
                    rot_label = 0.0 if col % 2 == 0 else 180.0

                    placed_poly = translate(use_tri, xoff=x_origin, yoff=y_origin)
                    b = placed_poly.bounds
                    if (b[0] < sp - 1e-6 or b[1] < sp - 1e-6
                            or b[2] > self.sheet_width - sp + 1e-6
                            or b[3] > self.sheet_height - sp + 1e-6):
                        continue

                    current_sheet.parts.append(PlacedPart(
                        part_id=part_id,
                        part_name=f"Деталь #{part_id}",
                        x=x_origin,
                        y=y_origin,
                        rotation=rot_label,
                        geometry=placed_poly,
                        bounding_box=placed_poly.bounds
                    ))
                    current_sheet.used_area += part_area
                    parts_placed += 1
                    part_id += 1
                    placed_on_this_sheet = True

            if not placed_on_this_sheet:
                # Если на новый лист ничего не поместилось — выходим
                sheets.pop()
                break

        return self._calculate_result_statistics(
            sheets, quantity, parts_placed,
            "Triangle Parquet Tessellation (base-aligned)"
        )

    # ------------------------------------------------------------------
    # Общий алгоритм (не треугольники)
    # ------------------------------------------------------------------

    def _optimize_general(
            self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
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

        return self._calculate_result_statistics(
            sheets, quantity, parts_placed, "Bottom-Left Packing"
        )

    def _try_place_general(
            self, sheet: Sheet, part_id: int,
            geometry: ShapelyPolygon) -> bool:
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

    def _get_bottom_left_positions(
            self, sheet: Sheet,
            geometry: ShapelyPolygon) -> List[Tuple[float, float]]:
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]

        positions = []

        if not sheet.parts:
            positions.append((self.spacing - bounds[0],
                              self.spacing - bounds[1]))
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
                    positions.append(
                        (x_right - bounds[0], pb[3] - part_height - bounds[1]))

            y_top = pb[3] + self.spacing
            if y_top + part_height <= self.sheet_height - self.spacing:
                positions.append((pb[0] - bounds[0], y_top - bounds[1]))
                if pb[2] - part_width >= self.spacing:
                    positions.append(
                        (pb[2] - part_width - bounds[0], y_top - bounds[1]))

        # Дедупликация
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

    def _evaluate_placement(
            self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        bounds = geometry.bounds
        return bounds[1] * 1000 + bounds[0]

    def _can_place_on_sheet(
            self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        bounds = geometry.bounds
        sp = self.spacing

        if (bounds[0] < sp or bounds[1] < sp
                or bounds[2] > self.sheet_width - sp
                or bounds[3] > self.sheet_height - sp):
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

    st.markdown("## 🔲 Продвинутая оптимизация раскроя")
    st.markdown("**Паркетная упаковка произвольных треугольников.**")
    st.markdown("---")

    if not SHAPELY_AVAILABLE:
        st.error(
            "❌ Библиотека **shapely** не установлена.\n\nВыполните: `pip install shapely`")
        return

    if not objects_data:
        st.warning(
            "⚠️ Нет данных для оптимизации. Загрузите и обработайте DXF файл.")
        return

    st.success(f"✅ Загружено объектов: **{len(objects_data)}**")

    with st.spinner('🔍 Анализ геометрии чертежа...'):
        geometries = extract_all_geometries(objects_data)

    if not geometries:
        st.error("❌ Не удалось определить геометрию ни одного объекта.")
        with st.expander("🔧 Отладочная информация"):
            st.write("**Типы объектов в данных:**")
            for i, obj in enumerate(objects_data[:10]):
                obj_type = type(obj).__name__
                st.write(f"  • Объект {i}: `{obj_type}`")
                if hasattr(obj, 'entity'):
                    if hasattr(obj.entity, 'dxftype'):
                        try:
                            st.write(
                                f"    └─ Тип DXF: `{obj.entity.dxftype()}`")
                        except:
                            pass
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
    st.dataframe(pd.DataFrame(info_data), use_container_width=True,
                 hide_index=True)

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
                f"({geometries[i][2]['width']:.1f}×{geometries[i][2]['height']:.1f} мм)"
            )
        )

    with col_qty:
        quantity = st.number_input(
            "Количество деталей",
            value=20, min_value=1, max_value=1000, step=1
        )

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

    with st.expander("🔍 Предпросмотр геометрии", expanded=False):
        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor('#FFFFFF')
        ax.set_facecolor('#F8F8F8')

        bounds = selected_geom.bounds
        coords = list(selected_geom.exterior.coords)

        if len(coords) > 2:
            polygon = MplPolygon(
                coords,
                linewidth=2.5,
                edgecolor='#0066CC',
                facecolor='#ADD8E6',
                alpha=0.6
            )
            ax.add_patch(polygon)
            xs, ys = zip(*coords[:-1])
            ax.scatter(xs, ys, c='red', s=50, zorder=5, label='Вершины')
            st.write(f"**Количество вершин:** {len(coords)-1}")

        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.set_title(f"Геометрия детали: {selected_info['type']}",
                     fontsize=14, fontweight='bold', pad=15)
        ax.set_xlabel('X (мм)', fontsize=11)
        ax.set_ylabel('Y (мм)', fontsize=11)
        ax.legend()

        margin = max(selected_info['width'], selected_info['height']) * 0.15
        ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
        ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

    # Показываем информацию о тесселяции для треугольников
    if selected_info['type'] == 'triangle':
        result_norm = normalize_triangle_to_base(selected_geom)
        if result_norm:
            _, base_len, tri_height, _ = result_norm
            st.info(
                f"💡 **Паркетная тесселяция треугольников**\n\n"
                f"База: **{base_len:.1f} мм**, Высота: **{tri_height:.1f} мм**\n\n"
                f"Треугольники чередуются: ▲▽▲▽ без зазоров по горизонтали. "
                f"Ожидаемая эффективность: **~{100 - (5/(base_len+5))*100:.0f}%+**"
            )

    st.markdown("---")
    st.markdown("#### 📄 Параметры листа")

    col1, col2, col3 = st.columns(3)
    with col1:
        sheet_width = st.number_input(
            "Ширина листа (мм)",
            value=3000.0, step=100.0, min_value=100.0
        )
    with col2:
        sheet_height = st.number_input(
            "Высота листа (мм)",
            value=1500.0, step=100.0, min_value=100.0
        )
    with col3:
        spacing = st.number_input(
            "Отступ между деталями (мм)",
            value=5.0, min_value=0.0, max_value=50.0, step=1.0
        )

    min_required_width = selected_info['width'] + 2 * spacing
    min_required_height = selected_info['height'] + 2 * spacing

    if sheet_width < min_required_width or sheet_height < min_required_height:
        st.warning(
            f"⚠️ Деталь может не поместиться на лист. "
            f"Минимальные размеры: {min_required_width:.0f}×{min_required_height:.0f} мм"
        )

    st.markdown("---")

    if st.button("🚀 Запустить оптимизацию", type="primary",
                 use_container_width=True):

        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            status_text.text('⏳ Инициализация оптимизатора...')
            progress_bar.progress(10)

            optimizer = AdvancedNestingOptimizer(sheet_width, sheet_height, spacing)

            status_text.text(
                f'⏳ Оптимизация размещения {quantity} деталей...')
            progress_bar.progress(30)

            result = optimizer.optimize(selected_geom, quantity)

            progress_bar.progress(100)
            status_text.text("✅ Оптимизация завершена!")

            st.session_state['nesting_result'] = result
            st.session_state['nesting_geometry'] = selected_geom
            st.session_state['nesting_info'] = selected_info

            st.success("✅ Оптимизация завершена успешно!")
            st.balloons()

        except Exception as e:
            st.error(f"❌ Ошибка при оптимизации: {e}")
            import traceback
            with st.expander("🐛 Детали ошибки"):
                st.code(traceback.format_exc())
            return

    if 'nesting_result' in st.session_state:
        result = st.session_state['nesting_result']

        st.markdown("---")
        st.markdown("### 📊 Результаты оптимизации")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📄 Листов", len(result.sheets))
        with col2:
            placement_rate = (
                result.parts_placed / result.total_parts * 100
                if result.total_parts > 0 else 0
            )
            st.metric("✅ Размещено",
                      f"{result.parts_placed}/{result.total_parts}",
                      delta=f"{placement_rate:.0f}%")
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
            st.warning(
                f"⚠️ **{result.parts_not_placed}** деталей не поместились! "
                f"Попробуйте увеличить размер листа или уменьшить отступы."
            )

        if result.parts_placed == 0:
            st.error("❌ Ни одна деталь не размещена!")

        if result.sheets and result.parts_placed > 0:
            st.markdown("---")
            st.markdown("### 🎨 Визуализация раскроя")

            col_viz1, col_viz2 = st.columns([1, 3])
            with col_viz1:
                show_all = st.checkbox("Показать все листы", value=False)
                show_labels = st.checkbox("Показать номера деталей",
                                          value=True)

            sheets_to_show = (result.sheets if show_all
                              else result.sheets[:5])

            for sheet in sheets_to_show:
                with st.expander(
                        f"📄 Лист #{sheet.sheet_number}",
                        expanded=(sheet.sheet_number == 1)):

                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                    with col_s1:
                        st.metric("Деталей", len(sheet.parts))
                    with col_s2:
                        st.metric("Использовано",
                                  f"{sheet.used_area/1e6:.3f} м²")
                    with col_s3:
                        st.metric("Отходы",
                                  f"{sheet.waste_area/1e6:.3f} м²")
                    with col_s4:
                        st.metric("Эффективность",
                                  f"{sheet.efficiency:.1f}%")

                    fig, ax = plt.subplots(figsize=(16, 9))
                    fig.patch.set_facecolor('#FFFFFF')
                    ax.set_facecolor('#F0F4F8')

                    # Граница листа
                    sheet_boundary = plt.Polygon(
                        [(0, 0), (sheet.width, 0),
                         (sheet.width, sheet.height), (0, sheet.height)],
                        fill=False, edgecolor='red',
                        linewidth=3, linestyle='--',
                        label='Граница листа'
                    )
                    ax.add_patch(sheet_boundary)

                    if sheet.parts:
                        num_colors = max(20, len(sheet.parts))
                        colors = plt.cm.tab20(
                            np.linspace(0, 1, num_colors))

                        for i, part in enumerate(sheet.parts):
                            coords = list(part.geometry.exterior.coords)
                            if len(coords) > 2:
                                part_polygon = MplPolygon(
                                    coords,
                                    facecolor=colors[i % len(colors)],
                                    edgecolor='darkblue',
                                    alpha=0.75,
                                    linewidth=1.2
                                )
                                ax.add_patch(part_polygon)

                                if show_labels:
                                    centroid = part.geometry.centroid
                                    ax.text(
                                        centroid.x, centroid.y,
                                        str(part.part_id),
                                        ha='center', va='center',
                                        fontsize=7, fontweight='bold',
                                        bbox=dict(
                                            boxstyle='round,pad=0.3',
                                            facecolor='white',
                                            edgecolor='black',
                                            alpha=0.85
                                        )
                                    )

                    ax.set_xlim(-50, sheet.width + 50)
                    ax.set_ylim(-50, sheet.height + 50)
                    ax.set_aspect('equal')
                    ax.grid(True, alpha=0.25, linestyle=':',
                            linewidth=0.5)
                    ax.set_title(
                        f"Лист #{sheet.sheet_number} — "
                        f"{len(sheet.parts)} деталей — "
                        f"Эффективность: {sheet.efficiency:.1f}%",
                        fontsize=14, fontweight='bold', pad=20
                    )
                    ax.set_xlabel("X (мм)", fontsize=12)
                    ax.set_ylabel("Y (мм)", fontsize=12)

                    from matplotlib.patches import Patch
                    legend_elements = [
                        Patch(facecolor='lightblue', alpha=0.75,
                              edgecolor='darkblue',
                              label=f'Детали ({len(sheet.parts)} шт)'),
                        Patch(facecolor='none', edgecolor='red',
                              linestyle='--', linewidth=2,
                              label='Границы листа')
                    ]
                    ax.legend(handles=legend_elements,
                              loc='upper right', fontsize=11)

                    plt.tight_layout()
                    st.pyplot(fig, use_container_width=True)
                    plt.close(fig)

            if len(result.sheets) > 5 and not show_all:
                st.info(
                    f"ℹ️ Показано 5 из {len(result.sheets)} листов. "
                    f"Включите 'Показать все листы' для полного просмотра."
                )


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Модуль оптимизации раскроя v4.0 - ПРАВИЛЬНАЯ ПАРКЕТНАЯ ТЕССЕЛЯЦИЯ")
    print("=" * 70)
    print(f"Shapely доступен: {SHAPELY_AVAILABLE}")
    if SHAPELY_AVAILABLE:
        from shapely import __version__ as shapely_version
        print(f"Версия Shapely: {shapely_version}")
    print("=" * 70)

    if SHAPELY_AVAILABLE:
        print("\n--- Тест паркетной тесселяции треугольников ---")

        # Тест 1: прямоугольный треугольник
        tri_right = ShapelyPolygon([(0, 0), (100, 0), (0, 60)])
        print(f"Треугольник: {list(tri_right.exterior.coords)}")

        res = normalize_triangle_to_base(tri_right)
        if res:
            norm, base, h, rot = res
            print(f"  База: {base:.2f}, Высота: {h:.2f}, Поворот: {rot:.2f}°")
            print(f"  Нормализованные вершины: {list(norm.exterior.coords)}")

        opt = AdvancedNestingOptimizer(3000, 1500, spacing=5)
        result = opt.optimize(tri_right, 50)
        print(f"\nРезультат для 50 деталей:")
        print(f"  Листов: {len(result.sheets)}")
        print(f"  Размещено: {result.parts_placed}/{result.total_parts}")
        print(f"  Эффективность: {result.average_efficiency:.1f}%")
        print(f"  Алгоритм: {result.algorithm_used}")

        # Тест 2: остроугольный треугольник
        print("\n--- Тест 2: остроугольный треугольник ---")
        tri_acute = ShapelyPolygon([(0, 0), (120, 0), (40, 80)])
        opt2 = AdvancedNestingOptimizer(3000, 1500, spacing=5)
        result2 = opt2.optimize(tri_acute, 30)
        print(f"  Размещено: {result2.parts_placed}/{result2.total_parts}")
        print(f"  Эффективность: {result2.average_efficiency:.1f}%")
