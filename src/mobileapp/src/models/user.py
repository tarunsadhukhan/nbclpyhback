from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    email_id: str
    name: str
    password: str
    user_id: Optional[int]            = None
    refresh_token: Optional[str]      = None
    active: int                       = 1
    updated_by_con_user: int          = 0
    updated_date_time: Optional[str]  = None
