import pandas as pd
import logging
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

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
            'Тип объекта': self.entity_type, '№ объекта': self.entity_num,
            'Описание': self.description, 'Класс ошибки': self.error_class,
            'Серьёзность': self.severity.value
        }

class ErrorCollector:
    def __init__(self):
        self.issues = []
        self.object_issues = {}
    
    def add_issue(self, issue, object_num=0):
        self.issues.append(issue)
        if object_num > 0:
            if object_num not in self.object_issues: self.object_issues[object_num] = []
            self.object_issues[object_num].append(issue)
    
    def add_error(self, t, n, m, c=""): self.add_issue(ProcessingIssue(t,n,m,c,ErrorSeverity.ERROR), n)
    def add_warning(self, t, n, m, c=""): self.add_issue(ProcessingIssue(t,n,m,c,ErrorSeverity.WARNING), n)
    def add_skipped(self, t, n, r): self.add_issue(ProcessingIssue(t,n,r,"",ErrorSeverity.SKIPPED), n)
    def add_info(self, t, n, m): self.add_issue(ProcessingIssue(t,n,m,"",ErrorSeverity.INFO), n)

    @property
    def has_issues(self): return bool(self.issues)
    @property
    def has_errors(self): return any(i.severity == ErrorSeverity.ERROR for i in self.issues)

    def get_all_as_dataframe(self):
        return pd.DataFrame([i.to_dict() for i in self.issues]) if self.issues else pd.DataFrame()