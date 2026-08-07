from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr

class UserBase(BaseModel):
    email_id: str
    name: str
    active: bool = True
    refresh_token: Optional[str] = None

class UserCreate(UserBase):
    password: str

# class UserResponse(UserBase):
#     user_id: int
    
#     class Config:
#         orm_mode = True

class BranchRoleMapping(BaseModel):
    company_id: int
    branch_id: int
    role_id: str

class UserCreatePortal(BaseModel):
    name: str 
    user_name: str
    password: str
    is_active: bool
    branch_roles: List[BranchRoleMapping]