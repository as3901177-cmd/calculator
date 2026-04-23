"""
Продвинутый алгоритм раскроя с поддержкой произвольных треугольников.
Поддержка DXFObject из ezdxf.
"""

import math
from typing import List, Optional, Tuple, Any
from dataclasses import dataclass, field
import logging

# Безопасный импорт Shapely
try:
    from shapely.geometry import Polygon as ShapelyPolygon
    from shapely.affinity import translate, rotate
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    ShapelyPolygon = Any
    print("Warning: shapely is not installed. Run: pip install shapely")

logger = logging.getLogger(__name__)


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
# Конвертация DXF → Shapely
# ---------------------------------------------------------------------------

def dxf_object_to_shapely(dxf_obj: Any) -> Optional[ShapelyPolygon]:
    """Конвертирует DXFObject (POLYLINE/LWPOLYLINE) в Shapely Polygon."""
    if not SHAPELY_AVAILABLE or dxf_obj is None:
        return None

    try:
        if hasattr(dxf_obj, 'entity'):
            entity = dxf_obj.entity
            if hasattr(entity, 'vertices'):           # POLYLINE
                vertices = [(float(v.dxf.x), float(v.dxf.y)) for v in entity.vertices]
            else:                                     # LWPOLYLINE
                vertices = [(float(p[0]), float(p[1])) for p in entity.points()]
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
    if not SHAPELY_AVAILABLE or geom is None:
        return "unknown"
    try:
        coords = list(geom.exterior.coords)[:-1]
        if len(coords) == 3:
            return "triangle"
        if len(coords) == 4:
            return "quadrilateral"
        return f"polygon ({len(coords)} sides)"
    except:
        return "unknown"


# ---------------------------------------------------------------------------
# Геометрия тесселяции треугольников
# ---------------------------------------------------------------------------

Vec2 = Tuple[float, float]


def _tri_vertices(geom: ShapelyPolygon) -> List[Vec2]:
    coords = list(geom.exterior.coords)[:-1]
    assert len(coords) == 3
    return [(float(x), float(y)) for x, y in coords]


def _reflect_over_edge(p: Vec2, a: Vec2, b: Vec2) -> Vec2:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return p
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    fx = a[0] + t * dx
    fy = a[1] + t * dy
    return (2 * fx - p[0], 2 * fy - p[1])


def _dist_point_to_line(p: Vec2, a: Vec2, b: Vec2) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / length


def _para_height(a: Vec2, b: Vec2, c: Vec2) -> float:
    return 2.0 * _dist_point_to_line(c, a, b)


def _find_best_pairing_edge(verts: List[Vec2]) -> Tuple[int, int, int]:
    edges = [(0, 1, 2), (1, 2, 0), (2, 0, 1)]
    return min(edges, key=lambda e: _para_height(verts[e[0]], verts[e[1]], verts[e[2]]))


@dataclass
class TessellationParams:
    v: List[Vec2]
    r: List[Vec2]
    vec_col: Vec2
    vec_row: Vec2
    para_height: float


def _build_tessellation_params(geom: ShapelyPolygon) -> TessellationParams:
    verts = _tri_vertices(geom)
    ia, ib, ic = _find_best_pairing_edge(verts)
    a, b, c = verts[ia], verts[ib], verts[ic]

    ox, oy = a
    a_ = (0.0, 0.0)
    b_ = (b[0] - ox, b[1] - oy)
    c_ = (c[0] - ox, c[1] - oy)
    c_mirror = _reflect_over_edge(c_, a_, b_)

    return TessellationParams(
        v=[a_, b_, c_],
        r=[b_, a_, c_mirror],
        vec_col=b_,
        vec_row=c_,
        para_height=_para_height(a_, b_, c_),
    )


def _offset_verts(verts: List[Vec2], dx: float, dy: float) -> List[Vec2]:
    return [(x + dx, y + dy) for x, y in verts]


def _make_poly(verts: List[Vec2]) -> ShapelyPolygon:
    return ShapelyPolygon(verts)


