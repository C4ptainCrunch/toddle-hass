"""Tests for the Toddle API client."""

from __future__ import annotations

import base64
from datetime import date, datetime, time
import json
import time as time_mod
from unittest.mock import patch

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.toddle.api import (
    API_BASE_URL,
    DAYCARE_TZ,
    Child,
    JournalEntry,
    PresenceStatus,
    SubscriptionDay,
    ToddleAuthenticationError,
    ToddleClient,
    ToddleConnectionError,
    ToddleInvalidTenantError,
    ToddleResponseError,
    _token_expiry,
    epoch_for_filter,
)

from .conftest import CHILD_UUID, load_fixture

LOGIN = f"{API_BASE_URL}/auth/login"
REFRESH = f"{API_BASE_URL}/auth/refresh"
ME = f"{API_BASE_URL}/me"
CHILDREN = f"{API_BASE_URL}/parent/children"
DAYS = f"{API_BASE_URL}/parent/subscription-days"
JOURNALS = f"{API_BASE_URL}/parent/journals"


def make_token(expires_in: float) -> str:
    """Return an unsigned JWT expiring in the given number of seconds."""
    payload = json.dumps({"exp": int(time_mod.time() + expires_in)}).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"header.{body}.signature"


@pytest.fixture
async def client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> ToddleClient:
    """Return a client using the mocked session."""
    return ToddleClient(
        aioclient_mock.create_session(hass.loop),
        "sofie@example.com",
        "hunter2",
        device_id="device",
        tenant="brussel",
    )


async def test_login_and_headers(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test logging in and the headers sent."""
    token = make_token(900)
    aioclient_mock.post(LOGIN, json={"access_token": token, "refresh_token": "r"})
    aioclient_mock.get(ME, json=load_fixture("me.json"))

    parent = await client.get_me()
    assert parent.name == "Sofie Peeters"

    login_call, me_call = aioclient_mock.mock_calls
    assert login_call[2] == {"email": "sofie@example.com", "password": "hunter2"}
    headers = me_call[3]
    assert headers["Authorization"] == f"Bearer {token}"
    assert headers["X-Tactics-Tenant"] == "brussel"
    assert headers["X-Tactics-Device-Id"] == "device"
    assert headers["Accept"] == "application/json"

    # The token is reused while valid.
    await client.get_me()
    assert aioclient_mock.call_count == 3


async def test_refresh_on_expiry(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test an expiring token is refreshed instead of logging in again."""
    aioclient_mock.post(
        LOGIN, json={"access_token": make_token(30), "refresh_token": "r"}
    )
    aioclient_mock.post(REFRESH, json={"access_token": make_token(900)})
    aioclient_mock.get(ME, json=load_fixture("me.json"))

    await client.get_me()
    await client.get_me()
    urls = [str(call[1]) for call in aioclient_mock.mock_calls]
    assert urls == [LOGIN, ME, REFRESH, ME]
    assert aioclient_mock.mock_calls[2][2] == {"refresh_token": "r"}


async def test_refresh_failure_logs_in(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test a rejected refresh token falls back to logging in."""
    aioclient_mock.post(
        LOGIN, json={"access_token": make_token(30), "refresh_token": "r"}
    )
    aioclient_mock.post(REFRESH, status=401)
    aioclient_mock.get(ME, json=load_fixture("me.json"))

    await client.login()
    await client.get_me()
    urls = [str(call[1]) for call in aioclient_mock.mock_calls]
    assert urls == [LOGIN, REFRESH, LOGIN, ME]


async def test_retry_after_rejection(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test a request rejected with 401 is retried once with a new token."""
    aioclient_mock.post(
        LOGIN, json={"access_token": make_token(900), "refresh_token": "r"}
    )
    aioclient_mock.post(
        REFRESH, json={"access_token": make_token(900), "refresh_token": "r2"}
    )
    aioclient_mock.get(ME, status=401)

    with pytest.raises(ToddleAuthenticationError):
        await client.get_me()
    urls = [str(call[1]) for call in aioclient_mock.mock_calls]
    assert urls == [LOGIN, ME, REFRESH, ME]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, ToddleAuthenticationError),
        (401, ToddleAuthenticationError),
        (500, ToddleResponseError),
    ],
)
async def test_login_errors(
    client: ToddleClient,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    error: type[Exception],
) -> None:
    """Test login errors are mapped."""
    aioclient_mock.post(LOGIN, status=status, text="nope")
    with pytest.raises(error):
        await client.login()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"exc": TimeoutError}, ToddleConnectionError),
        ({"exc": ClientError}, ToddleConnectionError),
        ({"text": "not json"}, ToddleResponseError),
        ({"json": {"no": "token"}}, ToddleResponseError),
    ],
)
async def test_transport_errors(
    client: ToddleClient,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, object],
    error: type[Exception],
) -> None:
    """Test transport and payload errors are mapped."""
    aioclient_mock.post(LOGIN, **kwargs)
    with pytest.raises(error):
        await client.login()


