from typing import Annotated

from pydantic import BaseModel, EmailStr, Field

from app.core.security import MIN_PASSWORD_LENGTH


class LoginIn(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=200)]


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str


class ChangePasswordIn(BaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=200)]
    new_password: Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)]
