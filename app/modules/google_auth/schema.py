from pydantic import BaseModel


class GoogleCallbackRequest(BaseModel):
    code: str


class GoogleAuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    is_new_user: bool
