from urllib.parse import urlencode

MOBILE_SCHEME = "akizniz://callback"


def build_success_redirect(access_token: str, refresh_token: str, is_new_user: bool) -> str:
    params = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "is_new_user": str(is_new_user).lower(),
    }
    return f"{MOBILE_SCHEME}?{urlencode(params)}"


def build_error_redirect(error_message: str) -> str:
    params = {"error": error_message}
    return f"{MOBILE_SCHEME}?{urlencode(params)}"