def _fits(poly: ShapelyPolygon, sw: float, sh: float) -> bool:
    b = poly.bounds
    return b[0] >= -1e-6 and b[1] >= -1e-6 and b[2] <= sw + 1e-6 and b[3] <= sh + 1e-6


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
        if not SHAPELY_AVAILABLE:
            return self._create_empty_result(quantity, "Shapely not available")

        try:
            normalized = self._normalize_geometry(part_geometry)
            self.shape_type = get_polygon_type(normalized)

            if self.shape_type == "triangle":
                return self._optimize_triangles(normalized, quantity)
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
        b = geom.bounds
        cx = (b[0] + b[2]) / 2
        cy = (b[1] + b[3]) / 2
        return translate(geom, xoff=-cx, yoff=-cy)

    def _optimize_triangles(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        best_result = None
        for base_angle in [0.0, 90.0, 180.0, 270.0]:
            try:
                rotated = rotate(part_geometry, base_angle, origin="centroid")
                rotated = self._normalize_geometry(rotated)
                params = _build_tessellation_params(rotated)

                if params.para_height < 1e-6 or math.hypot(*params.vec_col) < 1e-6:
                    continue

                result = self._place_tessellation(rotated, params, quantity, base_angle)
                if best_result is None or result.parts_placed > best_result.parts_placed:
                    best_result = result
            except Exception as exc:
                logger.warning(f"Тесселяция при {base_angle}° не удалась: {exc}")
                continue

        return best_result or self._optimize_general(part_geometry, quantity)

    def _place_tessellation(
        self, part_geometry: ShapelyPolygon, params: TessellationParams,
        quantity: int, base_angle: float
    ) -> NestingResult:
        sheets: List[Sheet] = []
        parts_placed = 0
        part_area = part_geometry.area

        all_v = params.v + params.r
        tile_min_x = min(p[0] for p in all_v)
        tile_min_y = min(p[1] for p in all_v)
        tile_max_y = max(p[1] for p in all_v)
        tile_h = tile_max_y - tile_min_y

        row_height = tile_h + self.spacing
        col_step = math.hypot(*params.vec_col)

        usable_w = self.sheet_width - 2 * self.spacing
        usable_h = self.sheet_height - 2 * self.spacing
        tiles_per_row = max(1, int(usable_w / col_step))
        max_rows = max(1, int(usable_h / row_height))

        part_num = 1
        current_sheet = None
        new_sheet_attempts = 0

        while part_num <= quantity:
            if current_sheet is None:
                current_sheet = Sheet(
                    sheet_number=len(sheets) + 1,
                    width=self.sheet_width,
                    height=self.sheet_height,
                )
                sheets.append(current_sheet)
                new_sheet_attempts += 1

            n = self._fill_sheet(
                sheet=current_sheet,
                params=params,
                tile_min_x=tile_min_x,
                tile_min_y=tile_min_y,
                col_step=col_step,
                row_height=row_height,
                tiles_per_row=tiles_per_row,
                max_rows=max_rows,
                quantity_remaining=quantity - parts_placed,
                part_area=part_area,
                start_id=part_num,
            )

            if n > 0:
                parts_placed += n
                part_num += n
                new_sheet_attempts = 0
                current_sheet = None
            else:
                current_sheet = None
                if new_sheet_attempts >= 2:
                    break

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
            algorithm_used=f"Triangle Tessellation (base_angle={base_angle:.0f}°)",
        )

    def _fill_sheet(self, sheet, params, tile_min_x, tile_min_y, col_step,
                   row_height, tiles_per_row, max_rows, quantity_remaining,
                   part_area, start_id) -> int:
        placed = 0
        part_id = start_id

        for row in range(max_rows):
            if placed >= quantity_remaining: break
            dy = self.spacing + row * row_height - tile_min_y
            dx_extra = (col_step / 2) if (row % 2 == 1) else 0.0

            for col in range(tiles_per_row):
                if placed >= quantity_remaining: break
                dx = self.spacing + col * col_step + dx_extra - tile_min_x

                # T1
                t1 = _make_poly(_offset_verts(params.v, dx, dy))
                if _fits(t1, self.sheet_width, self.sheet_height):
                    sheet.parts.append(PlacedPart(
                        part_id=part_id, part_name=f"Деталь #{part_id}",
                        x=dx, y=dy, rotation=0.0, geometry=t1, bounding_box=t1.bounds
                    ))
                    sheet.used_area += part_area
                    sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
                    placed += 1
                    part_id += 1

                # T2
                t2 = _make_poly(_offset_verts(params.r, dx, dy))
                if _fits(t2, self.sheet_width, self.sheet_height):
                    sheet.parts.append(PlacedPart(
                        part_id=part_id, part_name=f"Деталь #{part_id}",
                        x=dx, y=dy, rotation=180.0, geometry=t2, bounding_box=t2.bounds
                    ))
                    sheet.used_area += part_area
                    sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
                    placed += 1
                    part_id += 1

        return placed

    def _optimize_general(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        self.optimal_rotations = [0, 15, 30, 45, 60, 75, 90, 180]
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
                new_sheet = Sheet(sheet_number=len(sheets) + 1,
                                width=self.sheet_width, height=self.sheet_height)
                if self._try_place_general(new_sheet, part_num, part_geometry):
                    sheets.append(new_sheet)
                    parts_placed += 1
                else:
                    break

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
            algorithm_used="Bottom-Left Packing (General)",
        )

    def _try_place_general(self, sheet: Sheet, part_id: int, geometry: ShapelyPolygon) -> bool:
        best = None
        best_score = float("inf")

        for angle in self.optimal_rotations:
            rotated = rotate(geometry, angle, origin="centroid")
            for x, y in self._bottom_left_positions(sheet, rotated):
                test = translate(rotated, xoff=x, yoff=y)
                if self._can_place(sheet, test):
                    score = self._score(sheet, test)
                    if score < best_score:
                        best_score = score
                        best = (x, y, angle, rotated)
                    if not sheet.parts:
                        break

        if best is None:
            return False

        x, y, angle, final = best
        placed_geom = translate(final, xoff=x, yoff=y)
        sheet.parts.append(PlacedPart(
            part_id=part_id, part_name=f"Деталь #{part_id}",
            x=x, y=y, rotation=angle, geometry=placed_geom, bounding_box=placed_geom.bounds
        ))
        sheet.used_area += geometry.area
        sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
        return True

    def _bottom_left_positions(self, sheet: Sheet, geometry: ShapelyPolygon):
        b = geometry.bounds
        pw, ph = b[2] - b[0], b[3] - b[1]
        positions = []

        if not sheet.parts:
            positions.append((-b[0] + self.spacing, -b[1] + self.spacing))
            return positions

        step = 5
        for x in range(int(self.spacing), int(self.sheet_width - pw), step):
            positions.append((x - b[0], self.spacing - b[1]))

        for part in sheet.parts:
            pb = part.bounding_box
            xr = pb[2] + self.spacing
            if xr + pw <= self.sheet_width:
                positions += [(xr - b[0], pb[1] - b[1]), (xr - b[0], pb[3] - ph - b[1])]
            yt = pb[3] + self.spacing
            if yt + ph <= self.sheet_height:
                positions += [(pb[0] - b[0], yt - b[1]), (pb[2] - pw - b[0], yt - b[1])]

        positions.sort(key=lambda p: (p[1], p[0]))
        return positions

    def _score(self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        b = geometry.bounds
        score = b[1] * 1000 + b[0]
        if sheet.parts:
            min_d = min(geometry.distance(p.geometry) for p in sheet.parts)
            if min_d >= self.spacing:
                score -= (100 - min_d) * 10
        return score

    def _fits_on_sheet(self, geometry: ShapelyPolygon) -> bool:
        b = geometry.bounds
        return b[0] >= 0 and b[1] >= 0 and b[2] <= self.sheet_width and b[3] <= self.sheet_height

    def _can_place(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        if not self._fits_on_sheet(geometry):
            return False
        for part in sheet.parts:
            if geometry.intersects(part.geometry) or geometry.distance(part.geometry) < self.spacing:
                return False
        return True


# ---------------------------------------------------------------------------
# Streamlit интерфейс
# ---------------------------------------------------------------------------

def render_nesting_optimizer_tab(objects_data: Any = None):
    """Основная функция для Streamlit вкладки."""
    try:
        import streamlit as st

        st.title("🔧 Оптимизатор Раскроя")

        if not SHAPELY_AVAILABLE:
            st.error("❌ Библиотека **shapely** не установлена.\n\nВыполните: `pip install shapely`")
            return

        st.success("✅ Модуль загружен успешно")

        if objects_data is None:
            st.warning("Данные объектов не переданы.")
            return

        if not isinstance(objects_data, list):
            objects_data = [objects_data]

        st.subheader(f"📦 Загружено объектов: **{len(objects_data)}**")

        table_data = []
        shapely_geoms = []

        for obj in objects_data:
            geom = dxf_object_to_shapely(obj)
            poly_type = get_polygon_type(geom)
            center = getattr(obj, 'center', (0, 0))

            table_data.append({
                "№": getattr(obj, 'num', '?'),
                "Тип": getattr(obj, 'entity_type', 'Unknown'),
                "Замкнут": getattr(obj, 'is_closed', False),
                "Длина (мм)": f"{getattr(obj, 'length', 0):.2f}",
                "Геометрия": poly_type,
                "Центр": f"({center[0]:.1f}, {center[1]:.1f})"
            })
            shapely_geoms.append(geom)

        st.dataframe(table_data, use_container_width=True)

        st.subheader("⚙️ Параметры листа")
        col1, col2, col3 = st.columns(3)
        with col1:
            sheet_width = st.number_input("Ширина листа (мм)", value=3000.0, step=50.0)
        with col2:
            sheet_height = st.number_input("Высота листа (мм)", value=1500.0, step=50.0)
        with col3:
            spacing = st.number_input("Отступ между деталями (мм)", value=10.0, min_value=0.0)

        if st.button("🚀 Запустить оптимизацию", type="primary"):
            with st.spinner("Выполняется оптимизация..."):
                optimizer = AdvancedNestingOptimizer(
                    sheet_width=sheet_width,
                    sheet_height=sheet_height,
                    spacing=spacing
                )

                if shapely_geoms and shapely_geoms[0]:
                    result = optimizer.optimize(shapely_geoms[0], quantity=10)
                    st.success(f"Размещено деталей: **{result.parts_placed}** из {result.total_parts}")
                    st.info(f"Алгоритм: {result.algorithm_used}")
                    st.metric("Средняя эффективность", f"{result.average_efficiency:.1f}%")

                    for sheet in result.sheets:
                        st.write(f"**Лист {sheet.sheet_number}** — "
                               f"{len(sheet.parts)} деталей, эффективность {sheet.efficiency:.1f}%")

    except Exception as e:
        st.error(f"Ошибка: {e}")
        logger.exception("Error in render_nesting_optimizer_tab")
