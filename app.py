"""
Анализатор Чертежей CAD Pro v24.0
Главный файл приложения Streamlit.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tempfile
import warnings
from typing import List, Dict, Any
from collections import defaultdict

import pandas as pd
import streamlit as st

# Локальные импорты
from dxf_analyzer.config import (
    install_dependencies, MAX_FILE_SIZE_MB, MIN_LENGTH,
    ZERO_LENGTH_TYPES, SILENT_SKIP_TYPES, get_color_name, get_aci_color
)
from dxf_analyzer.models import DXFObject, ObjectStatus
from dxf_analyzer.errors import ErrorCollector
from dxf_analyzer.utils import get_layer_info, calc_entity_safe
from dxf_analyzer.calculators import calculators
from dxf_analyzer.geometry import (
    get_entity_center, check_is_closed,
    count_piercings_advanced, get_piercing_statistics
)
from dxf_analyzer.visualization import visualize_dxf_with_status_indicators
from dxf_analyzer.ui_components import show_error_report

# Автоустановка зависимостей
install_dependencies()

# Импорт ezdxf после установки
try:
    import ezdxf
except ImportError as e:
    st.error(f"❌ Ошибка загрузки ezdxf: {e}")
    st.info("🔄 Попробуйте перезагрузить страницу")
    st.stop()

warnings.filterwarnings('ignore')

# ==================== НАСТРОЙКА СТРАНИЦЫ ====================
st.set_page_config(
    page_title="Анализатор Чертежей CAD Pro v24.0",
    page_icon="📐",
    layout="wide"
)

st.title("📐 Анализатор Чертежей CAD Pro v24.0")
st.markdown("**Профессиональный расчет длины реза для станков ЧПУ и лазерной резки**")

# ==================== СПРАВКА ====================
with st.expander("ℹ️ Информация о подсчёте врезок"):
    st.markdown("""
    ### 📍 Как считаются врезки (точки прожига):
    
    **Что такое врезка:**
    - Это точка, где лазер включается для начала резки
    - Каждая **связанная цепь объектов** = **1 врезка**
    
    **Примеры:**
    - 1 окружность = 1 врезка ✅
    - 4 LINE, образующих прямоугольник = 1 врезка ✅ (если концы совпадают)
    - 4 несвязанных LINE = 4 врезки ✅
    - 2 дуги, образующих окружность = 1 врезка ✅ (если зазор < допуска)
    
    **Алгоритм:**
    1. Замкнутые объекты (CIRCLE, замкнутые полилинии) = изолированные цепи
    2. Для открытых объектов строим граф связности по близости концов
    3. Используется допуск 0.1 мм (настраивается)
    4. Каждая найденная цепь = 1 врезка
    """)

with st.expander("ℹ️ Информация о цветах"):
    st.markdown("""
    ### Режимы отображения чертежа:
    
    **Режим 1: Исходные цвета из файла (по умолчанию)**
    - Линии отображаются теми цветами, которые установлены в DXF файле
    - Ошибки выделяются красной обводкой поверх исходного цвета
    
    **Режим 2: Индикация ошибок**
    - Чёрный = Нормальные объекты (учтены)
    - Оранжевый = Предупреждения (учтены с коррекцией)
    - Красный = Ошибки (исключены)
    - Серый = Пропущены
    
    **Режим 3: Визуализация цепей (НОВОЕ v24.0)**
    - Каждая цепь выделена уникальным цветом
    - Помогает увидеть связанные объекты
    """)

st.markdown("---")

# ==================== ЗАГРУЗКА ФАЙЛА ====================
uploaded_file = st.file_uploader("📂 Загрузите чертеж в формате DXF", type=["dxf"])

if uploaded_file is not None:
    file_size_mb = uploaded_file.size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        st.error(f"❌ Файл слишком большой: {file_size_mb:.1f} МБ (максимум: {MAX_FILE_SIZE_MB} МБ)")
        st.stop()
    
    collector = ErrorCollector()
    
    with st.spinner('⏳ Обработка чертежа...'):
        try:
            # Сохраняем во временный файл
            with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
                tmp.write(uploaded_file.getbuffer())
                temp_path = tmp.name
            
            # Читаем DXF
            try:
                doc = ezdxf.readfile(temp_path)
                dxf_version = doc.dxfversion
                if dxf_version < 'AC1018':
                    collector.add_warning('FILE', 0, f"Старая версия DXF: {dxf_version}", "DXFVersionWarning")
                collector.add_info('FILE', 0, f"Файл загружен. Версия: {dxf_version}")
            except ezdxf.DXFError as e:
                collector.add_error('FILE', 0, f"Ошибка чтения DXF: {e}", "DXFError")
                show_error_report(collector)
                st.stop()
            except Exception as e:
                collector.add_error('FILE', 0, f"Ошибка: {e}", type(e).__name__)
                show_error_report(collector)
                st.stop()
            finally:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            
            # ==================== АНАЛИЗ ====================
            msp = doc.modelspace()
            objects_data: List[DXFObject] = []
            stats: Dict[str, Dict[str, Any]] = {}
            color_stats: Dict[int, Dict[str, Any]] = {}
            total_length = 0.0
            skipped_types = set()
            
            real_object_num = calc_object_num = 0
            
            for entity in msp:
                entity_type = entity.dxftype()
                real_object_num += 1
                layer, color = get_layer_info(entity)
                
                if entity_type not in calculators:
                    if entity_type not in SILENT_SKIP_TYPES:
                        skipped_types.add(entity_type)
                    continue
                
                length, status, issue_desc = calc_entity_safe(
                    entity_type, entity, real_object_num, calculators, collector
                )
                
                if length < MIN_LENGTH:
                    if entity_type not in ZERO_LENGTH_TYPES:
                        collector.add_skipped(entity_type, real_object_num, f"Нулевая длина: {length:.6f}")
                    continue
                
                calc_object_num += 1
                center = get_entity_center(entity)
                is_closed = check_is_closed(entity)
                
                dxf_obj = DXFObject(
                    num=calc_object_num, real_num=real_object_num,
                    entity_type=entity_type, length=length, center=center,
                    entity=entity, layer=layer, color=color, original_color=color,
                    status=status, original_length=length,
                    issue_description=issue_desc, is_closed=is_closed, chain_id=-1
                )
                objects_data.append(dxf_obj)
                
                # Статистика по типам
                if entity_type not in stats:
                    stats[entity_type] = {'count': 0, 'length': 0.0, 'items': []}
                stats[entity_type]['count'] += 1
                stats[entity_type]['length'] += length
                stats[entity_type]['items'].append({'num': calc_object_num, 'length': length})
                
                # Статистика по цветам
                if color not in color_stats:
                    color_stats[color] = {
                        'count': 0, 'length': 0.0,
                        'color_name': get_color_name(color),
                        'hex_color': get_aci_color(color)
                    }
                color_stats[color]['count'] += 1
                color_stats[color]['length'] += length
                
                total_length += length
            
            # Подсчёт врезок
            piercing_count, piercing_details = count_piercings_advanced(objects_data, collector)
            
            # ==================== ВЫВОД ====================
            show_error_report(collector)
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета")
                if skipped_types:
                    st.info(f"Пропущено: {', '.join(sorted(skipped_types))}")
            else:
                if collector.has_errors:
                    st.success(f"✅ Обработано: **{len(objects_data)}** объектов (🔴 {len(collector.errors)} ошибок)")
                else:
                    st.success(f"✅ Обработано: **{len(objects_data)}** объектов")
                
                # Итоговые метрики
                st.markdown("### 📏 Итоговая длина реза:")
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric("Миллиметры", f"{total_length:.2f}")
                with col2:
                    st.metric("Сантиметры", f"{total_length/10:.2f}")
                with col3:
                    st.metric("Метры", f"{total_length/1000:.4f}")
                with col4:
                    st.metric("Объектов", f"{len(objects_data)}")
                with col5:
                    st.metric("🔵 Врезок (цепей)", f"{piercing_count}")
                
                # Статистика врезок
                st.markdown("### 📍 Статистика врезок (анализ связности):")
                col_p1, col_p2, col_p3, col_p4, col_p5 = st.columns(5)
                
                with col_p1:
                    st.metric("🔵 Всего цепей", piercing_details['total'],
                             help="Количество связанных групп объектов")
                with col_p2:
                    st.metric("🔴 Замкнутые", piercing_details['closed_objects'],
                             help="Полные контуры")
                with col_p3:
                    st.metric("🔗 Открытые группы", piercing_details['open_chains'],
                             help="Несколько связанных открытых объектов")
                with col_p4:
                    st.metric("➡️ Изолированные", piercing_details['isolated_objects'],
                             help="Одиночные открытые объекты")
                with col_p5:
                    st.metric("⚙️ Допуск", f"{piercing_details['tolerance_used']} мм",
                             help="Точки ближе этого значения считаются соединёнными")
                
                # Детали цепей
                if piercing_details['chains']:
                    with st.expander(f"🔍 Детали цепей ({len(piercing_details['chains'])} шт.)", expanded=False):
                        chains_rows = []
                        for chain in piercing_details['chains']:
                            emoji = {'closed': '🔴', 'open': '🔗', 'isolated': '➡️'}.get(chain['type'], '❓')
                            chains_rows.append({
                                'ID': chain['chain_id'],
                                'Тип': f"{emoji} {chain['type']}",
                                'Объектов': chain['objects_count'],
                                'Номера объектов': ', '.join(map(str, chain['objects'])),
                                'Типы': ', '.join(chain['entity_types']),
                                'Длина (мм)': round(chain['total_length'], 2)
                            })
                        
                        df_chains = pd.DataFrame(chains_rows)
                        st.dataframe(df_chains, use_container_width=True, hide_index=True)
                        st.download_button(
                            label="📥 Скачать детали цепей (CSV)",
                            data=df_chains.to_csv(index=False, encoding='utf-8-sig'),
                            file_name="chains_details.csv", mime="text/csv"
                        )
                
                st.markdown("---")
                
                # Спецификации
                col_left, col_right = st.columns([1, 1.5])
                
                with col_left:
                    st.markdown("### 📊 Сводная спецификация по типам")
                    summary_rows = [
                        {
                            'Тип': etype,
                            'Кол-во': stats[etype]['count'],
                            'Длина (мм)': round(stats[etype]['length'], 2),
                            'Средняя': round(stats[etype]['length'] / stats[etype]['count'], 2)
                        }
                        for etype in sorted(stats.keys())
                    ]
                    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
                    
                    st.markdown("### 🎨 Статистика по цветам")
                    color_rows = [
                        {
                            '🟦 Цвет': f"<span style='color: {c['hex_color']}'>●</span> {c['color_name']}",
                            'Код': cid,
                            'Кол-во': c['count'],
                            'Длина (мм)': round(c['length'], 2)
                        }
                        for cid, c in sorted(color_stats.items())
                    ]
                    if color_rows:
                        st.markdown(pd.DataFrame(color_rows).to_html(escape=False), unsafe_allow_html=True)
                
                with col_right:
                    st.markdown("### 🎨 Чертеж с цветовой индикацией")
                    
                    display_mode = st.radio(
                        "Режим отображения:",
                        options=["Исходные цвета", "Индикация ошибок", "Визуализация цепей"],
                        horizontal=True
                    )
                    
                    use_original_colors = display_mode == "Исходные цвета"
                    show_chains = display_mode == "Визуализация цепей"
                    
                    show_markers = st.checkbox("🔴 Показать маркеры", value=True)
                    font_size_multiplier = st.slider(
                        "📏 Размер шрифта", min_value=0.5, max_value=3.0,
                        value=1.0, step=0.1
                    ) if show_markers else 1.0
                    
                    with st.spinner('Генерация визуализации...'):
                        fig, error_msg = visualize_dxf_with_status_indicators(
                            doc, objects_data, collector,
                            show_markers, font_size_multiplier,
                            use_original_colors, show_chains
                        )
                        
                        if fig is not None:
                            st.pyplot(fig, use_container_width=True)
                            if show_chains:
                                st.info(f"💡 Каждый цвет = отдельная цепь. Найдено {piercing_count} цепей.")
                        else:
                            st.error(f"❌ {error_msg}" if error_msg else "❌ Не удалось создать визуализацию")
        
        except Exception as e:
            collector.add_error('SYSTEM', 0, f"Критическая ошибка: {e}", type(e).__name__)
            show_error_report(collector)
            
            import traceback
            with st.expander("🔍 Трассировка ошибки"):
                st.code(traceback.format_exc())

else:
    st.info("👈 Загрузите DXF-чертеж для начала")
    st.markdown("""
    ### 📝 О версии v24.0:
    
    **ГЛАВНОЕ УЛУЧШЕНИЕ:**
    - ✅ **ПРАВИЛЬНЫЙ подсчёт врезок с анализом связности**
    - ✅ Алгоритм находит связанные объекты (граф смежности)
    - ✅ Прямоугольник из 4 LINE = 1 врезка (не 4!)
    - ✅ Визуализация цепей разными цветами
    """)

# ==================== ФУТЕР ====================
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v24.0 | Лицензия MIT | АНАЛИЗ СВЯЗНОСТИ КОНТУРОВ
</div>
""", unsafe_allow_html=True)
