"""
Визуализация чертежей с индикацией статусов
"""

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from typing import List, Tuple, Optional, Any
from matplotlib.figure import Figure

from .models import DXFObject, ObjectStatus
from .errors import ErrorCollector
from .config import get_aci_color

def visualize_dxf_with_status_indicators(
    doc: Any,
    objects_data: List[DXFObject],
    collector: ErrorCollector,
    show_markers: bool = True,
    font_size_multiplier: float = 1.0,
    use_original_colors: bool = True,
    show_chains: bool = False
) -> Tuple[Optional[Figure], Optional[str]]:
    """
    Визуализация DXF-чертежа с индикацией статусов или цепей
    
    Args:
        doc: Документ ezdxf
        objects_data: Список объектов DXF
        collector: Коллектор ошибок
        show_markers: Показывать ли маркеры номеров
        font_size_multiplier: Множитель размера шрифта
        use_original_colors: Использовать исходные цвета из файла
        show_chains: Режим визуализации цепей
        
    Returns:
        Tuple[Figure, Optional[str]]: (фигура matplotlib, сообщение об ошибке)
    """
    try:
        fig, ax = plt.subplots(figsize=(16, 12))
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('X (мм)', fontsize=10)
        ax.set_ylabel('Y (мм)', fontsize=10)
        
        # Определяем цветовую схему для цепей
        chain_color_map = {}
        if show_chains:
            unique_chains = list(set(obj.chain_id for obj in objects_data))
            num_chains = len(unique_chains)
            
            # Генерируем уникальные цвета для каждой цепи
            colors_for_chains = plt.cm.rainbow(np.linspace(0, 1, num_chains))
            chain_color_map = {chain_id: colors_for_chains[i] 
                              for i, chain_id in enumerate(sorted(unique_chains))}
        
        # Определяем границы чертежа
        all_x, all_y = [], []
        
        # Функция для замены белого/прозрачного цвета на чёрный
        def fix_color(color_hex: str) -> str:
            """Заменяет белые и прозрачные цвета на чёрный"""
            # Список белых и прозрачных цветов
            white_colors = ['#FFFFFF', '#ffffff', '#FFF', '#fff', '#FEFEFE', '#fefefe']
            
            if color_hex.upper() in [c.upper() for c in white_colors]:
                return '#000000'  # Чёрный
            
            return color_hex
        
        # Отрисовка объектов
        for obj in objects_data:
            entity = obj.entity
            entity_type = entity.dxftype()
            
            # Определяем цвет и стиль
            if show_chains:
                color = chain_color_map.get(obj.chain_id, 'black')
                linewidth = 1.5
                alpha = 0.8
            elif use_original_colors:
                # Получаем исходный цвет и заменяем белый на чёрный
                original_color = get_aci_color(obj.original_color)
                color = fix_color(original_color)
                linewidth = 1.0
                alpha = 0.9
            else:
                # Цвета по статусам
                status_colors = {
                    ObjectStatus.NORMAL: 'black',
                    ObjectStatus.WARNING: 'orange',
                    ObjectStatus.ERROR: 'red',
                    ObjectStatus.SKIPPED: 'gray'
                }
                color = status_colors.get(obj.status, 'purple')
                linewidth = 1.5 if obj.status != ObjectStatus.NORMAL else 1.0
                alpha = 0.7
            
            # Рисуем объект
            if entity_type == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end
                ax.plot([start.x, end.x], [start.y, end.y], 
                       color=color, linewidth=linewidth, alpha=alpha)
                all_x.extend([start.x, end.x])
                all_y.extend([start.y, end.y])
            
            elif entity_type == 'CIRCLE':
                center = entity.dxf.center
                radius = entity.dxf.radius
                circle = plt.Circle((center.x, center.y), radius, 
                                   fill=False, color=color, 
                                   linewidth=linewidth, alpha=alpha)
                ax.add_patch(circle)
                all_x.extend([center.x - radius, center.x + radius])
                all_y.extend([center.y - radius, center.y + radius])
            
            elif entity_type == 'ARC':
                center = entity.dxf.center
                radius = entity.dxf.radius
                start_angle = entity.dxf.start_angle
                end_angle = entity.dxf.end_angle
                
                arc = patches.Arc((center.x, center.y), 2*radius, 2*radius,
                                 theta1=start_angle, theta2=end_angle,
                                 color=color, linewidth=linewidth, alpha=alpha)
                ax.add_patch(arc)
                all_x.append(center.x)
                all_y.append(center.y)
            
            elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
                if entity_type == 'LWPOLYLINE':
                    points = list(entity.get_points('xy'))
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                else:
                    points = list(entity.points())
                    xs = [p.x for p in points]
                    ys = [p.y for p in points]
                
                if obj.is_closed and len(xs) > 0:
                    xs.append(xs[0])
                    ys.append(ys[0])
                
                ax.plot(xs, ys, color=color, linewidth=linewidth, alpha=alpha)
                all_x.extend(xs)
                all_y.extend(ys)
            
            elif entity_type == 'SPLINE':
                try:
                    points = list(entity.flattening(0.01))
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    ax.plot(xs, ys, color=color, linewidth=linewidth, alpha=alpha)
                    all_x.extend(xs)
                    all_y.extend(ys)
                except Exception:
                    pass
            
            elif entity_type == 'ELLIPSE':
                center = entity.dxf.center
                major_axis = entity.dxf.major_axis
                ratio = entity.dxf.ratio
                
                # Упрощённая отрисовка эллипса
                import math
                a = math.sqrt(major_axis.x**2 + major_axis.y**2)
                b = a * ratio
                ellipse = patches.Ellipse((center.x, center.y), 2*a, 2*b,
                                         fill=False, color=color,
                                         linewidth=linewidth, alpha=alpha)
                ax.add_patch(ellipse)
                all_x.append(center.x)
                all_y.append(center.y)
        
        # Настройка осей (ПЕРЕД маркерами!)
        if all_x and all_y:
            margin = 50
            x_min, x_max = min(all_x), max(all_x)
            y_min, y_max = min(all_y), max(all_y)
            ax.set_xlim(x_min - margin, x_max + margin)
            ax.set_ylim(y_min - margin, y_max + margin)
        
        # Маркеры номеров объектов (ПОСЛЕ настройки осей!)
        if show_markers:
            base_font_size = 6 * font_size_multiplier
            markers_added = 0
            
            print(f"DEBUG: show_markers={show_markers}, objects_count={len(objects_data)}")
            
            for obj in objects_data:
                # Проверка наличия центра
                if obj.center is None:
                    print(f"DEBUG: Объект {obj.num} не имеет центра")
                    continue
                
                x, y = obj.center
                print(f"DEBUG: Объект {obj.num}, центр=({x:.2f}, {y:.2f})")
                
                # В режиме цепей - показываем ID цепи
                if show_chains:
                    marker_color = chain_color_map.get(obj.chain_id, 'black')
                    # Конвертируем цвет из массива в hex
                    if isinstance(marker_color, np.ndarray):
                        marker_color = tuple(marker_color)
                    label_text = f"C{obj.chain_id}"
                    markersize = 6
                else:
                    # Цвет маркера по статусу
                    if obj.status == ObjectStatus.ERROR:
                        marker_color = 'red'
                        markersize = 7
                    elif obj.status == ObjectStatus.WARNING:
                        marker_color = 'orange'
                        markersize = 6
                    else:
                        marker_color = 'blue'
                        markersize = 5
                    
                    label_text = str(obj.num)
                
                # Рисуем точку-маркер
                ax.plot(x, y, 
                       marker='o', 
                       color=marker_color, 
                       markersize=markersize, 
                       alpha=0.9, 
                       markeredgecolor='white', 
                       markeredgewidth=1.0,
                       zorder=100)  # zorder - чтобы маркеры были поверх
                
                # Добавляем текстовую метку
                ax.text(x, y, f" {label_text}", 
                       fontsize=base_font_size,
                       color=marker_color, 
                       weight='bold',
                       ha='left', 
                       va='center',
                       zorder=101,  # Текст поверх маркеров
                       bbox=dict(
                           boxstyle='round,pad=0.3', 
                           facecolor='white', 
                           alpha=0.9, 
                           edgecolor=marker_color,
                           linewidth=1.5
                       ))
                
                markers_added += 1
            
            print(f"DEBUG: Добавлено маркеров: {markers_added}")
            
            # Если маркеры не добавлены, показываем предупреждение
            if markers_added == 0:
                collector.add_warning('VISUALIZATION', 0, 
                                     "Маркеры не отображены: у объектов нет координат центра",
                                     "MarkerWarning")
        
        # Заголовок
        if show_chains:
            num_chains = len(set(obj.chain_id for obj in objects_data))
            title = f"Визуализация цепей ({num_chains} цепей)"
        else:
            title = "Визуализация чертежа"
        
        ax.set_title(title, fontsize=14, weight='bold')
        
        plt.tight_layout()
        return fig, None
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR in visualization: {error_details}")
        return None, str(e)
