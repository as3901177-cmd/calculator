"""
Сбор и обработка ошибок при обработке DXF.
"""

import pandas as pd
from typing import List, Dict
from .config import logger
from .models import ProcessingIssue, ErrorSeverity


class ErrorCollector:
    """
    Собирает ошибки во время обработки.
    Отслеживает какие объекты имели проблемы.
    """
    
    def __init__(self):
        self.issues: List[ProcessingIssue] = []
        self.object_issues: Dict[int, List[ProcessingIssue]] = {}
    
    def add_issue(self, issue: ProcessingIssue, object_num: int = 0):
        """Добавляет проблему."""
        self.issues.append(issue)
        
        if object_num > 0:
            if object_num not in self.object_issues:
                self.object_issues[object_num] = []
            self.object_issues[object_num].append(issue)
        
        log_methods = {
            ErrorSeverity.ERROR: logger.error,
            ErrorSeverity.WARNING: logger.warning,
        }
        log_method = log_methods.get(issue.severity, logger.info)
        log_method(f"[{issue.entity_type}] #{issue.entity_num}: {issue.description}")
    
    def add_error(self, entity_type: str, entity_num: int, 
                  error_msg: str, error_class: str = ""):
        """Добавляет критическую ошибку."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=error_msg,
            error_class=error_class,
            severity=ErrorSeverity.ERROR
        ), object_num=entity_num)
    
    def add_warning(self, entity_type: str, entity_num: int, 
                    warning_msg: str, error_class: str = ""):
        """Добавляет предупреждение."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=warning_msg,
            error_class=error_class,
            severity=ErrorSeverity.WARNING
        ), object_num=entity_num)
    
    def add_skipped(self, entity_type: str, entity_num: int, reason: str):
        """Добавляет пропущенный объект."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=reason,
            severity=ErrorSeverity.SKIPPED
        ), object_num=entity_num)
    
    def add_info(self, entity_type: str, entity_num: int, info_msg: str):
        """Добавляет информационное сообщение."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=info_msg,
            severity=ErrorSeverity.INFO
        ), object_num=entity_num)
    
    def has_issue_for_object(self, object_num: int, 
                             severity: ErrorSeverity = None) -> bool:
        """Проверяет наличие проблемы для объекта."""
        if object_num not in self.object_issues:
            return False
        if severity is None:
            return len(self.object_issues[object_num]) > 0
        return any(i.severity == severity for i in self.object_issues[object_num])
    
    def get_issues_for_object(self, object_num: int) -> List[ProcessingIssue]:
        """Получает все проблемы для объекта."""
        return self.object_issues.get(object_num, [])
    
    @property
    def errors(self) -> List[ProcessingIssue]:
        """Возвращает только ошибки."""
        return [i for i in self.issues if i.severity == ErrorSeverity.ERROR]
    
    @property
    def warnings(self) -> List[ProcessingIssue]:
        """Возвращает только предупреждения."""
        return [i for i in self.issues if i.severity == ErrorSeverity.WARNING]
    
    @property
    def skipped(self) -> List[ProcessingIssue]:
        """Возвращает только пропущённые."""
        return [i for i in self.issues if i.severity == ErrorSeverity.SKIPPED]
    
    @property
    def has_issues(self) -> bool:
        """Есть ли какие-либо проблемы."""
        return bool(self.issues)
    
    @property
    def has_errors(self) -> bool:
        """Есть ли критические ошибки."""
        return bool(self.errors)
    
    @property
    def total_issues(self) -> int:
        """Общее количество проблем."""
        return len(self.issues)
    
    def get_all_as_dataframe(self) -> pd.DataFrame:
        """Возвращает все проблемы единым DataFrame."""
        if not self.issues:
            return pd.DataFrame()
        return pd.DataFrame([issue.to_dict() for issue in self.issues])
    
    def get_summary(self) -> str:
        """Краткая сводка по проблемам."""
        parts = []
        if self.errors:
            parts.append(f"🔴 Ошибок: {len(self.errors)}")
        if self.warnings:
            parts.append(f"🟡 Предупреждений: {len(self.warnings)}")
        if self.skipped:
            parts.append(f"⚪ Пропущено: {len(self.skipped)}")
        return " | ".join(parts) if parts else "✅ Проблем не обнаружено"
    
    def get_summary_with_percent(self, total_objects: int) -> str:
        """Сводка с процентами от общего количества."""
        if total_objects == 0:
            return self.get_summary()
        
        parts = []
        if self.errors:
            pct = (len(self.errors) / total_objects) * 100
            parts.append(f"🔴 Ошибок: {len(self.errors)} ({pct:.1f}%)")
        if self.warnings:
            pct = (len(self.warnings) / total_objects) * 100
            parts.append(f"🟡 Предупреждений: {len(self.warnings)} ({pct:.1f}%)")
        if self.skipped:
            pct = (len(self.skipped) / total_objects) * 100
            parts.append(f"⚪ Пропущено: {len(self.skipped)} ({pct:.1f}%)")
        
        return " | ".join(parts) if parts else "✅ Проблем не обнаружено"