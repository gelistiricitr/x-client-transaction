import base64
import math
import re
import urllib.request
from typing import Any, Dict, Optional, Union
from urllib.parse import urljoin

import bs4

from .constants import (
    MIGRATION_REDIRECTION_REGEX,
    ON_DEMAND_FILE_REGEX,
    ON_DEMAND_FILE_URL,
    ON_DEMAND_HASH_PATTERN,
    XWEB_ENTRY_REGEX,
    XWEB_SIGN_REGEX,
    XWEB_STARTUP_REGEX,
)

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_HOME_PAGE_CANDIDATES = (
    "https://x.com/i/jf/",
    "https://x.com/x/migrate",
    "https://x.com/",
)
_XWEB_SIGN_URL_CACHE: Dict[str, str] = {}


class Math:

    @staticmethod
    def round(num: Union[float, int]):
        # using javascript...? just use the native Math.round(num)
        x = math.floor(num)
        if (num - x) >= 0.5:
            x = math.ceil(num)
        return math.copysign(x, num)


def generate_headers():
    headers = {
        "authority": "x.com",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "referer": "https://x.com",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
    }
    return headers


def validate_response(response: bs4.BeautifulSoup):
    if not isinstance(response, bs4.BeautifulSoup):
        raise TypeError(
            f"the response object must be bs4.BeautifulSoup, not {type(response).__name__}")


def get_migration_url(response: bs4.BeautifulSoup):
    migration_url = response.select_one("meta[http-equiv='refresh']")
    migration_redirection_url = re.search(MIGRATION_REDIRECTION_REGEX, str(
        migration_url)) or re.search(MIGRATION_REDIRECTION_REGEX, str(response))
    return migration_redirection_url


def get_migration_form(response: bs4.BeautifulSoup):
    migration_form = response.select_one("form[name='f']") or response.select_one(
        f"form[action='https://x.com/x/migrate']")
    if not migration_form:
        return
    url = migration_form.attrs.get("action", "https://x.com/x/migrate")
    method = migration_form.attrs.get("method", "POST")
    request_payload = {input_field.get("name"): input_field.get(
        "value") for input_field in migration_form.select("input")}
    return {"method": method, "url": url, "data": request_payload}


