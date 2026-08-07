from pydantic import BaseModel, EmailStr
from typing import List, Optional
# ✅ Country Schema for API Response
class CountrySchema(BaseModel):
    country_id: int
    country_name: str

    class Config:
        from_attributes = True
        
class CountryResponseSchema(BaseModel):
    data: List[CountrySchema]  # ✅ Ensures `{ "data": [...] }`
        
        
class StateSchema(BaseModel):
    state_id: int
    state_name: str

    class Config:
        from_attributes = True


class StateResponseSchema(BaseModel):
    data: List[StateSchema]

class StatusSchema(BaseModel):
    con_status_id: int
    con_status_name: str
   
    class Config:
        from_attributes = True


class StatusResponseSchema(BaseModel):
    data: List[StatusSchema]
    
    
class ModuleSchema(BaseModel):
    con_module_id: int
    con_module_name: str
   
    class Config:
        from_attributes = True


class ModuleResponseSchema(BaseModel):
    data: List[ModuleSchema]    
  
    
class ContactFormSchema(BaseModel):
    name: str
    address: str
    pincode: str
    state: int
    country: int
    email: str
    mobile: str
    contactPerson: str
    orgshrname: str
    message: str
    modules: List[str]
    custommodules: str
    
    class Config:
        from_attributes = True  # ✅ Ensures compatibility with DB models    