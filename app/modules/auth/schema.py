from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

    model_config = {
        "json_schema_extra": {
            "example": {"email": "user@example.com", "password": "your_password"}
        }
    }


class RefreshRequest(BaseModel):
    refreshToken: str

    model_config = {"json_schema_extra": {"example": {"refreshToken": "jwt"}}}


class LogoutRequest(BaseModel):
    refreshToken: str

    model_config = {"json_schema_extra": {"example": {"refreshToken": "jwt"}}}


class AuthTokens(BaseModel):
    accessToken: str
    refreshToken: str

    model_config = {
        "json_schema_extra": {"example": {"accessToken": "jwt", "refreshToken": "jwt"}}
    }


class LogoutResponse(BaseModel):
    success: bool = True
