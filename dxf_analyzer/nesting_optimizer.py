from typing import List, Optional, Tuple
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.affinity import translate, rotate
import logging

logger = logging.getLogger(__name__)


# ==================== ПРОДВИНУТЫЙ АЛГОРИТМ РАСКРОЯ ====================

class AdvancedNestingOptimizer:
    """
    Продвинутый алгоритм раскроя с АДАПТИВНОЙ стратегией.
    Специальная оптимизация для треугольников с зубчатой упаковкой.

    Исправлены баги:
      1. effective_width: убран лишний +spacing, шаг = base_width / 2.
      2. Y-смещение перевёрнутого треугольника: магическое 0.6 заменено
         точным расчётом от rotated_bounds.
      3. Цикл размещения: for+part_num-=1 заменён на while-loop.
      4. Минимальный отступ: spacing*0.3 → spacing*0.95.
      5. X-позиция после rotate: пересчитывается через актуальные
         rotated_bounds, отдельный if angle==180 для y убран.
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

    def optimize(self, part_geometry: ShapelyPolygon, quantity: int) -> "NestingResult":
        """Выполняет оптимизацию раскроя с адаптивной стратегией."""
        normalized_geom = self._normalize_geometry(part_geometry)
        self.shape_type = get_polygon_type(normalized_geom)
        logger.info(f"Detected shape type: {self.shape_type}")

        if self.shape_type == "triangle":
            return self._optimize_triangles(normalized_geom, quantity)
        else:
            return self._optimize_general(normalized_geom, quantity)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _normalize_geometry(self, geom: ShapelyPolygon) -> ShapelyPolygon:
        """Перемещает центр bounding box в (0, 0)."""
        bounds = geom.bounds
        cx = (bounds[0] + bounds[2]) / 2
        cy = (bounds[1] + bounds[3]) / 2
        return translate(geom, xoff=-cx, yoff=-cy)

    # ------------------------------------------------------------------
    # Треугольная зубчатая упаковка
    # ------------------------------------------------------------------

    def _optimize_triangles(
        self, part_geometry: ShapelyPolygon, quantity: int
    ) -> "NestingResult":
        """
        Зубчатая упаковка треугольников.

        Принцип: прямые (0°) и перевёрнутые (180°) треугольники
        чередуются в строке, заполняя пространство без разрывов.
        """
        sheets: List["Sheet"] = []
        parts_placed = 0

        bounds = part_geometry.bounds
        base_width = bounds[2] - bounds[0]
        base_height = bounds[3] - bounds[1]

        # ── ИСПРАВЛЕНиЕ БАГ 1 ───────────────────────────────────────
        # Шаг по X = половина ширины треугольника.
        # При зубчатой упаковке каждый следующий треугольник смещается
        # ровно на base_width/2 — перевёрнутый вписывается в пустоту.
        # spacing не прибавляем к шагу; он учитывается только как отступ
        # от краёв листа.
        effective_width = base_width / 2

        # Сколько треугольников влезает в одну строку
        usable_width = self.sheet_width - 2 * self.spacing
        parts_per_row = max(1, int(usable_width / effective_width))

        # Высота строки = высота треугольника + отступ
        row_height = base_height + self.spacing

        current_sheet: Optional["Sheet"] = None

        # ── ИСПРАВЛЕНиЕ БАГ 3 ───────────────────────────────────────
        # for-loop с part_num -= 1 не работает: range уже вычислен.
        # Используем while-loop с ручным управлением счётчиком.
        part_num = 1
        new_sheet_attempts = 0  # защита от бесконечного цикла

        while part_num <= quantity:
            # Создаём новый лист при необходимости
            if current_sheet is None:
                current_sheet = Sheet(
                    sheet_number=len(sheets) + 1,
                    width=self.sheet_width,
                    height=self.sheet_height,
                    parts=[],
                    used_area=0.0,
                    efficiency=0.0,
                )
                sheets.append(current_sheet)
                new_sheet_attempts += 1

            placement = self._find_zigzag_position(
                current_sheet,
                part_geometry,
                base_width,
                base_height,
                effective_width,
                parts_per_row,
                row_height,
                part_num,
            )

            if placement is not None:
                x, y, angle, placed_geom_local = placement
                placed_geom = translate(placed_geom_local, xoff=x, yoff=y)

                placed_part = PlacedPart(
                    part_id=part_num,
                    part_name=f"Деталь #{part_num}",
                    x=x,
                    y=y,
                    rotation=angle,
                    geometry=placed_geom,
                    bounding_box=placed_geom.bounds,
                )

                current_sheet.parts.append(placed_part)
                current_sheet.used_area += part_geometry.area
                current_sheet.efficiency = (
                    current_sheet.used_area / current_sheet.total_area
                ) * 100

                parts_placed += 1
                part_num += 1
                new_sheet_attempts = 0  # сбрасываем счётчик при успехе

            else:
                # Текущий лист заполнен — переходим на следующий
                current_sheet = None

                if new_sheet_attempts >= 2:
                    # Не смогли разместить даже на свежем листе — выходим
                    logger.warning(
                        f"Не удалось разместить деталь #{part_num} — прерываем."
                    )
                    break

        parts_not_placed = quantity - parts_placed
        total_material_used = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        average_efficiency = (
            sum(s.efficiency for s in sheets) / len(sheets) if sheets else 0.0
        )

        return NestingResult(
            sheets=sheets,
            total_parts=quantity,
            parts_placed=parts_placed,
            parts_not_placed=parts_not_placed,
            total_material_used=total_material_used,
            total_waste=total_waste,
            average_efficiency=average_efficiency,
            algorithm_used="Triangle Zigzag Packing",
        )

    def _find_zigzag_position(
        self,
        sheet: "Sheet",
        geometry: ShapelyPolygon,
        base_width: float,
        base_height: float,
        effective_width: float,
        parts_per_row: int,
        row_height: float,
        part_num: int,
    ) -> Optional[Tuple[float, float, float, ShapelyPolygon]]:
        """
        Вычисляет позицию для зубчатой упаковки.

        Возвращает (offset_x, offset_y, angle, rotated_geom) или None.
        offset_x / offset_y — смещение, которое нужно передать в translate().
        """
        num_placed = len(sheet.parts)
        row_index = num_placed // parts_per_row
        col_index = num_placed % parts_per_row

        # Проверяем, помещается ли новая строка
        if (row_index + 1) * row_height + self.spacing > self.sheet_height:
            return None

        # Чётные позиции — прямой (0°), нечётные — перевёрнутый (180°)
        angle = 0.0 if col_index % 2 == 0 else 180.0

        rotated_geom = rotate(geometry, angle, origin="centroid")

        # ── ИСПРАВЛЕНиЕ БАГ 2 + 5 ──────────────────────────────────
        # Берём актуальные bounds ПОСЛЕ поворота.
        # X: шаг равен effective_width; bounds[0] — левый край геометрии
        #    после поворота (centroid мог сместиться).
        # Y: используем rotated_bounds[1], а НЕ добавляем магическое 0.6.
        #    При angle=180 shapely разворачивает треугольник вокруг centroid,
        #    поэтому bounds[1] уже указывает на правильный верхний край.
        rotated_bounds = rotated_geom.bounds

        x = self.spacing + col_index * effective_width - rotated_bounds[0]
        y = self.spacing + row_index * row_height - rotated_bounds[1]

        test_geom = translate(rotated_geom, xoff=x, yoff=y)

        if not self._fits_on_sheet(test_geom):
            return self._find_alternative_position(sheet, rotated_geom)

        # ── ИСПРАВЛЕНиЕ БАГ 4 ───────────────────────────────────────
        # Отступ spacing*0.3 = 1.5 мм — слишком мало, детали касаются.
        # Используем почти полный spacing.
        min_allowed_distance = self.spacing * 0.95

        for part in sheet.parts:
            if test_geom.intersects(part.geometry):
                return self._find_alternative_position(sheet, rotated_geom)
            if test_geom.distance(part.geometry) < min_allowed_distance:
                return self._find_alternative_position(sheet, rotated_geom)

        return (x, y, angle, rotated_geom)

    def _find_alternative_position(
        self,
        sheet: "Sheet",
        geometry: ShapelyPolygon,
    ) -> Optional[Tuple[float, float, float, ShapelyPolygon]]:
        """
        Запасной поиск позиции сканированием всего листа.
        Вызывается когда зубчатая схема не сработала.
        """
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]
        step = 5

        for y_start in range(
            int(self.spacing),
            int(self.sheet_height - part_height),
            step,
        ):
            for x_start in range(
                int(self.spacing),
                int(self.sheet_width - part_width),
                step,
            ):
                offset_x = x_start - bounds[0]
                offset_y = y_start - bounds[1]
                test_geom = translate(geometry, xoff=offset_x, yoff=offset_y)

                if self._can_place_at(sheet, test_geom):
                    angle = self._determine_best_angle(sheet, test_geom)

                    if angle != 0.0:
                        rotated = rotate(geometry, angle, origin="centroid")
                        rb = rotated.bounds
                        offset_x = x_start - rb[0]
                        offset_y = y_start - rb[1]
                        test_geom2 = translate(rotated, xoff=offset_x, yoff=offset_y)

                        if self._can_place_at(sheet, test_geom2):
                            return (offset_x, offset_y, angle, rotated)
                    else:
                        return (offset_x, offset_y, 0.0, geometry)

        return None

    def _determine_best_angle(
        self, sheet: "Sheet", geometry: ShapelyPolygon
    ) -> float:
        """Возвращает угол, противоположный ближайшей детали."""
        if not sheet.parts:
            return 0.0

        nearest = min(sheet.parts, key=lambda p: geometry.distance(p.geometry))
        return 180.0 if nearest.rotation == 0.0 else 0.0

    # ------------------------------------------------------------------
    # Общая упаковка (не-треугольники)
    # ------------------------------------------------------------------

    def _optimize_general(
        self, part_geometry: ShapelyPolygon, quantity: int
    ) -> "NestingResult":
        """Bottom-Left упаковка для произвольных фигур."""
        self.optimal_rotations = get_optimal_rotations_for_shape(
            self.shape_type, self.rotation_step
        )

        sheets: List["Sheet"] = []
        parts_placed = 0

        for part_num in range(1, quantity + 1):
            placed = False

            for sheet in sheets:
                if self._try_place_on_sheet_general(sheet, part_num, part_geometry):
                    placed = True
                    parts_placed += 1
                    break

            if not placed:
                new_sheet = Sheet(
                    sheet_number=len(sheets) + 1,
                    width=self.sheet_width,
                    height=self.sheet_height,
                    parts=[],
                    used_area=0.0,
                    efficiency=0.0,
                )

                if self._try_place_on_sheet_general(new_sheet, part_num, part_geometry):
                    sheets.append(new_sheet)
                    parts_placed += 1
                else:
                    logger.warning(
                        f"Не удалось разместить деталь #{part_num} — прерываем."
                    )
                    break

        parts_not_placed = quantity - parts_placed
        total_material_used = sum(s.total_area for s in sheets)
        total_waste = sum(s.waste_area for s in sheets)
        average_efficiency = (
            sum(s.efficiency for s in sheets) / len(sheets) if sheets else 0.0
        )

        return NestingResult(
            sheets=sheets,
            total_parts=quantity,
            parts_placed=parts_placed,
            parts_not_placed=parts_not_placed,
            total_material_used=total_material_used,
            total_waste=total_waste,
            average_efficiency=average_efficiency,
            algorithm_used=f"Bottom-Left Packing ({self.shape_type})",
        )

    def _try_place_on_sheet_general(
        self,
        sheet: "Sheet",
        part_id: int,
        geometry: ShapelyPolygon,
    ) -> bool:
        """Пробует разместить деталь на листе (все углы поворота)."""
        best_placement = None
        best_score = float("inf")

        for angle in self.optimal_rotations:
            rotated_geom = rotate(geometry, angle, origin="centroid")
            positions = self._find_bottom_left_positions(sheet, rotated_geom)

            for x, y in positions:
                test_geom = translate(rotated_geom, xoff=x, yoff=y)

                if self._can_place_at(sheet, test_geom):
                    score = self._evaluate_placement(sheet, test_geom, angle)

                    if score < best_score:
                        best_score = score
                        best_placement = (x, y, angle, rotated_geom)

                    if not sheet.parts:
                        break

            if best_placement and not sheet.parts:
                break

        if best_placement is None:
            return False

        x, y, angle, final_geom = best_placement
        placed_geom = translate(final_geom, xoff=x, yoff=y)

        placed_part = PlacedPart(
            part_id=part_id,
            part_name=f"Деталь #{part_id}",
            x=x,
            y=y,
            rotation=angle,
            geometry=placed_geom,
            bounding_box=placed_geom.bounds,
        )

        sheet.parts.append(placed_part)
        sheet.used_area += geometry.area
        sheet.efficiency = (sheet.used_area / sheet.total_area) * 100
        return True

    def _find_bottom_left_positions(
        self,
        sheet: "Sheet",
        geometry: ShapelyPolygon,
    ) -> List[Tuple[float, float]]:
        """Генерирует кандидатные позиции по стратегии Bottom-Left."""
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]

        positions: List[Tuple[float, float]] = []

        if not sheet.parts:
            positions.append((-bounds[0] + self.spacing, -bounds[1] + self.spacing))
            return positions

        step = 5

        # Вдоль нижней границы
        for x in range(
            int(self.spacing),
            int(self.sheet_width - part_width),
            step,
        ):
            positions.append((x - bounds[0], self.spacing - bounds[1]))

        # Вблизи существующих деталей
        for part in sheet.parts:
            pb = part.bounding_box

            # Справа
            x_right = pb[2] + self.spacing
            if x_right + part_width <= self.sheet_width:
                positions.append((x_right - bounds[0], pb[1] - bounds[1]))
                positions.append(
                    (x_right - bounds[0], pb[3] - part_height - bounds[1])
                )

            # Сверху
            y_top = pb[3] + self.spacing
            if y_top + part_height <= self.sheet_height:
                positions.append((pb[0] - bounds[0], y_top - bounds[1]))
                positions.append(
                    (pb[2] - part_width - bounds[0], y_top - bounds[1])
                )

        # Снизу вверх, слева направо
        positions.sort(key=lambda p: (p[1], p[0]))
        return positions

    def _evaluate_placement(
        self,
        sheet: "Sheet",
        geometry: ShapelyPolygon,
        angle: float,
    ) -> float:
        """Оценка позиции (меньше = лучше)."""
        bounds = geometry.bounds
        score = bounds[1] * 1000 + bounds[0]

        if sheet.parts:
            min_distance = min(
                geometry.distance(p.geometry) for p in sheet.parts
            )
            if min_distance >= self.spacing:
                score -= (100 - min_distance) * 10

        return score

    # ------------------------------------------------------------------
    # Геометрические утилиты
    # ------------------------------------------------------------------

    def _fits_on_sheet(self, geometry: ShapelyPolygon) -> bool:
        """Возвращает True, если геометрия целиком лежит на листе."""
        b = geometry.bounds
        return (
            b[0] >= 0
            and b[1] >= 0
            and b[2] <= self.sheet_width
            and b[3] <= self.sheet_height
        )

    def _can_place_at(self, sheet: "Sheet", geometry: ShapelyPolygon) -> bool:
        """Проверяет: не выходит за лист и не пересекается/не касается деталей."""
        if not self._fits_on_sheet(geometry):
            return False

        for part in sheet.parts:
            if geometry.intersects(part.geometry):
                return False
            if geometry.distance(part.geometry) < self.spacing:
                return False

        return True
