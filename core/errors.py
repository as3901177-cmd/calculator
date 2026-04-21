from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class ErrorSeverity(Enum):
    ERROR = "🔴 Ошибка"
    WARNING = "🟡 Предупреждение"
    SKIPPED = "⚪ Пропущен"
    INFO = "🔵 Информация"

class ObjectStatus(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"

@dataclass
class DXFObject:
    num: int
    real_num: int
    entity_type: str
    length: float
    center: Any
    entity: Any = None
    layer: str = ""
    color: int = 256
    original_color: int = 256
    status: ObjectStatus = ObjectStatus.NORMAL
    original_length: float = 0.0
    issue_description: str = ""
    is_closed: bool = False
    chain_id: int = -1

@dataclass
class ProcessingIssue:
    entity_type: str
    entity_num: int
    description: str
    error_class: str = ""
    severity: ErrorSeverity = ErrorSeverity.ERROR
    
    def to_dict(self) -> Dict[str, str]:
        return {
            'Тип объекта': self.entity_type,
            '№ объекта': self.entity_num,
            'Описание': self.description,
            'Класс ошибки': self.error_class,
            'Серьёзность': self.severity.value
        }

class ErrorCollector:
    def __init__(self):
        self.issues: List[ProcessingIssue] = []
        self.object_issues: Dict[int, List[ProcessingIssue]] = {}
    
    def add_issue(self, issue: ProcessingIssue, object_num: int = 0):
        self.issues.append(issue)
        if object_num > 0:
            if object_num not in self.object_issues:
                self.object_issues[object_num] = []
            self.object_issues[object_num].append(issue)
    
    def add_error(self, entity_type, entity_num, error_msg, error_class=""):
        self.add_issue(ProcessingIssue(entity_type, entity_num, error_msg, error_class, ErrorSeverity.ERROR), entity_num)
    
    def add_warning(self, entity_type, entity_num, warning_msg, error_class=""):
        self.add_issue(ProcessingIssue(entity_type, entity_num, warning_msg, error_class, ErrorSeverity.WARNING), entity_num)
    
    def add_skipped(self, entity_type, entity_num, reason):
        self.add_issue(ProcessingIssue(entity_type, entity_num, reason, "", ErrorSeverity.SKIPPED), entity_num)

    def add_info(self, entity_type, entity_num, info_msg):
        self.add_issue(ProcessingIssue(entity_type, entity_num, info_msg, "", ErrorSeverity.INFO), entity_num)

    @property
    def errors(self): return [i for i in self.issues if i.severity == ErrorSeverity.ERROR]
    @property
    def warnings(self): return [i for i in self.issues if i.severity == ErrorSeverity.WARNING]
    @property
    def skipped(self): return [i for i in self.issues if i.severity == ErrorSeverity.SKIPPED]
    @property
    def has_issues(self): return bool(self.issues)
    @property
    def has_errors(self): return bool(self.errors)
    @property
    def total_issues(self): return len(self.issues)

    def get_all_as_dataframe(self):
        return pd.DataFrame([issue.to_dict() for issue in self.issues]) if self.issues else pd.DataFrame()

    def get_summary(self) -> str:
        parts = []
        if self.errors: parts.append(f"🔴 Ошибок: {len(self.errors)}")
        if self.warnings: parts.append(f"🟡 Предупреждений: {len(self.warnings)}")
        if self.skipped: parts.append(f"⚪ Пропущено: {len(self.skipped)}")
        return " | ".join(parts) if parts else "✅ Проблем не обнаружено"