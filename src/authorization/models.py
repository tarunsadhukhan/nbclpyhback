from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str
    logintype: str
    rememberMe: bool = False

