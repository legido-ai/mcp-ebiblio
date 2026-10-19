"""Tests for the eBiblio HTTP client: auth, parsing, borrowing and returns."""

from __future__ import annotations

import pytest
import requests

from ebiblio_mcp.client import (
    AuthenticationError,
    EbiblioClient,
    EbiblioError,
    parse_activity_page,
    parse_counters,
    parse_resource_page,
)
from ebiblio_mcp.config import Settings

from conftest import FakeSession, fixture, fixture_json, make_response

BASE = "https://andalucia.ebiblio.es"
RESOURCE_ID = "5fcfe8a0114a6f0001f59490"
LOAN_ID = "6ad6496b9d08eec7853de5b4"
MEDIUM = (
    "3ccc34cb-c069-4255-ab94-0f36a75a4690https-warehouse-demarque-dev-publications-"
    "c1cc5f4c-1ee5-47c0-a387-2934bcb5f78c-1110000000061-epub"
)


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        base_url=BASE,
        username="user@example.com",
        password="secret-password",
        data_dir="/tmp/ebiblio-tests",
    )


def build_client(settings: Settings, session: FakeSession, logged_in: bool = True) -> EbiblioClient:
    """Wire a client to a fake session; by default it is already authenticated."""
    session.add_static("GET", r"/ebiblio_auth_sign_in$", make_response(text=fixture("login.html")))
    session.add_static(
        "POST", r"/ebiblio_auth_sign_in$", make_response(text=fixture("activity.html"))
    )
    client = EbiblioClient(settings, session=session)  # type: ignore[arg-type]
    if logged_in:
        client.login()
        session.calls.clear()
    return client


def test_login_posts_credentials(settings: Settings) -> None:
    session = FakeSession()
    session.add_static("GET", r"/ebiblio_auth_sign_in$", make_response(text=fixture("login.html")))
    session.add_static("POST", r"/ebiblio_auth_sign_in$", make_response(text=fixture("activity.html")))

    client = build_client(settings, session)
    client.login()

    posts = session.calls_for(r"/ebiblio_auth_sign_in", "POST")
    assert len(posts) == 1
    data = posts[0]["kwargs"]["data"]
    assert data["login"] == "user@example.com"
    assert data["password"] == "secret-password"
    assert data["authenticity_token"] == "TEST-CSRF-TOKEN"


def test_login_refused(settings: Settings) -> None:
    session = FakeSession()
    session.add_static("GET", r"/ebiblio_auth_sign_in$", make_response(text=fixture("login.html")))
    session.add_static("POST", r"/ebiblio_auth_sign_in$", make_response(text=fixture("login.html")))

    with pytest.raises(AuthenticationError):
        build_client(settings, session).login()


def test_search_parses_json_api(settings: Settings) -> None:
    session = FakeSession()
    session.add_static(
        "GET",
        r"/v1/resources\.json",
        make_response(
            text=fixture("resources.json"),
            content_type="application/json; charset=utf-8",
        ),
    )
    results = build_client(settings, session).search("blasco", per_page=3)
    assert results
    first = results[0]
    assert first["title"]
    assert first["resource_id"]
    assert first["resource_id"] in first["url"]
    assert any(media["nature"] in ("epub", "pdf", "audiobook") for media in first["media"])


def test_parse_resource_page_available() -> None:
    resource = parse_resource_page(fixture("resource_available.html"), RESOURCE_ID)
    assert resource.title == "La barraca (novela)"
    assert resource.authors == ["Vicente Blasco Ibáñez"]
    assert resource.available is True
    assert resource.medium_id == MEDIUM
    assert resource.formats == ["epub"]
    assert resource.borrow_form_action.endswith("/loans_confirmation")
    assert resource.borrow_form_fields["_resource_id"] == RESOURCE_ID


def test_parse_resource_page_unavailable() -> None:
    resource = parse_resource_page(fixture("resource_unavailable.html"), RESOURCE_ID)
    assert resource.borrow_form_action is None
    assert resource.available is False
    assert resource.availability_text == "No disponible"