@pytest.mark.parametrize("payload", [[], {"uuid": None, "x": 1}])
async def test_bad_payloads(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker, payload: object
) -> None:
    """Test unexpected payload shapes."""
    aioclient_mock.post(LOGIN, json={"access_token": make_token(900)})
    aioclient_mock.get(ME, json=[])
    aioclient_mock.get(CHILDREN, json=payload)
    with pytest.raises(ToddleResponseError):
        await client.get_me()
    with pytest.raises(ToddleResponseError):
        await client.get_children()


def _range(start: date, end: date) -> dict[str, str]:
    return {
        "child": CHILD_UUID,
        "daterange[gte]": str(epoch_for_filter(start, time.min)),
        "daterange[lte]": str(epoch_for_filter(end, time(23, 59, 59))),
    }


async def test_truncated_ranges_are_split(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test ranges the API truncates are split; pages are ignored by the API."""
    entries = load_fixture("journals.json")["data"]
    monday = [e for e in entries if e["uuid"].endswith("1")]
    tuesday = [e for e in entries if not e["uuid"].endswith("1")]
    mon, tue = date(2026, 3, 30), date(2026, 3, 31)
    aioclient_mock.post(LOGIN, json={"access_token": make_token(900)})
    # The whole range is truncated to two (one duplicated) items.
    aioclient_mock.get(
        JOURNALS,
        params=_range(mon, tue),
        json={"data": [tuesday[0], tuesday[0]], "total": 4},
    )
    aioclient_mock.get(
        JOURNALS, params=_range(mon, mon), json={"data": monday, "total": 1}
    )
    # A single day can't be split any further.
    aioclient_mock.get(
        JOURNALS, params=_range(tue, tue), json={"data": tuesday[:2], "total": 3}
    )
    with patch("custom_components.toddle.api._LOGGER.warning") as warning:
        result = await client.get_journals(CHILD_UUID, mon, tue)
    assert [e.uuid[-1] for e in result] == ["1", "2", "3"]
    warning.assert_called_once()


async def test_date_ranges_and_models(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test date ranges are encoded as daycare wall-clock time."""
    aioclient_mock.post(LOGIN, json={"access_token": make_token(900)})
    aioclient_mock.get(DAYS, json=load_fixture("subscription_days.json"))
    aioclient_mock.get(JOURNALS, json=load_fixture("journals.json"))

    days = await client.get_subscription_days(
        CHILD_UUID, date(2026, 3, 31), date(2026, 4, 4)
    )
    params = aioclient_mock.mock_calls[-1][1].query
    assert params["child"] == CHILD_UUID
    # Real Brussels-time bounds, as sent by the official app.
    assert params["daterange[gte]"] == "1774908000"  # 2026-03-31 00:00 CEST
    assert params["daterange[lte]"] == "1775339999"  # 2026-04-04 23:59:59 CEST
    now = datetime(2026, 3, 31, 17, 0, tzinfo=DAYCARE_TZ)
    assert [d.status_at(now) for d in days] == [
        PresenceStatus.PICKED_UP,
        PresenceStatus.EXPECTED,
        PresenceStatus.ABSENT,
        PresenceStatus.EXPECTED,
        PresenceStatus.NO_DAYCARE,
    ]

    journals = await client.get_journals(
        CHILD_UUID, date(2026, 3, 30), date(2026, 3, 31)
    )
    assert journals[1].happened_at.isoformat() == "2026-03-31T11:48:00+02:00"
    assert journals[1].happened_at.tzinfo is DAYCARE_TZ


def test_child_names() -> None:
    """Test the friendly name of children."""
    base = {"uuid": "abcdef1234", "display_name": "Emma Louise Janssens"}
    assert Child.from_dict(base).first_name == "Emma"
    assert (
        Child.from_dict({**base, "display_name": "? Janssens"}).first_name == "Janssens"
    )
    assert (
        Child.from_dict({**base, "display_name": "?", "child_code": "123"}).first_name
        == "123"
    )
    assert Child.from_dict({**base, "display_name": ""}).first_name == "abcdef12"


def test_subscription_day_details() -> None:
    """Test time slot parsing and derived values."""
    day = SubscriptionDay.from_dict(
        {
            "uuid": "d",
            "date": 1774915200,
            "state": "OUT",
            "schedules": [
                {"in": "07:00", "out": "12:00"},
                {"in": "13:00", "out": "18:00"},
            ],
            "presences": [
                {"in": "08:00", "out": "10:00"},
                {"in": "bogus", "out": ""},
                {"in": "14:00", "out": ""},
                "garbage",
            ],
        }
    )
    assert day.is_present
    assert day.status_at(day.check_in) is PresenceStatus.PRESENT
    assert day.check_in.time() == time(8, 0)
    assert day.check_out is None
    assert day.scheduled_start.time() == time(7, 0)
    assert day.scheduled_end.time() == time(18, 0)
    now = day.check_in.replace(hour=15)
    assert day.time_present(now).total_seconds() == 3 * 3600
    assert len(day.schedule_intervals()) == 2

    bare = SubscriptionDay.from_dict(
        {"uuid": "d", "date": 1774915200, "schedules": None}
    )
    assert bare.status_at(day.check_in) is PresenceStatus.NO_DAYCARE
    assert bare.check_in is bare.check_out is bare.scheduled_start is None


def test_journal_defaults() -> None:
    """Test journal entries with missing fields."""
    entry = JournalEntry.from_dict({"uuid": "j", "created_at": 1774957846})
    assert entry.type == "GENERAL"
    assert entry.happened_at == entry.created_at
    assert entry.subscription_day_uuid is None


def test_token_expiry_fallback() -> None:
    """Test undecodable tokens are assumed to live 15 minutes."""
    assert _token_expiry("garbage") == pytest.approx(time_mod.time() + 900, abs=5)
    assert _token_expiry(make_token(100)) == pytest.approx(time_mod.time() + 100, abs=5)


async def test_out_of_range_items_dropped(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test records outside the requested dates are ignored."""
    aioclient_mock.post(LOGIN, json={"access_token": make_token(900)})
    aioclient_mock.get(DAYS, json=load_fixture("subscription_days.json"))
    aioclient_mock.get(JOURNALS, json=load_fixture("journals.json"))
    day = date(2026, 3, 31)
    days = await client.get_subscription_days(CHILD_UUID, day, day)
    assert [d.date for d in days] == [day]
    journals = await client.get_journals(CHILD_UUID, day, day)
    assert {j.happened_at.date() for j in journals} == {day}


async def test_unknown_tenant(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test a tenant that doesn't exist is reported as such."""
    aioclient_mock.post(
        LOGIN,
        status=400,
        json={"message": 'Connection named "x" does not exist.', "type": "GENERIC"},
    )
    with pytest.raises(ToddleInvalidTenantError):
        await client.login()


async def test_rejected_token_400(
    client: ToddleClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test a 400 about the Authorization header triggers a new token."""
    aioclient_mock.post(LOGIN, json={"access_token": make_token(900)})
    aioclient_mock.get(
        ME,
        status=400,
        json={"message": "Invalid 'Authorization' Header on request"},
    )
    with pytest.raises(ToddleAuthenticationError):
        await client.get_me()
    urls = [str(call[1]) for call in aioclient_mock.mock_calls]
    assert urls == [LOGIN, ME, LOGIN, ME]


def test_missed_day_becomes_absent() -> None:
    """Test a planned day without check-in counts as absent once it's over."""
    day = SubscriptionDay.from_dict(
        {
            "uuid": "d",
            "date": 1774915200,
            "state": "INVOICED",
            "schedules": [{"in": "07:00", "out": "18:00"}],
            "presences": [{"in": "", "out": ""}],
        }
    )
    at = lambda h: datetime(2026, 3, 31, h, 0, tzinfo=DAYCARE_TZ)  # noqa: E731
    assert day.status_at(at(17)) is PresenceStatus.EXPECTED
    assert day.status_at(at(18)) is PresenceStatus.ABSENT
    assert day.is_attending
    unscheduled = SubscriptionDay.from_dict(
        {
            "uuid": "d",
            "date": 1774915200,
            "state": "OUT",
            "schedules": [],
            "presences": [{"in": "", "out": "10:00"}],
        }
    )
    assert unscheduled.status_at(at(23)) is PresenceStatus.EXPECTED
    assert (
        unscheduled.status_at(datetime(2026, 4, 1, 0, 0, tzinfo=DAYCARE_TZ))
        is PresenceStatus.ABSENT
    )
