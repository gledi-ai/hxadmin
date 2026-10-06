from collections.abc import Collection
from urllib.parse import urlsplit

from starlette.requests import Request

SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))


def normalize_origin(origin: str) -> str:
    """`scheme://host[:port]`, lowercased; ValueError for anything that is not a bare origin."""
    parts = urlsplit(origin.strip())
    bare = parts.path in ("", "/") and not (parts.query or parts.fragment or "@" in parts.netloc)
    if parts.scheme not in ("http", "https") or not parts.netloc or not bare:
        raise ValueError(f"Trusted origin must look like 'https://admin.example.com': {origin!r}")
    return f"{parts.scheme}://{parts.netloc}".lower()


def is_cross_origin(request: Request, trusted: Collection[str] = ()) -> bool:
    """Whether a state-changing request was sent by a browser from another origin.

    Browsers send `Sec-Fetch-Site`; older ones only send `Origin`, which is compared with
    `Host`. A request with neither header does not come from a browser and passes.
    Origins in `trusted` (normalized with `normalize_origin`) always pass.
    """
    if request.method in SAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    if origin is not None and origin.lower() in trusted:
        return False
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in ("same-origin", "none")
    if origin is None:
        return False
    host = request.headers.get("host", "").lower()
    return not host or urlsplit(origin).netloc.lower() != host