def test_parse_activity_page_loan_details() -> None:
    loans = parse_activity_page(fixture("activity.html"))
    assert len(loans) == 1
    loan = loans[0]
    assert loan.loan_id == LOAN_ID
    assert loan.resource_id == RESOURCE_ID
    assert loan.title == "La barraca (novela)"
    assert loan.authors == ["Vicente Blasco Ibáñez"]
    assert loan.expires_at == "18 diciembre 2026 a las 17:46"
    assert loan.secret_question == "¿Cuál es tu código de socio?"
    assert loan.secret_answer == "L123456789"
    assert "drm=acs4" in loan.links["acs4"]
    assert "drm=lcp" in loan.links["lcp_computer"]
    assert "drm=lcp" in loan.links["lcp_reader"]
    assert "viewer=web_reader" in loan.links["web_reader"]
    assert loan.return_url.endswith(f"/loans/{LOAN_ID}/return")


def test_parse_counters() -> None:
    counters = parse_counters(fixture("activity.html"))
    assert counters.loans_limit == 5
    assert counters.holds_limit == 2
    assert counters.loans_remaining == 4
    assert counters.holds_remaining == 2
    assert counters.name == "Javier"


def test_borrow_two_step_flow(settings: Settings) -> None:
    session = FakeSession()
    session.add_static("GET", r"/resources/" + RESOURCE_ID, make_response(text=fixture("resource_available.html")))
    session.add_static(
        "GET", r"/loans_confirmation", make_response(text=fixture("loan_confirmation.html"))
    )
    session.add_static("POST", r"/loans_activation", make_response(text=fixture("loan_activated.html")))
    session.add_static("GET", r"/my_profile/activity", make_response(text=fixture("activity.html")))

    loan = build_client(settings, session).borrow(RESOURCE_ID)
    assert loan.loan_id == LOAN_ID

    confirmation = session.calls_for(r"/loans_confirmation", "GET")[0]
    assert confirmation["kwargs"]["params"]["notify"] == "0"
    activation = session.calls_for(r"/loans_activation", "POST")[0]
    assert activation["kwargs"]["data"]["authenticity_token"] == "TEST-CSRF-TOKEN"


def test_borrow_with_notification_email(settings: Settings) -> None:
    session = FakeSession()
    session.add_static("GET", r"/resources/" + RESOURCE_ID, make_response(text=fixture("resource_available.html")))
    session.add_static("GET", r"/loans_confirmation", make_response(text=fixture("loan_confirmation.html")))
    session.add_static("POST", r"/loans_activation", make_response(text=fixture("loan_activated.html")))
    session.add_static("GET", r"/my_profile/activity", make_response(text=fixture("activity.html")))

    build_client(settings, session).borrow(RESOURCE_ID, notify=True, email="other@example.com")
    params = session.calls_for(r"/loans_confirmation", "GET")[0]["kwargs"]["params"]
    assert params["notify"] == "1"
    assert params["email"] == "other@example.com"


def test_borrow_refused_when_no_copy_available(settings: Settings) -> None:
    session = FakeSession()
    session.add_static("GET", r"/resources/" + RESOURCE_ID, make_response(text=fixture("resource_unavailable.html")))
    with pytest.raises(EbiblioError) as excinfo:
        build_client(settings, session).borrow(RESOURCE_ID)
    assert "No disponible" in str(excinfo.value)


def test_borrow_fails_when_loan_is_not_created(settings: Settings) -> None:
    session = FakeSession()
    session.add_static("GET", r"/resources/" + RESOURCE_ID, make_response(text=fixture("resource_available.html")))
    session.add_static("GET", r"/loans_confirmation", make_response(text=fixture("loan_confirmation.html")))
    session.add_static(
        "POST",
        r"/loans_activation",
        make_response(
            text='<html><head><title>Límite alcanzado</title></head><body><p class="msg__text">'
            "No puedes realizar más préstamos hoy</p></body></html>"
        ),
    )
    session.add_static(
        "GET", r"/my_profile/activity", make_response(text="<html><body>Préstamos activos</body></html>")
    )
    with pytest.raises(EbiblioError) as excinfo:
        build_client(settings, session).borrow(RESOURCE_ID)
    assert "No puedes realizar más préstamos hoy" in str(excinfo.value)


