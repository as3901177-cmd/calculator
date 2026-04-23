"""
Продвинутый алгоритм раскроя с поддержкой произвольных треугольников.

Ключевая идея для треугольников (равносторонних, равнобедренных, разносторонних):
  Любые ДВА одинаковых треугольника можно сложить в параллелограмм,
  отразив один из них относительно любой из трёх сторон.
  Алгоритм перебирает все три стороны, выбирает ту, что даёт
  параллелограмм с наименьшей высотой (= наиболее «плоский» → больше рядов),
  и строит тесселяцию из таких параллелограммов.

  Схема (сторона AB):

      C                    C'
     / \\                 //\\
    /   \\     →         //  \\
   A-----B         A---B---A'
                        \\   /
                         \\ /
                          C

  Параллелограмм A-B-C'-C — шагаем по нему как по тайлу.

Шаги _optimize_triangles:
  1. _find_best_pairing_edge  — выбрать сторону с min высотой параллелограмма.
  2. _build_tessellation_params — вычислить координаты T1/T2 и векторы шага.
  3. _fill_sheet_with_tessellation — заполнить лист строками тайлов.
  4. Перебираем 4 поворота (0°,90°,180°,270°) — берём лучший.
"""

import math
from typing import List, Optional, Tuple
from dataclasses import dataclass, field

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.affinity import translate, rotate
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Типы данных (замените на реальные из вашего проекта)
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


def get_polygon_type(geom: ShapelyPolygon) -> str:
    coords = list(geom.exterior.coords)[:-1]
    if len(coords) == 3:
        return "triangle"
    if len(coords) == 4:
        return "quadrilateral"
    return "polygon"


def get_optimal_rotations_for_shape(
    shape_type: Optional[str], rotation_step: float
) -> List[float]:
    if shape_type == "quadrilateral":
        return [0.0, 90.0]
    angles, a = [], 0.0
    while a < 360.0:
        angles.append(a)
        a += rotation_step
    return angles


# ---------------------------------------------------------------------------
# Геометрия тесселяции
# ---------------------------------------------------------------------------

Vec2 = Tuple[float, float]


def _tri_vertices(geom: ShapelyPolygon) -> List[Vec2]:
    coords = list(geom.exterior.coords)[:-1]
    assert len(coords) == 3
    return [(float(x), float(y)) for x, y in coords]


def _reflect_over_edge(p: Vec2, a: Vec2, b: Vec2) -> Vec2:
    """Отражает точку p через прямую AB."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    fx, fy = a[0] + t * dx, a[1] + t * dy
    return (2 * fx - p[0], 2 * fy - p[1])


def _dist_point_to_line(p: Vec2, a: Vec2, b: Vec2) -> float:
    """Расстояние от p до бесконечной прямой AB."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / length


def _para_height(a: Vec2, b: Vec2, c: Vec2) -> float:
    """Высота параллелограмма = 2 * расстояние от C до AB."""
    return 2.0 * _dist_point_to_line(c, a, b)


def _find_best_pairing_edge(verts: List[Vec2]) -> Tuple[int, int, int]:
    """
    Выбирает сторону (ia, ib, ic) с минимальной высотой параллелограмма.
    Чем меньше высота → тем «шире» строка → тем больше рядов влезает.
    """
    edges = [(0, 1, 2), (1, 2, 0), (2, 0, 1)]
    return min(
        edges,
        key=lambda e: _para_height(verts[e[0]], verts[e[1]], verts[e[2]]),
    )


@dataclass
class TessellationParams:
    """Параметры тайла для тесселяции."""
    # Вершины T1 (оригинал), нормированные так, что A = (0, 0)
    v: List[Vec2]   # [A, B, C]
    # Вершины T2 (отражение через AB)
    r: List[Vec2]   # [B, A, C']
    # Вектор шага между тайлами в строке (= вектор AB)
    vec_col: Vec2
    # Вектор шага между строками (= вектор AC)
    vec_row: Vec2
    # Высота параллелограмма (без spacing)
    para_height: float


def _build_tessellation_params(geom: ShapelyPolygon) -> TessellationParams:
    """
    Строит параметры тесселяции.

    Нормализация: A (начало лучшей стороны) сдвигается в (0, 0).
    T1 = A, B, C
    T2 = B, A, C'  (C' = отражение C через AB)

    vec_col = B — шаг вдоль строки (один тайл = ширина AB).
    vec_row = C — шаг между строками (высота = |Cy|).
    """
    verts = _tri_vertices(geom)
    ia, ib, ic = _find_best_pairing_edge(verts)
    a, b, c = verts[ia], verts[ib], verts[ic]

    # Нормализуем: A → (0, 0)
    ox, oy = a
    a_ = (0.0, 0.0)
    b_ = (b[0] - ox, b[1] - oy)
    c_ = (c[0] - ox, c[1] - oy)

    # C' = отражение C через AB
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
# Основной класс
# ---------------------------------------------------------------------------


