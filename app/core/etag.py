"""ETag middleware for conditional GET responses.

Computes a weak ETag (sha1 of the response body, first 16 hex chars) for JSON
GET responses, and returns 304 Not Modified when the client resends the same
value via If-None-Match.

Placed inner to GZipMiddleware so the ETag is computed on the uncompressed body.
"""

import hashlib
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ETagMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method != "GET":
            return await call_next(request)

        response = await call_next(request)

        if response.status_code != 200:
            return response
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        etag = 'W/"' + hashlib.sha1(body).hexdigest()[:16] + '"'

        if request.headers.get("if-none-match") == etag:
            return Response(
                status_code=304,
                headers={
                    "ETag": etag,
                    "Cache-Control": "private, max-age=0, must-revalidate",
                },
            )

        headers = dict(response.headers)
        headers["ETag"] = etag
        headers.setdefault("Cache-Control", "private, max-age=0, must-revalidate")
        headers.pop("content-length", None)

        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
