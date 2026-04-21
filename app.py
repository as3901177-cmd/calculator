import streamlit as st
import ezdxf
import tempfile
import os
import pandas as pd
import traceback
from config import *
from models import ErrorCollector, ObjectStatus, DXFObject, ErrorSeverity
from geometry import (
    calculators, calc_entity_safe, get_entity_center, 
    get_layer_info, check_is_closed, count_piercings_advanced
)
from visuals import visualize_dxf_with_status_indicators

# ==================== UI ФУНКЦИИ ====================

def show_error_report(collector: ErrorCollector):
    if not collector.has_issues:
        st.success("✅ Обработка завершена без ошибок")
        return
    
    if collector.has_errors:
        st.error(f"⚠️ Обнаружены ошибки: {collector.get_summary()}")
    else:
        st.warning(f"⚠️ Есть предупреждения: {collector.get_summary()}")
    
    with st.expander(f"🔍 Подробный отчёт ({collector.total_issues})", expanded=False):
        tabs = st.tabs(["🔴 Ошибки", "🟡 Предупреждения", "📋 Весь лог"])
        
        with tabs[0]:
            df_err = pd.DataFrame([i.to_dict() for i in collector.errors])
            st.dataframe(df_err, use_container_width=True, hide_index=True)
            
        with tabs[1]:
            df_warn = pd.DataFrame([i.to_dict() for i in collector.warnings])
            st.dataframe(df_warn, use_container_width=True, hide_index=True)
            
        with tabs[2]:
            st.dataframe(collector.get_all_as_dataframe(), use_container_width=True, hide_index=True)

# ==================== ГЛАВНЫЙ ИНТЕРФЕЙС ====================

st.set_page_config(page_title="Анализатор CAD Pro v24.0", layout="wide")
st.title("📐 Анализатор Чертежей CAD Pro v24.0")

uploaded_file = st.file_uploader("📂 Загрузите DXF файл", type=["dxf"])

if uploaded_file:
    collector = ErrorCollector()
    
    with st.spinner('⏳ Чтение файла...'):
        try:
            # Сохранение во временный файл
            with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
                tmp.write(uploaded_file.getbuffer())
                temp_path = tmp.name
            
            doc = ezdxf.readfile(temp_path)
            msp = doc.modelspace()
            
            objects_data = []
            total_length = 0.0
            stats = {}
            color_stats = {}
            
            real_num = 0
            calc_num = 0
            
            # Основной цикл обработки объектов
            for entity in msp:
                real_num += 1
                etype = entity.dxftype()
                
                if etype not in calculators:
                    continue
                
                length, status, issue_desc = calc_entity_safe(
                    etype, entity, real_num, calculators, collector
                )
                
                if length < MIN_LENGTH and etype not in ('POINT', 'TEXT'):
                    continue
                
                calc_num += 1
                layer, color = get_layer_info(entity)
                
                dxf_obj = DXFObject(
                    num=calc_num,
                    real_num=real_num,
                    entity_type=etype,
                    length=length,
                    center=get_entity_center(entity),
                    entity=entity,
                    layer=layer,
                    color=color,
                    status=status,
                    issue_description=issue_desc,
                    is_closed=check_is_closed(entity)
                )
                
                objects_data.append(dxf_obj)
                
                # Сбор статистики
                if etype not in stats: stats[etype] = {'count': 0, 'length': 0.0}
                stats[etype]['count'] += 1
                stats[etype]['length'] += length
                
                if color not in color_stats:
                    color_stats[color] = {'count': 0, 'length': 0.0, 'name': get_color_name(color), 'hex': get_aci_color(color)}
                color_stats[color]['count'] += 1
                color_stats[color]['length'] += length
                
                if status != ObjectStatus.ERROR:
                    total_length += length

            # Анализ врезок
            p_count, p_details = count_piercings_advanced(objects_data, collector)
            
            # ВЫВОД РЕЗУЛЬТАТОВ
            show_error_report(collector)
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Общая длина (мм)", f"{total_length:.2f}")
            col2.metric("Метры", f"{total_length/1000:.3f}")
            col3.metric("Объектов", len(objects_data))
            col4.metric("Врезок", p_count)
            
            st.markdown("---")
            
            view_col, data_col = st.columns([1.5, 1])
            
            with view_col:
                st.subheader("🎨 Визуализация")
                mode = st.radio("Режим:", ["Исходные цвета", "Индикация ошибок", "Цепи"], horizontal=True)
                show_m = st.checkbox("Показать номера объектов", value=True)
                
                fig, err = visualize_dxf_with_status_indicators(
                    doc, objects_data, collector,
                    show_markers=show_m,
                    use_original_colors=(mode == "Исходные цвета"),
                    show_chains=(mode == "Цепи")
                )
                if fig: st.pyplot(fig)
                else: st.error(err)
                
            with data_col:
                st.subheader("📊 Спецификация")
                st.table(pd.DataFrame([
                    {'Тип': k, 'Кол-во': v['count'], 'Длина (мм)': round(v['length'], 2)}
                    for k, v in stats.items()
                ]))
                
                st.subheader("🌈 По цветам")
                for c_id, c_info in color_stats.items():
                    st.markdown(
                        f"<span style='color:{c_info['hex']}'>●</span> "
                        f"**{c_info['name']}**: {c_info['count']} шт, {c_info['length']:.1f} мм", 
                        unsafe_allow_html=True
                    )

            os.remove(temp_path)

        except Exception as e:
            st.error(f"Критическая ошибка: {e}")
            st.code(traceback.format_exc())

else:
    st.info("👈 Загрузите DXF файл, чтобы начать расчет")