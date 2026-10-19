"""HTTP client and HTML/JSON parsers for the eBiblio (Cantook) platform.

Everything in this module works against the public web front-end of an eBiblio
deployment: an authenticated session cookie for account operations, plus the
public ``/v1/resources.json`` catalogue API for searching.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .config import Settings

log = logging.getLogger("ebiblio.client")

_LOAN_ID_RE = re.compile(r"/loans/([0-9a-f]{16,32})")
_RESOURCE_ID_RE = re.compile(r"/resources/([0-9a-f]{16,32})")


class EbiblioError(RuntimeError):
    """Raised for any expected failure while talking to eBiblio."""


class AuthenticationError(EbiblioError):
    """Login was refused or the session expired and could not be renewed."""


@dataclass
class Loan:
    """One active loan as shown in *Mi cuenta > Préstamos y reservas*."""

    loan_id: str
    resource_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    expires_at: str | None = None
    secret_question: str | None = None
    secret_answer: str | None = None
    links: dict[str, str] = field(default_factory=dict)
    return_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "loan_id": self.loan_id,
            "resource_id": self.resource_id,
            "title": self.title,
            "authors": self.authors,
            "expires_at": self.expires_at,
            "secret_question": self.secret_question,
            "secret_answer": self.secret_answer,
            "links": self.links,
        }


@dataclass
class Resource:
    """A catalogue record plus the state of its borrow form."""

    resource_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    available: bool | None = None
    availability_text: str | None = None
    medium_id: str | None = None
    formats: list[str] = field(default_factory=list)
    cover: str | None = None
    borrow_form_action: str | None = None
    borrow_form_fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "title": self.title,
            "authors": self.authors,
            "available": self.available,
            "availability_text": self.availability_text,
            "medium_id": self.medium_id,
            "formats": self.formats,
            "cover": self.cover,
        }


@dataclass
class AccountCounters:
    #: The platform shows what is still available, not what was consumed.
    loans_remaining: int | None = None
    loans_limit: int | None = None
    holds_remaining: int | None = None
    holds_limit: int | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "loans_remaining": self.loans_remaining,
            "loans_limit": self.loans_limit,
            "holds_remaining": self.holds_remaining,
            "holds_limit": self.holds_limit,
        }


def _text(node: Any) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


class EbiblioClient:
    """Session-based client for one eBiblio deployment."""

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            }
        )
        self._logged_in = False

    # ------------------------------------------------------------------ auth
    def login(self) -> None:
        """Authenticate and keep the session cookie."""
        url = urljoin(self.settings.base_url + "/", "ebiblio_auth_sign_in")
        resp = self.session.get(url, timeout=self.settings.timeout)
        token = _extract_csrf(resp.text)
        if not token:
            raise AuthenticationError("login page did not contain a CSRF token")
        resp = self.session.post(
            url,
            data={
                "authenticity_token": token,
                "login": self.settings.username,
                "password": self.settings.password,
                "remember_me": "1",
            },
            allow_redirects=True,
            timeout=self.settings.timeout,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        if soup.select_one("form#form-authentication") is not None:
            raise AuthenticationError("eBiblio refused the credentials")
        self._logged_in = True
        log.info("authenticated against %s", self.settings.base_url)

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_login: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        self._ensure_login()
        url = path if path.startswith("http") else urljoin(self.settings.base_url + "/", path.lstrip("/"))
        kwargs.setdefault("timeout", self.settings.timeout)
        kwargs.setdefault("allow_redirects", True)
        resp = self.session.request(method, url, **kwargs)
        if retry_login and _is_login_page(resp):
            log.info("session expired, logging in again")
            self._logged_in = False
            self.login()
            resp = self.session.request(method, url, **kwargs)
        return resp

    # -------------------------------------------------------------- catalogue
    def search(self, query: str = "", page: int = 1, per_page: int = 20, **filters: str) -> list[dict[str, Any]]:
        """Search the public catalogue through the platform's JSON API."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if query:
            params["q"] = query
        for key, value in filters.items():
            if value:
                params[key] = value
        resp = self.session.get(
            urljoin(self.settings.base_url + "/", "v1/resources.json"),
            params=params,
            timeout=self.settings.timeout,
        )
        if resp.status_code != 200:
            raise EbiblioError(f"catalogue search failed (HTTP {resp.status_code})")
        payload = resp.json()
        results = []
        for item in payload.get("resources", []):
            results.append(
                {
                    "resource_id": _resource_id_from_link(item.get("link", "")),
                    "title": item.get("title"),
                    "subtitle": item.get("subtitle"),
                    "authors": [
                        f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
                        for c in item.get("contributors", [])
                        if c.get("nature") in (None, "author")
                    ],
                    "publisher": item.get("publisher_name"),
                    "languages": item.get("languages"),
                    "page_count": item.get("page_count"),
                    "cover": item.get("cover"),
                    "media": [
                        {"id": m.get("id"), "nature": m.get("nature"), "key": m.get("key")}
                        for m in item.get("media", [])
                    ],
                    "url": item.get("link"),
                }
            )
        return results

    def get_resource(self, resource_id: str) -> Resource:
        """Fetch a resource page and parse its borrow form."""
        resp = self._request("GET", f"/resources/{resource_id}")
        if resp.status_code == 404:
            raise EbiblioError(f"resource {resource_id} not found")
        if resp.status_code != 200:
            raise EbiblioError(f"resource {resource_id}: HTTP {resp.status_code}")
        return parse_resource_page(resp.text, resource_id, base_url=self.settings.base_url)

    # ------------------------------------------------------------------ loans
    def loans(self) -> list[Loan]:
        """Active loans (``/my_profile/activity``)."""
        resp = self._request("GET", "/my_profile/activity")
        if resp.status_code != 200:
            raise EbiblioError(f"loans page: HTTP {resp.status_code}")
        return parse_activity_page(resp.text, base_url=self.settings.base_url)

    def account(self) -> AccountCounters:
        resp = self._request("GET", "/my_profile/activity")
        if resp.status_code != 200:
            raise EbiblioError(f"account page: HTTP {resp.status_code}")
        return parse_counters(resp.text)

    def borrow(self, resource_id: str, notify: bool = False, email: str | None = None) -> Loan:
        """Borrow a resource: ``loans_confirmation`` (GET) then ``loans_activation`` (POST)."""
        resource = self.get_resource(resource_id)
        if not resource.borrow_form_action:
            raise EbiblioError(
                f"«{resource.title}» cannot be borrowed right now"
                + (f" ({resource.availability_text})" if resource.availability_text else "")
            )
        fields = dict(resource.borrow_form_fields)
        fields["notify"] = "1" if notify else "0"
        if email:
            fields["email"] = email
        confirm = self._request("GET", resource.borrow_form_action, params=fields)
        if confirm.status_code != 200:
            raise EbiblioError(f"loan confirmation failed (HTTP {confirm.status_code})")
        soup = BeautifulSoup(confirm.text, "html.parser")
        activation = _form_by_action(soup, "loans_activation")
        if activation is None:
            # The platform refuses a second loan of a title the account already
            # holds: that is success from the caller's point of view.
            existing = next(
                (loan for loan in self.loans() if loan.resource_id == resource_id), None
            )
            if existing is not None:
                return existing
            raise EbiblioError(_page_message(confirm.text) or "loan confirmation was refused")
        data = {
            i.get("name"): i.get("value", "")
            for i in activation.find_all("input")
            if i.get("name")
        }
        action = activation.get("action") or ""
        resp = self._request("POST", action, data=data)
        if resp.status_code not in (200, 201):
            raise EbiblioError(f"loan activation failed (HTTP {resp.status_code})")
        loans = self.loans()
        for loan in loans:
            if loan.resource_id == resource_id:
                return loan
        raise EbiblioError(
            _page_message(resp.text) or "the loan was not created (unknown reason)"
        )

    def return_loan(self, loan_id: str, timeout: float = 30.0) -> None:
        """Return a loan early.

        The web UI issues ``PUT /loans/<id>/return`` (jQuery ajax) with the CSRF
        token, then polls ``/v1/loans/<id>/returned.json`` until the loan is
        gone; the platform processes the return asynchronously.
        """
        token = self._csrf_token()
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if token:
            headers["X-CSRF-Token"] = token
        resp = self._request("PUT", f"/loans/{loan_id}/return", headers=headers)
        if resp.status_code not in (200, 201, 204):
            raise EbiblioError(
                f"returning loan {loan_id} failed (HTTP {resp.status_code})"
                + (f": {_page_message(resp.text)}" if resp.text else "")
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not any(loan.loan_id == loan_id for loan in self.loans()):
                return
            time.sleep(1.5)
        raise EbiblioError(
            _page_message(resp.text) or "the loan is still active after the return request"
        )

    # --------------------------------------------------------------- downloads
    def loan_links(self, loan_id: str) -> dict[str, str]:
        for loan in self.loans():
            if loan.loan_id == loan_id:
                return loan.links
        raise EbiblioError(f"loan {loan_id} is not active")

    def fetch_loan_file(self, url: str) -> tuple[bytes, str]:
        """Download an .acsm / .lcpl payload (or any loan link)."""
        resp = self._request("GET", url)
        if resp.status_code != 200:
            raise EbiblioError(f"loan download failed (HTTP {resp.status_code})")
        return resp.content, resp.headers.get("Content-Type", "")

    def _csrf_token(self) -> str | None:
        resp = self._request("GET", "/my_profile/activity")
        soup = BeautifulSoup(resp.text, "html.parser")
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta and meta.get("content"):
            return meta["content"]
        return _extract_csrf(resp.text)


# --------------------------------------------------------------------- parsing
def _extract_csrf(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    field = soup.find("input", {"name": "authenticity_token"})
    if field and field.get("value"):
        return field["value"]
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]
    return None


def _form_by_action(soup: BeautifulSoup, needle: str) -> Any:
    for form in soup.find_all("form"):
        if needle in (form.get("action") or ""):
            return form
    return None


def _is_login_page(resp: requests.Response) -> bool:
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype:
        return False
    if "/ebiblio_auth_sign_in" in resp.url and "sign_out" not in resp.text:
        return True
    return "form-authentication" in resp.text and "sign_out" not in resp.text


def _resource_id_from_link(link: str) -> str | None:
    match = _RESOURCE_ID_RE.search(link or "")
    return match.group(1) if match else None


def _page_message(html: str) -> str | None:
    """Best-effort extraction of a human readable error/notice from a page.

    The account banner ("Tienes todavía derecho a N préstamos…") is present on
    every page and never the reason an action failed, so it is skipped.
    """
    soup = BeautifulSoup(html, "html.parser")
    for selector in (".msg--error", ".alert--error", ".js-loan__error", ".error", ".alert", ".notice"):
        for node in soup.select(selector):
            text = _text(node)
            if text and not _is_counter_banner(node, text):
                return text[:400]
    for node in soup.select(".msg__text"):
        text = _text(node)
        if text and not _is_counter_banner(node, text):
            return text[:400]
    title = soup.title.string if soup.title else None
    return title.strip()[:200] if title else None


def _is_counter_banner(node: Any, text: str) -> bool:
    if "Tienes todavía derecho a" in text:
        return True
    link = node.find("a", href=True)
    return bool(link and "counters" in (link.get("href") or ""))


def parse_counters(html: str) -> AccountCounters:
    soup = BeautifulSoup(html, "html.parser")
    counters = AccountCounters()
    for item in soup.select(".counters__item, .counter, li"):
        label = _text(item)
        match = re.search(r"(\d+)\s*/\s*(\d+)", label)
        if not match:
            continue
        low = label.lower()
        if "préstamo" in low and counters.loans_limit is None:
            counters.loans_remaining, counters.loans_limit = int(match.group(1)), int(match.group(2))
        elif "reserva" in low and counters.holds_limit is None:
            counters.holds_remaining, counters.holds_limit = int(match.group(1)), int(match.group(2))
    text = _text(soup.select_one("header") or soup)
    match = re.search(r"Tienes todavía derecho a (\d+) préstamos y (\d+) reservas", text)
    if match:
        counters.loans_remaining = int(match.group(1))
        counters.holds_remaining = int(match.group(2))
    menu = soup.select_one(".nav-account__link-account")
    if menu:
        counters.name = _text(menu) or None
    return counters


def parse_resource_page(html: str, resource_id: str, base_url: str = "") -> Resource:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("h1") or soup.select_one("meta[property='og:title']")
    if title_node and title_node.name == "meta":
        title = title_node.get("content", "")
    else:
        title = _text(title_node)
    authors = [_text(a) for a in soup.select(".contributors a, [itemprop='author']") if _text(a)]
    authors = list(dict.fromkeys(authors))
    availability_node = soup.select_one(".availability")
    availability_text = _text(availability_node) or None
    available: bool | None = None
    if availability_text:
        low = availability_text.lower()
        if "no disponible" in low or "prestado" in low:
            available = False
        elif "disponible" in low:
            available = True
    cover_node = soup.select_one("meta[property='og:image']")
    cover = cover_node.get("content") if cover_node else None

    resource = Resource(
        resource_id=resource_id,
        title=title,
        authors=authors,
        available=available,
        availability_text=availability_text,
        cover=cover,
    )
    form = _form_by_action(soup, "loans_confirmation")
    if form is not None:
        action = form.get("action") or ""
        resource.borrow_form_action = action
        resource.borrow_form_fields = {
            i.get("name"): i.get("value", "") for i in form.find_all("input") if i.get("name")
        }
        match = re.search(r"/media/([^/]+)/loans_confirmation", action)
        if match:
            resource.medium_id = match.group(1)
            resource.formats = _formats_from_medium_id(match.group(1))
    else:
        for anchor in soup.select("a[href*='/media/'][href*='/loans_confirmation']"):
            href = anchor.get("href") or ""
            match = re.search(r"/media/([^/]+)/loans_confirmation", href)
            if match:
                resource.medium_id = match.group(1)
                resource.formats = _formats_from_medium_id(match.group(1))
                resource.borrow_form_action = href
                resource.borrow_form_fields = {"_resource_id": resource_id}
                break
    if not resource.formats:
        for node in soup.select("[data-format], .format, .media__content"):
            value = (node.get("data-format") or _text(node)).lower()
            if value in ("epub", "pdf", "audiobook"):
                resource.formats.append(value)
        resource.formats = list(dict.fromkeys(resource.formats))
    return resource


def _formats_from_medium_id(medium_id: str) -> list[str]:
    tail = medium_id.rsplit("-", 1)[-1].lower()
    return [tail] if tail in ("epub", "pdf", "audiobook", "mp3") else []


def parse_activity_page(html: str, base_url: str = "") -> list[Loan]:
    """Parse *Préstamos y reservas* into structured loans."""
    soup = BeautifulSoup(html, "html.parser")
    loans: list[Loan] = []
    for item in soup.select("li.js-loan"):
        loan_id = None
        item_id = item.get("id") or ""
        match = re.match(r"loan-(.+)", item_id)
        if match:
            loan_id = match.group(1)
        button = item.select_one("[data-loan-id]")
        if button:
            loan_id = button.get("data-loan-id") or loan_id
        resource_id = button.get("data-resource-id") if button else None
        if not resource_id:
            link = item.select_one("a[href^='/resources/'], a[href*='/resources/']")
            if link:
                resource_id = _resource_id_from_link(link.get("href", ""))
        if not loan_id or not resource_id:
            continue
        title = _text(item.select_one(".details-content__title")) or _text(item.select_one("h4"))
        authors = [
            _text(a)
            for a in item.select(".contributors a, [itemprop='author']")
            if _text(a)
        ]
        authors = list(dict.fromkeys(authors))
        expiry_node = item.select_one(".time-remaining strong") or item.select_one(".time-remaining")
        expires = _text(expiry_node) or None
        if expires:
            expires = re.sub(r"^Tu préstamo expira el\s*", "", expires).rstrip(".")
        question = answer = None
        dl = item.find("dl")
        if dl:
            pairs = dl.find_all(["dt", "dd"])
            for index in range(0, len(pairs) - 1, 2):
                key, value = _text(pairs[index]).lower(), _text(pairs[index + 1])
                if "pregunta" in key:
                    question = value
                elif "respuesta" in key:
                    answer = value
        links: dict[str, str] = {}
        for anchor in item.select("a[href*='/loans/']"):
            href = (anchor.get("href") or "").replace("&amp;", "&")
            if "drm=acs4" in href:
                links.setdefault("acs4", href)
            elif "drm=lcp" in href:
                key = "lcp_reader" if "device_type=reader" in href else "lcp_computer"
                links.setdefault(key, href)
            elif "viewer=web_reader" in href:
                links.setdefault("web_reader", href)
        return_url = button.get("data-url") if button else None
        loans.append(
            Loan(
                loan_id=loan_id,
                resource_id=resource_id,
                title=title,
                authors=authors,
                expires_at=expires,
                secret_question=question,
                secret_answer=answer,
                links=links,
                return_url=return_url,
            )
        )
    return loans
