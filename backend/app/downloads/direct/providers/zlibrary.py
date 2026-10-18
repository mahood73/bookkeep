"""Z-Library's JSON API, pinned to the configured HTTPS domain."""
import re
from typing import List, Optional
from urllib.parse import urlsplit, urljoin, urlunsplit, unquote

import httpx
import structlog

from .base import DirectProvider, DirectSearchResult
from ... import SearchError

logger = structlog.get_logger()


class ZLibraryError(RuntimeError):
    """A safe diagnostic that contains neither credentials nor response bodies."""


class ZLibraryProvider(DirectProvider):
    DEFAULT_DOMAIN = "z-lib.gd"
    USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    EBOOK_EXTENSIONS = ["epub", "mobi", "azw3", "pdf", "fb2"]
    AUDIOBOOK_EXTENSIONS = ["mp3", "m4b", "m4a"]
    BOOK_PATH = re.compile(r"/book/(\d+)/([a-zA-Z0-9]+)(?:/[^?]*)?/?$")

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None,
                 domain: Optional[str] = None, timeout: float = 30.0,
                 flaresolverr_url: Optional[str] = None):
        self.domain = self.normalize_domain(domain)
        self.email = email
        self.password = password
        self.timeout = timeout
        # Retain the constructor interface; API calls do not use FlareSolverr.
        self._client: Optional[httpx.AsyncClient] = None
        self._authenticated = False
        self.last_error: Optional[str] = None

    @classmethod
    def normalize_domain(cls, domain: Optional[str]) -> str:
        value = (domain or "").strip() or cls.DEFAULT_DOMAIN
        parsed = urlsplit(value if "://" in value else "https://" + value)
        if (parsed.scheme != "https" or not parsed.hostname or
                parsed.username or parsed.password or parsed.netloc.lower() != parsed.hostname or
                parsed.path not in ("", "/") or parsed.query or parsed.fragment or
                not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname)):
            raise ValueError("Z-Library domain must be an HTTPS hostname without a port or path")
        return parsed.hostname

    @property
    def name(self) -> str:
        return "zlibrary"

    @property
    def base_url(self) -> str:
        return "https://" + self.domain

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
                # Never forward credentials or silently switch domains on redirects.
                follow_redirects=False,
            )
        return self._client

    async def _request(self, method: str, path: str, data=None) -> dict:
        client = await self._get_client()
        try:
            response = await client.request(method, self.base_url + path, data=data)
        except httpx.RequestError as exc:
            raise ZLibraryError(f"Cannot connect to configured Z-Library domain {self.domain} ({type(exc).__name__})") from None
        if response.is_redirect:
            raise ZLibraryError(f"Configured Z-Library domain {self.domain} redirected the API request; check the domain or browser protection")
        if response.status_code in (403, 513, 517) or "diamwall" in response.text.lower():
            raise ZLibraryError(f"Configured Z-Library domain {self.domain} blocks API access (HTTP {response.status_code})")
        try:
            payload = response.json()
        except ValueError:
            raise ZLibraryError(f"Configured Z-Library domain {self.domain} returned a non-JSON API response (HTTP {response.status_code})") from None
        if not isinstance(payload, dict):
            raise ZLibraryError("Z-Library returned an invalid API response")
        if not payload.get("success"):
            # Do not log the upstream body: it can include account/session fields.
            error = str(payload.get("error", "")).lower()
            if "incorrect email or password" in error:
                raise ZLibraryError("Z-Library rejected the saved email or password")
            if "authorization failed" in error:
                raise ZLibraryError("Z-Library refused API authorization")
            if "daily download limit" in error or "download quota exceeded" in error:
                raise ZLibraryError("Z-Library reports the account download quota is exhausted")
            raise ZLibraryError(f"Z-Library API request failed (HTTP {response.status_code})")
        if response.is_error:
            raise ZLibraryError(f"Z-Library API returned HTTP {response.status_code}")
        return payload

    async def _authenticate(self) -> bool:
        if self._authenticated:
            return True
        if not self.email or not self.password:
            self.last_error = "Z-Library requires a saved email and password"
            return False
        try:
            payload = await self._request("POST", "/eapi/user/login", {
                "email": self.email, "password": self.password,
            })
            client = await self._get_client()
            user = payload.get("user") or {}
            if user.get("id") and user.get("remix_userkey"):
                client.cookies.set("remix_userid", str(user["id"]), domain=self.domain, path="/")
                client.cookies.set("remix_userkey", str(user["remix_userkey"]), domain=self.domain, path="/")
            if not client.cookies.get("remix_userid", domain=self.domain) or not client.cookies.get("remix_userkey", domain=self.domain):
                raise ZLibraryError("Z-Library login returned no usable session")
            # Ignore advertised/personal domains: the UI override is authoritative.
            self._authenticated = True
            self.last_error = None
            return True
        except ZLibraryError as exc:
            self.last_error = str(exc)
            logger.warning("zlibrary_auth_failed", domain=self.domain, error=self.last_error)
            return False

    async def test_connection(self) -> bool:
        return await self._authenticate()

    async def search(self, title: str, author: Optional[str] = None,
                     isbn: Optional[str] = None, format_type: str = "ebook", *, strict: bool = False) -> List[DirectSearchResult]:
        """Search once; strict automatic mode propagates safe source failures."""
        if not await self._authenticate():
            if strict:
                raise SearchError(f"{self.last_error or 'Z-Library authentication failed'}; retry manually.")
            return []
        extensions = self.AUDIOBOOK_EXTENSIONS if format_type == "audiobook" else self.EBOOK_EXTENSIONS
        query = isbn or " ".join(part for part in [title, author] if part)
        try:
            payload = await self._request("POST", "/eapi/book/search", {
                "message": query, "extensions[]": extensions, "limit": "20", "page": "1",
            })
            if strict and not isinstance(payload.get("books"), list):
                raise ZLibraryError("Z-Library returned no valid search result list")
            self.last_error = None
            results = []
            seen = set()
            for book in payload.get("books") or []:
                if not isinstance(book, dict):
                    continue
                ext = str(book.get("extension") or "").lower().lstrip(".")
                book_id, book_hash = str(book.get("id") or ""), str(book.get("hash") or "")
                if ext not in extensions or not book_id.isdigit() or not re.fullmatch(r"[a-zA-Z0-9]+", book_hash):
                    continue
                book_title = str(book.get("title") or "").strip()
                url = f"{self.base_url}/book/{book_id}/{book_hash}"
                if not book_title or url in seen:
                    continue
                seen.add(url)
                size = self._parse_size(book.get("filesize"))
                language = str(book.get("language") or "").lower()
                language = {"english": "en", "french": "fr", "german": "de", "spanish": "es", "italian": "it", "portuguese": "pt", "russian": "ru"}.get(language, language) or None
                year_text = str(book.get("year") or "")
                results.append(DirectSearchResult(
                    title=book_title, download_url=url, info_url=self._browser_book_url(book.get("href")),
                    format=ext, size_bytes=size, author=book.get("author"), language=language,
                    year=int(year_text) if year_text.isdigit() else None,
                    quality_score=self._calculate_quality(ext, size, format_type), provider=self.name,
                ))
            return results
        except ZLibraryError as exc:
            self.last_error = str(exc)
            if strict:
                raise SearchError(f"Z-Library search failed: {self.last_error}. Retry manually.") from None
            logger.warning("zlibrary_search_failed", domain=self.domain, error=self.last_error)
            return []

    def _browser_book_url(self, href) -> Optional[str]:
        """Use the provider's browser route without exposing session parameters."""
        if not isinstance(href, str) or not href.strip():
            return None
        href = href.strip()
        if any(character.isspace() or character == "\\" for character in href):
            return None
        try:
            parsed = urlsplit(urljoin(self.base_url + "/", href))
            parts = unquote(parsed.path).split("/")
            if (parsed.scheme != "https" or parsed.netloc.lower() != self.domain or
                    parts[:2] != ["", "book"] or len(parts) < 4 or
                    not parts[2] or not parts[3] or any(part in (".", "..") for part in parts)):
                return None
            return urlunsplit(("https", self.domain, parsed.path, "", ""))
        except ValueError:
            return None

    def is_book_url(self, url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.scheme == "https" and parsed.netloc == self.domain and bool(self.BOOK_PATH.fullmatch(parsed.path))

    async def resolve_download_url(self, book_url: str) -> str:
        if not self.is_book_url(book_url):
            raise ZLibraryError("Z-Library book URL does not match the configured domain")
        if not await self._authenticate():
            raise ZLibraryError(self.last_error or "Z-Library login failed")
        match = self.BOOK_PATH.fullmatch(urlsplit(book_url).path)
        payload = await self._request("GET", f"/eapi/book/{match[1]}/{match[2]}/file")
        file_data = payload.get("file") or {}
        link = file_data.get("downloadLink") or payload.get("downloadLink")
        if not isinstance(link, str) or not link:
            raise ZLibraryError("Z-Library returned no download link; check availability and account quota")
        url = urljoin(self.base_url, link)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ZLibraryError("Z-Library returned an invalid download link")
        return url

    async def copy_session_to(self, client: httpx.Client):
        """Keep session cookies scoped to the configured domain, never the file host."""
        source = await self._get_client()
        for name in ("remix_userid", "remix_userkey"):
            value = source.cookies.get(name, domain=self.domain)
            if value:
                client.cookies.set(name, value, domain=self.domain, path="/")

    @staticmethod
    def _parse_size(value) -> int:
        if isinstance(value, (int, float)):
            return max(0, int(value))
        text = str(value or "").strip()
        if text.isdigit():
            return int(text)
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)", text, re.IGNORECASE)
        if not match:
            return 0
        return int(float(match[1]) * {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}[match[2].upper()])

    @staticmethod
    def _calculate_quality(file_format: str, size_bytes: int, format_type: str) -> float:
        scores = {"m4b": 20, "mp3": 10, "m4a": 15} if format_type == "audiobook" else {"epub": 20, "azw3": 15, "mobi": 10, "pdf": 5, "fb2": 5}
        score = 50 + scores.get(file_format, 0)
        lower, upper = (50_000_000, 2_000_000_000) if format_type == "audiobook" else (100_000, 50_000_000)
        return min(100, score + (10 if lower < size_bytes < upper else 0))

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        self._authenticated = False
