from dataclasses import dataclass
from typing import Optional


@dataclass
class Employee:
    emp_code: str
    name: str
    department_id: Optional[int]  = None
    designation_id: Optional[int] = None
    shift_id: Optional[int]       = None
    face_embedding: Optional[str] = None   # JSON-encoded list
    photo_html: Optional[str]     = None
    id: Optional[int]             = None
    is_active: int                = 1
    created_at: Optional[str]     = None
