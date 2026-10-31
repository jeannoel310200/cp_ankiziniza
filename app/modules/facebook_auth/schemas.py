from pydantic import BaseModel


class FacebookCallbackRequest(BaseModel):
    """Payload envoyé par le frontend SPA/mobile après redirection Facebook."""

    code: str


class FacebookAuthResponse(BaseModel):
    """Tokens retournés au client après authentification Facebook."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    is_new_user: bool  # True = inscription, False = connexion