def _fetch_cdn_text(url: str, session: Any = None, timeout: float = 15.0) -> str:
    if session is not None and hasattr(session, "get"):
        try:
            resp = session.get(url)
            if not hasattr(resp, "__await__"):
                text = getattr(resp, "text", None)
                if isinstance(text, str) and text:
                    return text
        except Exception:
            pass

    try:
        from curl_cffi import requests as curl_requests
        resp = curl_requests.get(url, impersonate="chrome", timeout=timeout)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except Exception:
        pass

    req = urllib.request.Request(
        url,
        headers={"User-Agent": generate_headers()["user-agent"]},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _resolve_xweb_sign_url(html: str, session: Any = None) -> Optional[str]:
    direct_match = re.search(
        r"""https://abs\.twimg\.com/x-web/[^\s"'`<>]*sign\.o-[^\s"'`<>]+\.js""",
        html,
    )
    if direct_match:
        return direct_match.group(0)

    entry_match = XWEB_ENTRY_REGEX.search(html)
    if not entry_match:
        return None

    entry_url = entry_match.group(0)
    cached = _XWEB_SIGN_URL_CACHE.get(entry_url)
    if cached:
        return cached

    try:
        entry_js = _fetch_cdn_text(entry_url, session=session)
    except Exception:
        return None

    sign_match = XWEB_SIGN_REGEX.search(entry_js)
    if sign_match:
        resolved = urljoin(entry_url, sign_match.group(1))
        _XWEB_SIGN_URL_CACHE[entry_url] = resolved
        return resolved

    startup_candidates = [m.group(1) for m in XWEB_STARTUP_REGEX.finditer(entry_js)]
    startup_candidates.sort(key=lambda item: (0 if "startup-dynamic-" in item else 1))

    for rel_path in startup_candidates:
        chunk_url = urljoin(entry_url, rel_path)
        try:
            chunk_js = _fetch_cdn_text(chunk_url, session=session)
        except Exception:
            continue
        sign_match = XWEB_SIGN_REGEX.search(chunk_js)
        if sign_match:
            resolved = urljoin(chunk_url, sign_match.group(1))
            _XWEB_SIGN_URL_CACHE[entry_url] = resolved
            return resolved

    return None


def get_ondemand_file_url(response: bs4.BeautifulSoup, session: Any = None):
    html = str(response)
    match = ON_DEMAND_FILE_REGEX.search(html)
    if match:
        chunk_index = match.group(1)
        hash_regex = re.compile(ON_DEMAND_HASH_PATTERN.format(chunk_index))
        hash_match = hash_regex.search(html)
        if hash_match:
            filename = hash_match.group(1)
            return ON_DEMAND_FILE_URL.format(filename=filename)

    return _resolve_xweb_sign_url(html, session=session)


def _is_redirect_loop_error(exc: Exception) -> bool:
    message = f"{type(exc).__name__}: {exc}"
    lowered = message.lower()
    return (
        "toomanyredirects" in lowered
        or "too many redirects" in lowered
        or "is_redirect error" in lowered
    )


def _fetch_with_manual_redirects(session, url: str, *, max_redirects: int = 5):
    current_url = url
    redirects_followed = 0
    while True:
        response = session.request(
            method="GET", url=current_url, allow_redirects=False
        )
        status = getattr(response, "status_code", None)
        if status not in _REDIRECT_STATUS_CODES:
            return response
        location = None
        headers = getattr(response, "headers", None)
        if headers:
            location = headers.get("location") or headers.get("Location")
        if not location:
            return response
        redirects_followed += 1
        if redirects_followed > max_redirects:
            raise RuntimeError(
                f"Redirect zinciri {max_redirects} sınırını aştı: {current_url}"
            )
        current_url = urljoin(current_url, location)


def _request_home_page(session, url: str) -> Any:
    try:
        return session.request(method="GET", url=url)
    except Exception as exc:
        if not _is_redirect_loop_error(exc):
            raise
        return _fetch_with_manual_redirects(session, url)


async def _fetch_with_manual_redirects_async(session, url: str, *, max_redirects: int = 5):
    current_url = url
    redirects_followed = 0
    while True:
        response = await session.request(
            method="GET", url=current_url, allow_redirects=False
        )
        status = getattr(response, "status_code", None)
        if status not in _REDIRECT_STATUS_CODES:
            return response
        location = None
        headers = getattr(response, "headers", None)
        if headers:
            location = headers.get("location") or headers.get("Location")
        if not location:
            return response
        redirects_followed += 1
        if redirects_followed > max_redirects:
            raise RuntimeError(
                f"Redirect zinciri {max_redirects} sınırını aştı: {current_url}"
            )
        current_url = urljoin(current_url, location)


async def _request_home_page_async(session, url: str) -> Any:
    try:
        return await session.request(method="GET", url=url)
    except Exception as exc:
        if not _is_redirect_loop_error(exc):
            raise
        return await _fetch_with_manual_redirects_async(session, url)


def _is_valid_home_page(home_page: bs4.BeautifulSoup) -> bool:
    has_key = bool(
        home_page.select_one("meta[name='twitter-site-verification']")
        or home_page.select_one("[name^='tw']")
    )
    has_frames = bool(home_page.select("[id^='loading-x-anim']"))
    return has_key and has_frames


def handle_x_migration(session):
    # for python requests -> session = requests.Session()
    # session.headers = generate_headers()
    last_home_page: Optional[bs4.BeautifulSoup] = None
    last_error: Optional[Exception] = None

    for candidate_url in _HOME_PAGE_CANDIDATES:
        try:
            response = _request_home_page(session, candidate_url)
            home_page = bs4.BeautifulSoup(response.content, 'html.parser')
            migration_redirection_url = get_migration_url(response=home_page)
            if migration_redirection_url:
                response = session.request(
                    method="GET", url=migration_redirection_url.group(0))
                home_page = bs4.BeautifulSoup(response.content, 'html.parser')
            migration_form = get_migration_form(response=home_page)
            if migration_form:
                response = session.request(**migration_form)
                home_page = bs4.BeautifulSoup(response.content, 'html.parser')
            last_home_page = home_page
            if _is_valid_home_page(home_page):
                return home_page
        except Exception as exc:
            last_error = exc

    if last_home_page is not None:
        return last_home_page
    if last_error is not None:
        raise last_error
    raise RuntimeError("X ana sayfası alınamadı")


async def handle_x_migration_async(session):
    # for httpx -> session = httpx.AsyncClient(headers=generate_headers())
    last_home_page: Optional[bs4.BeautifulSoup] = None
    last_error: Optional[Exception] = None

    for candidate_url in _HOME_PAGE_CANDIDATES:
        try:
            response = await _request_home_page_async(session, candidate_url)
            home_page = bs4.BeautifulSoup(response.content, 'html.parser')
            migration_redirection_url = get_migration_url(response=home_page)
            if migration_redirection_url:
                response = await session.request(
                    method="GET", url=migration_redirection_url.group(0))
                home_page = bs4.BeautifulSoup(response.content, 'html.parser')
            migration_form = get_migration_form(response=home_page)
            if migration_form:
                response = await session.request(**migration_form)
                home_page = bs4.BeautifulSoup(response.content, 'html.parser')
            last_home_page = home_page
            if _is_valid_home_page(home_page):
                return home_page
        except Exception as exc:
            last_error = exc

    if last_home_page is not None:
        return last_home_page
    if last_error is not None:
        raise last_error
    raise RuntimeError("X ana sayfası alınamadı")


def float_to_hex(x):
    result = []
    quotient = int(x)
    fraction = x - quotient

    while quotient > 0:
        quotient = int(x / 16)
        remainder = int(x - (float(quotient) * 16))

        if remainder > 9:
            result.insert(0, chr(remainder + 55))
        else:
            result.insert(0, str(remainder))

        x = float(quotient)

    if fraction == 0:
        return ''.join(result)

    result.append('.')

    while fraction > 0:
        fraction *= 16
        integer = int(fraction)
        fraction -= float(integer)

        if integer > 9:
            result.append(chr(integer + 55))
        else:
            result.append(str(integer))

    return ''.join(result)


def is_odd(num: Union[int, float]):
    if num % 2:
        return -1.0
    return 0.0


def base64_encode(string: str):
    string = string.encode() if isinstance(string, str) else string
    return base64.b64encode(string).decode()


def base64_decode(input):
    try:
        data = base64.b64decode(input)
        return data.decode()
    except Exception:
        # return bytes(input, "utf-8")
        return list(bytes(input, "utf-8"))


if __name__ == "__main__":
    pass