class AdvancedNestingOptimizer:
    """
    Продвинутый алгоритм раскроя с адаптивной стратегией.

    Для ЛЮБЫХ треугольников (равносторонних, равнобедренных, разносторонних):
      — строит тесселяцию через параллелограмм (пара T1+T2 по лучшей стороне)
      — перебирает 4 поворота базового треугольника, берёт лучший
      — эффективность стремится к теоретическому максимуму ~100%
        (без spacing) или ~85–95% с учётом отступов между строками

    Для остальных фигур: Bottom-Left с перебором углов поворота.
    """

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

    # ------------------------------------------------------------------
    # Публичный метод
    # ------------------------------------------------------------------

    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Выполняет оптимизацию раскроя."""
        normalized = self._normalize_geometry(part_geometry)
        self.shape_type = get_polygon_type(normalized)
        logger.info(f"Shape type: {self.shape_type}")

        if self.shape_type == "triangle":
            return self._optimize_triangles(normalized, quantity)
        return self._optimize_general(normalized, quantity)

    # ------------------------------------------------------------------
    # Нормализация
    # ------------------------------------------------------------------

    def _normalize_geometry(self, geom: ShapelyPolygon) -> ShapelyPolygon:
        """Сдвигает центр bounding box в (0, 0)."""
        b = geom.bounds
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return translate(geom, xoff=-cx, yoff=-cy)

    # ------------------------------------------------------------------
    # Треугольная тесселяция
    # ------------------------------------------------------------------

    def _optimize_triangles(
        self, part_geometry: ShapelyPolygon, quantity: int
    ) -> NestingResult:
        """
        Тесселяция произвольного треугольника.

        Перебирает 4 поворота (0°, 90°, 180°, 270°) — выбирает тот,
        при котором на листе помещается максимальное количество деталей.
        """
        best_result: Optional[NestingResult] = None

        for base_angle in [0.0, 90.0, 180.0, 270.0]:
            rotated = rotate(part_geometry, base_angle, origin="centroid")
            rotated = self._normalize_geometry(rotated)

            try:
                params = _build_tessellation_params(rotated)
            except Exception as exc:
                logger.warning(f"Тесселяция при {base_angle}° не удалась: {exc}")
                continue

            # Пропускаем вырожденные случаи
            if params.para_height < 1e-6 or math.hypot(*params.vec_col) < 1e-6:
                continue

            result = self._place_tessellation(rotated, params, quantity, base_angle)

            if best_result is None or result.parts_placed > best_result.parts_placed:
                best_result = result

        if best_result is None:
            logger.warning("Тесселяция не удалась — используем Bottom-Left.")
            return self._optimize_general(part_geometry, quantity)

        return best_result

    def _place_tessellation(
        self,
        part_geometry: ShapelyPolygon,
        params: TessellationParams,
        quantity: int,
        base_angle: float,
    ) -> NestingResult:
        """Заполняет листы тесселяцией, пока не разместим все детали."""
        sheets: List[Sheet] = []
        parts_placed = 0
        part_area = part_geometry.area

        # Вычисляем геометрию тайла (bounding box обоих треугольников)
        all_v = params.v + params.r
        tile_min_x = min(p[0] for p in all_v)
        tile_min_y = min(p[1] for p in all_v)
        tile_max_x = max(p[0] for p in all_v)
        tile_max_y = max(p[1] for p in all_v)
        tile_w = tile_max_x - tile_min_x
        tile_h = tile_max_y - tile_min_y

        # Высота строки с отступом
        row_height = tile_h + self.spacing

        # Шаг по колонке: ширина тайла (два треугольника рядом)
        # Для корректной тесселяции шаг = длина стороны стыковки
        col_step = math.hypot(params.vec_col[0], params.vec_col[1])

        usable_w = self.sheet_width - 2 * self.spacing
        usable_h = self.sheet_height - 2 * self.spacing
        tiles_per_row = max(1, int(usable_w / col_step))
        max_rows = max(1, int(usable_h / row_height))

        part_num = 1
        new_sheet_attempts = 0
        current_sheet: Optional[Sheet] = None

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
                current_sheet = None  # переходим на новый лист
            else:
                current_sheet = None
                if new_sheet_attempts >= 2:
                    logger.warning(f"Не удалось разместить деталь #{part_num} — стоп.")
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
            algorithm_used=f"Triangle Tessellation (base_angle={base_angle}°)",
        )

    def _fill_sheet(
        self,
        sheet: Sheet,
        params: TessellationParams,
        tile_min_x: float,
        tile_min_y: float,
        col_step: float,
        row_height: float,
        tiles_per_row: int,
        max_rows: int,
        quantity_remaining: int,
        part_area: float,
        start_id: int,
    ) -> int:
        """
        Заполняет один лист тесселяцией строками тайлов (T1 + T2).

        Размещение:
          • T1 и T2 стыкуются вплотную (отступ = 0) — они образуют параллелограмм.
          • Между строками — self.spacing.
          • Нечётные строки смещаются на col_step / 2 по X (кирпичная раскладка)
            для лучшего заполнения при разносторонних треугольниках.

        Возвращает количество размещённых деталей.
        """
        placed = 0
        part_id = start_id

        for row in range(max_rows):
            if placed >= quantity_remaining:
                break

            # Смещение строки по Y
            dy = self.spacing + row * row_height - tile_min_y

            # Кирпичное смещение по X для нечётных строк
            dx_extra = (col_step / 2) if (row % 2 == 1) else 0.0

            for col in range(tiles_per_row):
                if placed >= quantity_remaining:
                    break

                # Смещение тайла по X
                dx = self.spacing + col * col_step + dx_extra - tile_min_x

                # ── T1: оригинальный треугольник ──────────────────────
                t1 = _make_poly(_offset_verts(params.v, dx, dy))

                if _fits(t1, self.sheet_width, self.sheet_height):
                    sheet.parts.append(PlacedPart(
                        part_id=part_id,
                        part_name=f"Деталь #{part_id}",
                        x=dx, y=dy, rotation=0.0,
                        geometry=t1,
                        bounding_box=t1.bounds,
                    ))
                    sheet.used_area += part_area
                    sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
                    placed += 1
                    part_id += 1

                    if placed >= quantity_remaining:
                        break

                # ── T2: отражённый треугольник ────────────────────────
                t2 = _make_poly(_offset_verts(params.r, dx, dy))

                if _fits(t2, self.sheet_width, self.sheet_height):
                    sheet.parts.append(PlacedPart(
                        part_id=part_id,
                        part_name=f"Деталь #{part_id}",
                        x=dx, y=dy, rotation=180.0,
                        geometry=t2,
                        bounding_box=t2.bounds,
                    ))
                    sheet.used_area += part_area
                    sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
                    placed += 1
                    part_id += 1

        return placed

    # ------------------------------------------------------------------
    # Общая упаковка (не-треугольники)
    # ------------------------------------------------------------------

    def _optimize_general(
        self, part_geometry: ShapelyPolygon, quantity: int
    ) -> NestingResult:
        """Bottom-Left упаковка для произвольных фигур."""
        self.optimal_rotations = get_optimal_rotations_for_shape(
            self.shape_type, self.rotation_step
        )
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
                    height=self.sheet_height,
                )
                if self._try_place_general(new_sheet, part_num, part_geometry):
                    sheets.append(new_sheet)
                    parts_placed += 1
                else:
                    logger.warning(f"Не удалось разместить деталь #{part_num} — стоп.")
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
            algorithm_used=f"Bottom-Left Packing ({self.shape_type})",
        )

    def _try_place_general(
        self, sheet: Sheet, part_id: int, geometry: ShapelyPolygon
    ) -> bool:
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
            if best and not sheet.parts:
                break

        if best is None:
            return False

        x, y, angle, final = best
        placed = translate(final, xoff=x, yoff=y)
        sheet.parts.append(PlacedPart(
            part_id=part_id, part_name=f"Деталь #{part_id}",
            x=x, y=y, rotation=angle,
            geometry=placed, bounding_box=placed.bounds,
        ))
        sheet.used_area += geometry.area
        sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
        return True

    def _bottom_left_positions(
        self, sheet: Sheet, geometry: ShapelyPolygon
    ) -> List[Tuple[float, float]]:
        b = geometry.bounds
        pw, ph = b[2] - b[0], b[3] - b[1]
        positions: List[Tuple[float, float]] = []

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
                positions += [
                    (xr - b[0], pb[1] - b[1]),
                    (xr - b[0], pb[3] - ph - b[1]),
                ]
            yt = pb[3] + self.spacing
            if yt + ph <= self.sheet_height:
                positions += [
                    (pb[0] - b[0], yt - b[1]),
                    (pb[2] - pw - b[0], yt - b[1]),
                ]

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
            if geometry.intersects(part.geometry):
                return False
            if geometry.distance(part.geometry) < self.spacing:
                return False
        return True
