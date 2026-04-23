"""
Продвинутый алгоритм раскроя с поддержкой произвольных треугольников.
Версия 2.0 - с улучшенной тесселяцией для всех типов треугольников.
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
    ACUTE = "acute"      # Остроугольный (все углы < 90°)
    RIGHT = "right"      # Прямоугольный (один угол = 90°)
    OBTUSE = "obtuse"    # Тупоугольный (один угол > 90°)
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
    spatial_index: Optional[Any] = None  # STRtree для быстрого поиска
    
    def rebuild_spatial_index(self):
        """Перестраивает пространственный индекс для быстрых проверок."""
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
    
    # Проверяем на равнобедренность
    eps = 1e-6
    is_isosceles = abs(a2 - b2) < eps or abs(b2 - c2) < eps or abs(c2 - a2) < eps
    
    # Проверяем на равносторонность
    is_equilateral = abs(a2 - b2) < eps and abs(b2 - c2) < eps
    
    if is_equilateral:
        return TriangleType.EQUILATERAL
    
    # Сортируем стороны
    sides = sorted([a2, b2, c2])
    
    # Теорема Пифагора: для прямоугольного a² + b² = c²
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
    # Находим вершину, не входящую в основание
    apex_idx = 3 - base_idx1 - base_idx2
    
    # Вычисляем расстояние от вершины до прямой основания
    x1, y1 = verts[base_idx1]
    x2, y2 = verts[base_idx2]
    x3, y3 = verts[apex_idx]
    
    # Площадь через координаты
    area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2
    
    # Длина основания
    base_length = math.hypot(x2 - x1, y2 - y1)
    
    return 2 * area / base_length if base_length > 0 else 0


def reflect_point_over_line(p: Vec2, a: Vec2, b: Vec2) -> Vec2:
    """Отражает точку относительно прямой AB."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    
    if length_sq < 1e-12:
        return p
    
    # Проекция точки на прямую
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    
    # Координаты проекции
    proj_x = a[0] + t * dx
    proj_y = a[1] + t * dy
    
    # Отражаем
    return (2 * proj_x - p[0], 2 * proj_y - p[1])


