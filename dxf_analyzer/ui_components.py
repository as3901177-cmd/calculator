"""
Компоненты пользовательского интерфейса Streamlit
"""

import streamlit as st
import pandas as pd
from typing import Optional

from .errors import ErrorCollector

def show_error_report(collector: ErrorCollector):
    """
    Отображение отчёта об ошибках и предупреждениях
    
    Args:
        collector: Коллектор ошибок
    """
    summary = collector.get_summary()
    
    # Информационные сообщения
    if collector.info:
        with st.expander(f"ℹ️ Информация ({len(collector.info)})", expanded=False):
            for record in collector.info:
                st.info(f"**{record.entity_type}**: {record.message}")
    
    # Ошибки
    if collector.has_errors:
        with st.expander(f"🔴 Ошибки ({len(collector.errors)})", expanded=True):
            error_data = [
                {
                    'Номер': rec.entity_num,
                    'Тип': rec.entity_type,
                    'Ошибка': rec.message,
                    'Класс': rec.error_type
                }
                for rec in collector.errors
            ]
            st.dataframe(pd.DataFrame(error_data), use_container_width=True, hide_index=True)
    
    # Предупреждения
    if collector.has_warnings:
        with st.expander(f"⚠️ Предупреждения ({len(collector.warnings)})", expanded=False):
            warning_data = [
                {
                    'Номер': rec.entity_num,
                    'Тип': rec.entity_type,
                    'Предупреждение': rec.message
                }
                for rec in collector.warnings
            ]
            st.dataframe(pd.DataFrame(warning_data), use_container_width=True, hide_index=True)
    
    # Пропущенные объекты
    if collector.skipped:
        with st.expander(f"⏭️ Пропущено ({len(collector.skipped)})", expanded=False):
            skipped_data = [
                {
                    'Номер': rec.entity_num,
                    'Тип': rec.entity_type,
                    'Причина': rec.message
                }
                for rec in collector.skipped
            ]
            st.dataframe(pd.DataFrame(skipped_data), use_container_width=True, hide_index=True)