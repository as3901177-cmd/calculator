"""
Компоненты интерфейса Streamlit для отображения отчётов.
"""

import streamlit as st
import pandas as pd
from .errors import ErrorCollector


def show_error_report(collector: ErrorCollector):
    """Показывает отчёт об ошибках в Streamlit UI."""
    if not collector.has_issues:
        st.success("✅ Обработка завершена без ошибок")
        return
    
    if collector.has_errors:
        st.error(f"⚠️ Обнаружены ошибки при обработке: {collector.get_summary()}")
    else:
        st.warning(f"⚠️ Обработка завершена с предупреждениями: {collector.get_summary()}")
    
    with st.expander(f"🔍 Подробный отчёт о проблемах ({collector.total_issues} записей)", expanded=False):
        tab_labels = []
        if collector.errors:
            tab_labels.append(f"🔴 Ошибки ({len(collector.errors)})")
        if collector.warnings:
            tab_labels.append(f"🟡 Предупреждения ({len(collector.warnings)})")
        if collector.skipped:
            tab_labels.append(f"⚪ Пропущено ({len(collector.skipped)})")
        tab_labels.append("📋 Все проблемы")
        
        if not tab_labels:
            st.info("✅ Проблем не обнаружено")
            return
        
        tabs = st.tabs(tab_labels)
        tab_idx = 0
        
        if collector.errors:
            with tabs[tab_idx]:
                st.markdown("**Критические ошибки** — объекты НЕ учтены в расчёте:")
                st.dataframe(pd.DataFrame([i.to_dict() for i in collector.errors]),
                           use_container_width=True, hide_index=True)
                st.info("💡 Эти объекты исключены из итоговой длины реза.")
            tab_idx += 1
        
        if collector.warnings:
            with tabs[tab_idx]:
                st.markdown("**Предупреждения** — объекты включены в расчёт с коррекцией:")
                st.dataframe(pd.DataFrame([i.to_dict() for i in collector.warnings]),
                           use_container_width=True, hide_index=True)
                st.warning("💡 Эти объекты включены в расчёт с коррекцией значений.")
            tab_idx += 1
        
        if collector.skipped:
            with tabs[tab_idx]:
                st.markdown("**Пропущенные объекты** — не входят в расчёт:")
                st.dataframe(pd.DataFrame([i.to_dict() for i in collector.skipped]),
                           use_container_width=True, hide_index=True)
                st.info("💡 Эти типы объектов не поддерживаются или имеют нулевую длину.")
            tab_idx += 1
        
        with tabs[tab_idx]:
            st.markdown("**Полный лог всех проблем:**")
            df_all = collector.get_all_as_dataframe()
            if not df_all.empty:
                st.dataframe(df_all, use_container_width=True, hide_index=True)
                st.download_button(label="📥 Скачать лог ошибок (CSV)",
                                  data=df_all.to_csv(index=False, encoding='utf-8-sig'),
                                  file_name="error_log.csv", mime="text/csv")
        
        if collector.has_errors:
            st.markdown("---")
            st.markdown("### 📊 Влияние на результат расчёта")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Объектов с ошибками", len(collector.errors))
            with col2:
                st.metric("Предупреждений", len(collector.warnings))
            st.warning(f"⚠️ **Итоговая длина реза может быть занижена** "
                      f"из-за {len(collector.errors)} объектов с ошибками.")