from dataclasses import dataclass
from typing import Optional


@dataclass
class Attendance:
    eb_id: int
    attendance_date: str                      # YYYY-MM-DD
    attendance_source: str              = 'Manual'  # 'Face' | 'Manual'
    attendance_type: str                = 'R'       # R=Regular, O=OT, C=Cash
    attendance_mark: str                = 'P'
    status_id: str                      = '3'
    is_active: int                      = 1
    branch_id: Optional[int]            = None
    spell: Optional[str]                = None
    spell_hours: float                  = 0.0
    worked_department_id: Optional[int] = None
    worked_designation_id: Optional[int] = None
    working_hours: float                = 0.0
    idle_hours: float                   = 0.0
    daily_atten_id: Optional[int]       = None
    entry_time: Optional[str]           = None
    exit_time: Optional[str]            = None