def test_borrow_returns_existing_loan_when_already_on_loan(settings: Settings) -> None:
    """A refused confirmation for a title the account already holds is not an error."""
    session = FakeSession()
    session.add_static("GET", r"/resources/" + RESOURCE_ID, make_response(text=fixture("resource_available.html")))
    session.add_static(
        "GET",
        r"/loans_confirmation",
        make_response(
            text='<html><body><p class="msg__text"><a href="/my_profile/activity#counters">'
            "Tienes todavía derecho a 4 préstamos y 2 reservas</a></p>"
            "<p>Ya tienes este título en préstamo</p></body></html>"
        ),
    )
    session.add_static("GET", r"/my_profile/activity", make_response(text=fixture("activity.html")))
    loan = build_client(settings, session).borrow(RESOURCE_ID)
    assert loan.loan_id == LOAN_ID
    assert not session.calls_for(r"/loans_activation", "POST")


def test_page_message_skips_the_counter_banner() -> None:
    from ebiblio_mcp.client import _page_message

    banner = (
        '<html><body><p class="msg__text"><a href="/my_profile/activity#counters">'
        "Tienes todavía derecho a 4 préstamos y 2 reservas</a></p>"
        '<div class="alert">El préstamo ha caducado</div></body></html>'
    )
    assert _page_message(banner) == "El préstamo ha caducado"
    assert _page_message("<html><body><p>x</p></body></html>") is None


def test_return_loan_raises_while_the_loan_is_still_listed(settings: Settings, monkeypatch) -> None:
    session = FakeSession()
    session.add_static("GET", r"/my_profile/activity", make_response(text=fixture("activity.html")))
    session.add_static(
        "PUT",
        rf"/loans/{LOAN_ID}/return",
        make_response(text="{}", content_type="application/json"),
    )
    monkeypatch.setattr("ebiblio_mcp.client.time.sleep", lambda _seconds: None)
    client = build_client(settings, session)
    with pytest.raises(EbiblioError) as excinfo:
        client.return_loan(LOAN_ID, timeout=0.1)
    assert "still active" in str(excinfo.value)
    assert session.calls_for(rf"/loans/{LOAN_ID}/return", "PUT")


def test_return_loan_sends_csrf_and_accepts_disappearance(settings: Settings) -> None:
    session = FakeSession()
    state = {"returned": False}
    empty = '<html><body><meta name="csrf-token" content="TEST-CSRF-TOKEN"><h3>Préstamos activos</h3></body></html>'

    def activity(_kw: dict) -> requests.Response:
        return make_response(text=empty if state["returned"] else fixture("activity.html"))

    def do_return(_kw: dict) -> requests.Response:
        state["returned"] = True
        return make_response(text="{}", content_type="application/json")

    session.add("GET", r"/my_profile/activity", activity)
    session.add("PUT", rf"/loans/{LOAN_ID}/return", do_return)

    build_client(settings, session).return_loan(LOAN_ID)
    call = session.calls_for(rf"/loans/{LOAN_ID}/return", "PUT")[0]
    assert call["kwargs"]["headers"]["X-CSRF-Token"] == "TEST-CSRF-TOKEN"


def test_return_loan_reports_http_error(settings: Settings) -> None:
    session = FakeSession()
    session.add_static("GET", r"/my_profile/activity", make_response(text=fixture("activity.html")))
    session.add_static(
        "PUT", rf"/loans/{LOAN_ID}/return", make_response(status=404, text="<html></html>")
    )
    with pytest.raises(EbiblioError) as excinfo:
        build_client(settings, session).return_loan(LOAN_ID)
    assert "HTTP 404" in str(excinfo.value)


def test_session_renewed_when_expired(settings: Settings) -> None:
    session = FakeSession()
    state = {"expired": True, "logins": 0}

    def login_get(_kw: dict) -> requests.Response:
        state["logins"] += 1
        return make_response(text=fixture("login.html"))

    def activity(_kw: dict) -> requests.Response:
        if state["expired"]:
            # the session was dropped server side: the sign-in page comes back
            state["expired"] = False
            return make_response(text=fixture("login.html"), url=f"{BASE}/my_profile/activity")
        return make_response(text=fixture("activity.html"), url=f"{BASE}/my_profile/activity")

    session.add("GET", r"/ebiblio_auth_sign_in$", login_get)
    session.add(
        "POST",
        r"/ebiblio_auth_sign_in$",
        lambda _kw: make_response(text=fixture("activity.html"), url=f"{BASE}/home"),
    )
    session.add("GET", r"/my_profile/activity", activity)

    loans = build_client(settings, session, logged_in=False).loans()
    assert len(loans) == 1
    assert state["logins"] == 2  # one explicit login + one renewal
