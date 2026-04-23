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


# ==================== ПРОДВИНУТЫЙ АЛГОРИТМ С АДАПТИВНОЙ СТРАТЕГИЕЙ ====================

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
