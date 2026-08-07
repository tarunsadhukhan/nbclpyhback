from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Department:
    name: str
    id: Optional[int] = None


@dataclass
class Shift:
    name: str
    start_time: str
    end_time: str
    id: Optional[int] = None


@dataclass
class Occupation:
    name: str
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class Company:
    co_name: str
    co_id: Optional[int] = None
    co_logo: Optional[str] = None


@dataclass
class Branch:
    co_id: int
    br_name: str
    br_id: Optional[int] = None