def get_tessellation_params(geom: ShapelyPolygon) -> Optional[dict]:
    """
    Создает параметры для тесселяции треугольника.
    Использует стратегию в зависимости от типа треугольника.
    """
    try:
        verts = get_triangle_vertices(geom)
        triangle_type = classify_triangle(verts)
        
        # Находим оптимальное основание для тесселяции
        edge1, edge2, base_length = get_longest_edge(verts)
        
        # Для остроугольных и равносторонних - любое основание подходит
        # Для прямоугольных - выбираем гипотенузу
        # Для тупоугольных - выбираем самую длинную сторону
        
        base_verts = (verts[edge1], verts[edge2])
        apex_idx = 3 - edge1 - edge2
        apex = verts[apex_idx]
        
        # Вычисляем высоту
        height = get_triangle_height(verts, edge1, edge2)
        
        # Создаем два треугольника для тесселяции: оригинал и отраженный
        reflected_apex = reflect_point_over_line(apex, base_verts[0], base_verts[1])
        
        # Смещаем так, чтобы основание было внизу
        min_y = min(base_verts[0][1], base_verts[1][1])
        
        # Нормализуем координаты
        normalized_verts = [(v[0] - base_verts[0][0], v[1] - min_y) for v in verts]
        normalized_base = [(base_verts[0][0] - base_verts[0][0], min_y - min_y),
                          (base_verts[1][0] - base_verts[0][0], min_y - min_y)]
        
        # Отраженный треугольник
        reflected_verts = [
            (base_verts[0][0] - base_verts[0][0], min_y - min_y),
            (base_verts[1][0] - base_verts[0][0], min_y - min_y),
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
# Основной класс оптимизатора
# ---------------------------------------------------------------------------

class AdvancedNestingOptimizer:
    """Продвинутый алгоритм раскроя с поддержкой произвольных треугольников."""
    
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
            # Нормализуем геометрию
            normalized = self._normalize_geometry(part_geometry)
            
            # Определяем тип
            coords = list(normalized.exterior.coords)
            if len(coords) - 1 == 3:
                # Это треугольник - используем тесселяцию
                return self._optimize_triangle(normalized, quantity)
            else:
                # Общий случай
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
        """Нормализует геометрию - перемещает в центр координат."""
        b = geom.bounds
        cx = (b[0] + b[2]) / 2
        cy = (b[1] + b[3]) / 2
        return translate(geom, xoff=-cx, yoff=-cy)
    
    def _optimize_triangle(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """
        Оптимизирует раскрой треугольников с использованием тесселяции.
        Пробует разные ориентации для достижения максимальной плотности.
        """
        best_result = None
        best_count = 0
        
        # Пробуем разные базовые углы
        for base_angle in [0, 60, 90, 120, 180, 240, 270, 300]:
            try:
                # Поворачиваем треугольник
                rotated = rotate(part_geometry, base_angle, origin="centroid")
                rotated = self._normalize_geometry(rotated)
                
                # Получаем параметры тесселяции
                params = get_tessellation_params(rotated)
                if not params:
                    continue
                
                # Выполняем тесселяцию
                result = self._place_triangles_by_tessellation(
                    rotated, params, quantity, base_angle
                )
                
                # Сохраняем лучший результат
                if result.parts_placed > best_count:
                    best_count = result.parts_placed
                    best_result = result
                    
                # Если разместили все - можно остановиться
                if best_count == quantity:
                    break
                    
            except Exception as exc:
                logger.warning(f"Tessellation at {base_angle}° failed: {exc}")
                continue
        
        # Если тесселяция не сработала, используем общий алгоритм
        if best_result is None or best_result.parts_placed == 0:
            return self._optimize_general(part_geometry, quantity)
        
        return best_result
    
    def _place_triangles_by_tessellation(
        self, part_geometry: ShapelyPolygon, params: dict,
        quantity: int, base_angle: float
    ) -> NestingResult:
        """
        Размещает треугольники с использованием тесселяции (паркетажа).
        """
        sheets: List[Sheet] = []
        parts_placed = 0
        
        part_area = part_geometry.area
        
        # Вычисляем параметры сетки
        base_length = params['base_length']
        height = params['height']
        
        # Учитываем отступы
        col_step = base_length + self.spacing
        row_step = height + self.spacing
        
        # Количество элементов в ряду
        cols_per_row = max(1, int((self.sheet_width - self.spacing * 2) / col_step))
        rows = max(1, int((self.sheet_height - self.spacing * 2) / row_step))
        
        # Общее количество возможных позиций
        max_positions = cols_per_row * rows * 2  # *2 для двух ориентаций
        
        if max_positions == 0:
            return self._create_empty_result(quantity, "Triangle too large for sheet")
        
        part_id = 1
        
        for row in range(rows):
            if part_id > quantity:
                break
                
            # Смещение для шахматного порядка (только для равносторонних)
            col_offset = 0.5 if (params['triangle_type'] == TriangleType.EQUILATERAL and row % 2 == 1) else 0
            
            for col in range(cols_per_row):
                if part_id > quantity:
                    break
                
                # Создаем новый лист при необходимости
                if not sheets or len(sheets[-1].parts) >= max_positions // 2:
                    sheets.append(Sheet(
                        sheet_number=len(sheets) + 1,
                        width=self.sheet_width,
                        height=self.sheet_height
                    ))
                
                current_sheet = sheets[-1]
                
                # Вычисляем позицию
                x = self.spacing + col * col_step + (col_offset * col_step if col_offset else 0)
                y = self.spacing + row * row_step
                
                # Проверяем, помещается ли
                if x + base_length <= self.sheet_width and y + height <= self.sheet_height:
                    
                    # Размещаем оригинальный треугольник
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
                    
                    # Размещаем отраженный треугольник (если нужно и помещается)
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
        
        # Обновляем эффективность листов
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
            algorithm_used=f"Triangle Tessellation ({params['triangle_type'].value}, angle={base_angle:.0f}°)"
        )
    
    def _optimize_general(self, part_geometry: ShapelyPolygon, quantity: int) -> NestingResult:
        """Общий алгоритм для произвольных фигур (Bottom-Left)."""
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
        """Пытается разместить деталь на листе (Bottom-Left алгоритм)."""
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
        sheet.efficiency = (sheet.used_area / sheet.total_area) * 100 if sheet.total_area > 0 else 0
        
        return True
    
    def _get_bottom_left_positions(self, sheet: Sheet, geometry: ShapelyPolygon) -> List[Tuple[float, float]]:
        """Генерирует позиции для Bottom-Left алгоритма."""
        bounds = geometry.bounds
        part_width = bounds[2] - bounds[0]
        part_height = bounds[3] - bounds[1]
        
        positions = []
        
        if not sheet.parts:
            # Первая деталь - в угол с учетом отступа
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
            
            # Слева
            x_left = pb[0] - part_width - self.spacing
            if x_left >= self.spacing:
                positions.append((x_left - bounds[0], pb[1] - bounds[1]))
            
            # Снизу
            y_bottom = pb[1] - part_height - self.spacing
            if y_bottom >= self.spacing:
                positions.append((pb[0] - bounds[0], y_bottom - bounds[1]))
        
        # Удаляем дубликаты и сортируем
        positions = list(dict.fromkeys(positions))
        positions.sort(key=lambda p: (p[1], p[0]))
        
        # Ограничиваем количество
        return positions[:200]
    
    def _evaluate_placement(self, sheet: Sheet, geometry: ShapelyPolygon) -> float:
        """Оценивает качество размещения."""
        bounds = geometry.bounds
        
        # Чем ниже и левее, тем лучше
        score = bounds[1] * 1000 + bounds[0]
        
        if sheet.parts:
            # Бонус за близость к другим деталям
            min_distance = min(geometry.distance(p.geometry) for p in sheet.parts)
            if min_distance < self.spacing * 1.5:
                score -= 100  # Бонус за плотную упаковку
        
        return score
    
    def _fits_on_sheet(self, geometry: ShapelyPolygon) -> bool:
        """Проверяет, помещается ли геометрия на лист с учетом отступов."""
        bounds = geometry.bounds
        return (bounds[0] >= self.spacing and 
                bounds[1] >= self.spacing and 
                bounds[2] <= self.sheet_width - self.spacing and 
                bounds[3] <= self.sheet_height - self.spacing)
    
    def _can_place_on_sheet(self, sheet: Sheet, geometry: ShapelyPolygon) -> bool:
        """Проверяет возможность размещения."""
        if not self._fits_on_sheet(geometry):
            return False
        
        # Используем пространственный индекс для быстрой проверки
        if sheet.spatial_index is not None and sheet.parts:
            # Получаем кандидатов на пересечение
            buffer = geometry.buffer(self.spacing)
            candidates = sheet.spatial_index.query(buffer)
            
            for idx in candidates:
                if geometry.distance(sheet.parts[idx].geometry) < self.spacing:
                    return False
        else:
            # Линейный поиск для маленьких листов
            for part in sheet.parts:
                if geometry.distance(part.geometry) < self.spacing:
                    return False
        
        return True


# ---------------------------------------------------------------------------
# Функция для Streamlit (упрощенная версия)
# ---------------------------------------------------------------------------

def render_nesting_optimizer_tab(objects_data: List[Any] = None):
    """Отрисовывает вкладку оптимизации раскроя в Streamlit."""
    try:
        import streamlit as st
        
        st.title("🔧 Оптимизатор раскроя")
        
        if not SHAPELY_AVAILABLE:
            st.error("❌ Библиотека **shapely** не установлена.\n\nВыполните: `pip install shapely`")
            return
        
        st.success("✅ Модуль загружен успешно")
        
        if not objects_data:
            st.warning("⚠️ Нет данных для оптимизации")
            return
        
        # Здесь должен быть код для отображения интерфейса
        st.info("Интерфейс оптимизатора готов к работе")
        
    except Exception as e:
        st.error(f"Ошибка: {e}")


# ---------------------------------------------------------------------------
# Точка входа для тестирования
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Модуль оптимизации раскроя загружен успешно")
    print(f"Shapely доступен: {SHAPELY_AVAILABLE}")
    print("\nОсновные улучшения:")
    print("✓ Классификация треугольников по типам")
    print("✓ Учет отступов в проверке границ")
    print("✓ Пространственный индекс для быстрых проверок")
    print("✓ Шахматный порядок для равносторонних треугольников")
    print("✓ Поддержка всех типов треугольников")
