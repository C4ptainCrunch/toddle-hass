"""Asynchronous client for the Toddle (kinderopvang.software) parent API.

This module is deliberately free of Home Assistant imports so it can be
extracted into a standalone library. It talks to the API that powers the
"Toddle for Parents" mobile app, operated by Tactics bvba.

Time handling: the API encodes daycare-local wall-clock time as if it were
UTC. A journal entry written at 15:22 in Brussels comes back as the epoch for
15:22 UTC, and a subscription day's ``date`` is UTC midnight of that day. All
values are therefore decoded in UTC and then re-labelled with the daycare
time zone.

Date range *filters* however are matched against real instants: the server
compares them with the true local midnight of each day. Ranges are therefore
sent as real Brussels-time bounds, exactly like the official app does.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
import json
import logging
import socket
import time as time_mod
from typing import Any, Self
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://admin.kinderopvang.software/services.php/v1"
DEFAULT_TENANT = "brussel"
DEFAULT_LANGUAGE = "nl"
DAYCARE_TZ = ZoneInfo("Europe/Brussels")

# Refresh the access token this long before it actually expires.
_TOKEN_EXPIRY_MARGIN = 60
# Access tokens live 15 minutes; used when the JWT cannot be decoded.
_DEFAULT_TOKEN_LIFETIME = 900


class ToddleError(Exception):
    """Base exception for the Toddle client."""


class ToddleConnectionError(ToddleError):
    """The API could not be reached or timed out."""


class ToddleAuthenticationError(ToddleError):
    """The credentials or tokens were rejected."""


class ToddleInvalidTenantError(ToddleAuthenticationError):
    """The tenant (organisation) does not exist."""


class ToddleResponseError(ToddleError):
    """The API returned an unexpected status or payload."""

    def __init__(self, message: str, status: int | None = None, body: str = "") -> None:
        """Initialize the error."""
        super().__init__(message)
        self.status = status
        self.body = body


class AttendanceState(StrEnum):
    """Raw ``state`` values of a subscription day observed in the wild.

    Days move from ``EXPECTED`` (planned) to ``OUT`` (attended) to
    ``INVOICED`` (billed). A billed day without presences was missed.
    """

    EXPECTED = "EXPECTED"
    OUT = "OUT"
    INVOICED = "INVOICED"
    ABSENT = "ABSENT"
    UNPLANNED = "UNPLANNED"


class PresenceStatus(StrEnum):
    """Derived presence status of a child for a given day."""

    EXPECTED = "expected"
    PRESENT = "present"
    PICKED_UP = "picked_up"
    ABSENT = "absent"
    NO_DAYCARE = "no_daycare"


def wallclock_from_epoch(value: float) -> datetime:
    """Decode an API timestamp into an aware datetime in the daycare zone."""
    return datetime.fromtimestamp(value, UTC).replace(tzinfo=DAYCARE_TZ)


def date_from_epoch(value: float) -> date:
    """Decode an API day timestamp (UTC midnight) into a date."""
    return datetime.fromtimestamp(value, UTC).date()


def epoch_for_filter(value: date, at: time) -> int:
    """Encode a daycare-local date and time for a date range filter."""
    return int(datetime.combine(value, at, DAYCARE_TZ).timestamp())


def _parse_clock(value: str | None) -> time | None:
    """Parse an ``HH:MM`` string; empty strings mean "not set"."""
    if not value:
        return None
    try:
        hours, minutes = value.split(":", 1)
        return time(int(hours), int(minutes[:2]))
    except ValueError:
        _LOGGER.debug("Ignoring unparsable time value %r", value)
        return None


def _named_ref(value: Any) -> NamedRef | None:
    if isinstance(value, dict) and value.get("uuid"):
        return NamedRef(uuid=value["uuid"], name=value.get("display_name") or "")
    return None


@dataclass(frozen=True, slots=True)
class NamedRef:
    """A reference to another API object with a display name."""

    uuid: str
    name: str


@dataclass(frozen=True, slots=True)
class Parent:
    """The authenticated parent account."""

    uuid: str
    given_name: str
    family_name: str
    email: str

    @property
    def name(self) -> str:
        """Return the full name of the parent."""
        return f"{self.given_name} {self.family_name}".strip()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from an API payload."""
        return cls(
            uuid=data["uuid"],
            given_name=data.get("given_name") or "",
            family_name=data.get("family_name") or "",
            email=data.get("email") or "",
        )


@dataclass(frozen=True, slots=True)
class Child:
    """A child linked to the parent account."""

    uuid: str
    display_name: str
    birth_date: date | None
    gender: str | None
    child_code: str | None
    qr_code_url: str | None

    @property
    def first_name(self) -> str:
        """Return a short, friendly name for the child.

        Children without a registered first name (newborns) are reported as
        ``"? Family Name"``; fall back to the remainder of the name then.
        """
        parts = self.display_name.split()
        if parts and parts[0] != "?":
            return parts[0]
        rest = " ".join(parts[1:]).strip()
        return rest or self.child_code or self.uuid[:8]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from an API payload."""
        dob = data.get("day_of_birth")
        qr = data.get("qr")
        return cls(
            uuid=data["uuid"],
            display_name=(data.get("display_name") or "").strip(),
            birth_date=date_from_epoch(dob) if dob is not None else None,
            gender=data.get("gender"),
            child_code=data.get("child_code"),
            qr_code_url=qr.get("url") if isinstance(qr, dict) else None,
        )


@dataclass(frozen=True, slots=True)
class TimeSlot:
    """A pair of wall-clock in/out times; either side may be missing."""

    start: time | None
    end: time | None

    @property
    def is_empty(self) -> bool:
        """Return whether neither side of the slot is set."""
        return self.start is None and self.end is None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from an API payload."""
        return cls(
            start=_parse_clock(data.get("in")), end=_parse_clock(data.get("out"))
        )


def _slots(value: Any) -> tuple[TimeSlot, ...]:
    if not isinstance(value, list):
        return ()
    slots = (TimeSlot.from_dict(item) for item in value if isinstance(item, dict))
    return tuple(slot for slot in slots if not slot.is_empty)


@dataclass(frozen=True, slots=True)
class SubscriptionDay:
    """Attendance information of a child for one calendar day."""

    uuid: str
    date: date
    state: str
    type_of_day: str | None
    department: NamedRef | None
    daycare: NamedRef | None
    presence_product: NamedRef | None
    schedules: tuple[TimeSlot, ...]
    presences: tuple[TimeSlot, ...]
    remark: str
    absence: str
    exception: str
    temporary_outside: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from an API payload."""
        return cls(
            uuid=data["uuid"],
            date=date_from_epoch(data["date"]),
            state=str(data.get("state") or ""),
            type_of_day=data.get("type_of_day"),
            department=_named_ref(data.get("department")),
            daycare=_named_ref(data.get("daycare")),
            presence_product=_named_ref(data.get("presence_product")),
            schedules=_slots(data.get("schedules")),
            presences=_slots(data.get("presences")),
            remark=(data.get("remark") or "").strip(),
            absence=(data.get("absence") or "").strip(),
            exception=(data.get("exception") or "").strip(),
            temporary_outside=bool(data.get("temporary_outside")),
        )

    def _at(self, value: time | None) -> datetime | None:
        if value is None:
            return None
        return datetime.combine(self.date, value, DAYCARE_TZ)

    @property
    def is_planned(self) -> bool:
        """Return whether the child was supposed to attend on this day."""
        return self.state != AttendanceState.UNPLANNED and bool(
            self.schedules or self.presences
        )

    @property
    def is_attending(self) -> bool:
        """Return whether the child is planned and wasn't reported absent."""
        return (
            self.is_planned
            and self.state != AttendanceState.ABSENT
            and not self.absence
        )

    @property
    def is_present(self) -> bool:
        """Return whether the child is checked in and not yet checked out."""
        return any(slot.start and not slot.end for slot in self.presences)

    def status_at(self, now: datetime) -> PresenceStatus:
        """Derive the presence status as seen at a given moment.

        The raw state isn't reliable on its own: a planned day the child never
        showed up for stays planned (and is billed later), so it only counts as
        absent once its scheduled pick-up time has passed.
        """
        if self.is_present:
            return PresenceStatus.PRESENT
        if any(slot.start for slot in self.presences):
            return PresenceStatus.PICKED_UP
        if self.state == AttendanceState.ABSENT or self.absence:
            return PresenceStatus.ABSENT
        if not self.is_planned:
            return PresenceStatus.NO_DAYCARE
        end = self.scheduled_end or datetime.combine(
            self.date + timedelta(days=1), time.min, DAYCARE_TZ
        )
        return PresenceStatus.ABSENT if now >= end else PresenceStatus.EXPECTED

    @property
    def check_in(self) -> datetime | None:
        """Return the first check-in time of the day."""
        starts = [slot.start for slot in self.presences if slot.start]
        return self._at(min(starts)) if starts else None

    @property
    def check_out(self) -> datetime | None:
        """Return the last check-out time, once the child has left."""
        if self.is_present:
            return None
        ends = [slot.end for slot in self.presences if slot.end]
        return self._at(max(ends)) if ends else None

    @property
    def scheduled_start(self) -> datetime | None:
        """Return the contracted drop-off time."""
        starts = [slot.start for slot in self.schedules if slot.start]
        return self._at(min(starts)) if starts else None

    @property
    def scheduled_end(self) -> datetime | None:
        """Return the contracted pick-up time."""
        ends = [slot.end for slot in self.schedules if slot.end]
        return self._at(max(ends)) if ends else None

    def presence_intervals(self) -> list[tuple[datetime, datetime | None]]:
        """Return actual presence intervals; an open interval has no end."""
        intervals: list[tuple[datetime, datetime | None]] = []
        for slot in self.presences:
            if (start := self._at(slot.start)) is None:
                continue
            intervals.append((start, self._at(slot.end)))
        return intervals

    def schedule_intervals(self) -> list[tuple[datetime, datetime]]:
        """Return contracted schedule intervals."""
        intervals: list[tuple[datetime, datetime]] = []
        for slot in self.schedules:
            start, end = self._at(slot.start), self._at(slot.end)
            if start is not None and end is not None:
                intervals.append((start, end))
        return intervals

    def time_present(self, now: datetime) -> timedelta:
        """Return the total time spent at daycare, counting an open slot up to now."""
        total = timedelta()
        for start, end in self.presence_intervals():
            stop = end if end is not None else max(now, start)
            if stop > start:
                total += stop - start
        return total


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """A journal entry (message, meal, nap, ...) written by daycare staff."""

    uuid: str
    type: str
    message: str
    sender: str
    happened_at: datetime
    created_at: datetime
    priority: bool
    subscription_day_uuid: str | None = field(default=None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from an API payload."""
        happened = data.get("happened_at") or data.get("created_at") or 0
        created = data.get("created_at") or happened
        day = data.get("subscription_day")
        return cls(
            uuid=data["uuid"],
            type=str(data.get("type") or "GENERAL"),
            message=(data.get("message") or "").strip(),
            sender=str(data.get("sender") or ""),
            happened_at=wallclock_from_epoch(happened),
            created_at=wallclock_from_epoch(created),
            priority=bool(data.get("prio")),
            subscription_day_uuid=day.get("uuid") if isinstance(day, dict) else None,
        )


def _token_expiry(token: str) -> float:
    """Return the expiry (epoch seconds) of a JWT without verifying it."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return float(exp)
    except (IndexError, KeyError, TypeError, ValueError, binascii.Error):
        return time_mod.time() + _DEFAULT_TOKEN_LIFETIME


class ToddleClient:
    """Client for the Toddle parent API."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        *,
        device_id: str,
        tenant: str = DEFAULT_TENANT,
        device_name: str = "Home Assistant",
        language: str = DEFAULT_LANGUAGE,
        base_url: str = API_BASE_URL,
        request_timeout: float = 30,
    ) -> None:
        """Initialize the client with an externally managed session."""
        self._session = session
        self._email = email
        self._password = password
        self._device_id = device_id
        self._tenant = tenant
        self._device_name = device_name
        self._language = language
        self._base_url = base_url.rstrip("/")
        self._timeout = ClientTimeout(total=request_timeout)
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at = 0.0
        self._auth_lock = asyncio.Lock()

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Accept-Language": self._language,
            "X-Tactics-Tenant": self._tenant,
            "X-Tactics-Device-Id": self._device_id,
            "X-Tactics-Device-Name": self._device_name,
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a request and return the decoded JSON body."""
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                headers=self._headers(token),
                params=params,
                json=json_body,
                timeout=self._timeout,
            ) as response:
                if response.status in (401, 403):
                    raise ToddleAuthenticationError(
                        f"Authentication rejected ({response.status}) for {path}"
                    )
                if response.status >= 400:
                    text = await response.text()
                    # Invalid or expired tokens are answered with a 400.
                    if token is not None and "'Authorization'" in text:
                        raise ToddleAuthenticationError(
                            f"Access token rejected for {path}"
                        )
                    raise ToddleResponseError(
                        f"Unexpected status {response.status} for {path}: {text[:200]}",
                        response.status,
                        text,
                    )
                try:
                    return await response.json(content_type=None)
                except ValueError as err:
                    raise ToddleResponseError(f"Invalid JSON from {path}") from err
        except TimeoutError as err:
            raise ToddleConnectionError(f"Timeout while requesting {path}") from err
        except ClientResponseError as err:
            raise ToddleResponseError(str(err), err.status) from err
        except (ClientError, socket.gaierror) as err:
            raise ToddleConnectionError(f"Error requesting {path}: {err}") from err

    def _store_tokens(self, data: Any) -> None:
        if not isinstance(data, dict) or not data.get("access_token"):
            raise ToddleResponseError("Authentication response lacks an access token")
        self._access_token = str(data["access_token"])
        if data.get("refresh_token"):
            self._refresh_token = str(data["refresh_token"])
        self._token_expires_at = _token_expiry(self._access_token)

    async def login(self) -> None:
        """Log in with email and password."""
        try:
            data = await self._raw_request(
                "POST",
                "/auth/login",
                json_body={"email": self._email, "password": self._password},
            )
        except ToddleResponseError as err:
            if err.status == 400 and "does not exist" in err.body:
                raise ToddleInvalidTenantError(
                    f"Tenant {self._tenant!r} does not exist"
                ) from err
            # Unknown accounts get a 404, wrong passwords another 4xx.
            if err.status is not None and 400 <= err.status < 500:
                raise ToddleAuthenticationError("Invalid email or password") from err
            raise
        self._store_tokens(data)

    async def _refresh(self) -> bool:
        """Try to refresh the access token; return whether it worked."""
        if self._refresh_token is None:
            return False
        try:
            data = await self._raw_request(
                "POST",
                "/auth/refresh",
                json_body={"refresh_token": self._refresh_token},
            )
        except (ToddleAuthenticationError, ToddleResponseError):
            _LOGGER.debug("Refreshing the access token failed, logging in again")
            self._refresh_token = None
            return False
        self._store_tokens(data)
        return True

    async def _ensure_token(self, *, force: bool = False) -> str:
        """Return a valid access token, refreshing or logging in if needed."""
        async with self._auth_lock:
            valid = time_mod.time() < self._token_expires_at - _TOKEN_EXPIRY_MARGIN
            needs_token = self._access_token is None or force or not valid
            if needs_token and not await self._refresh():
                await self.login()
            assert self._access_token is not None
            return self._access_token

    async def _request(self, path: str, params: dict[str, str] | None = None) -> Any:
        """Perform an authenticated GET, re-authenticating once on rejection."""
        token = await self._ensure_token()
        try:
            return await self._raw_request("GET", path, token=token, params=params)
        except ToddleAuthenticationError:
            # Only force a refresh if nobody else did so in the meantime.
            token = await self._ensure_token(force=token == self._access_token)
            return await self._raw_request("GET", path, token=token, params=params)

    async def _collection(
        self, path: str, params: dict[str, str] | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch a collection and return its items and the reported total.

        The API ignores ``page`` and ``limit`` and never returns more than
        500 items, so callers narrow their query instead of paginating.
        """
        data = await self._request(path, params)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ToddleResponseError(f"Unexpected payload for {path}")
        items = [item for item in data["data"] if isinstance(item, dict)]
        total = data.get("total")
        return items, total if isinstance(total, int) else len(items)

    async def _ranged(
        self, path: str, child_uuid: str, start: date, end: date
    ) -> list[dict[str, Any]]:
        """Fetch a per-child collection, splitting ranges the API truncates."""
        items, total = await self._collection(
            path, self._range_params(child_uuid, start, end)
        )
        if total > len(items):
            if start < end:
                middle = start + (end - start) // 2
                items = await self._ranged(path, child_uuid, start, middle)
                items += await self._ranged(
                    path, child_uuid, middle + timedelta(days=1), end
                )
            else:
                _LOGGER.warning(
                    "%s returned %s of %s items for %s", path, len(items), total, start
                )
        unique: dict[str, dict[str, Any]] = {}
        for item in items:
            if isinstance(uuid := item.get("uuid"), str):
                unique.setdefault(uuid, item)
        return list(unique.values())

    @staticmethod
    def _range_params(child_uuid: str, start: date, end: date) -> dict[str, str]:
        return {
            "child": child_uuid,
            "daterange[gte]": str(epoch_for_filter(start, time.min)),
            "daterange[lte]": str(epoch_for_filter(end, time(23, 59, 59))),
        }

    async def get_me(self) -> Parent:
        """Return the authenticated parent."""
        data = await self._request("/me")
        if not isinstance(data, dict) or "uuid" not in data:
            raise ToddleResponseError("Unexpected payload for /me")
        return Parent.from_dict(data)

    async def get_children(self) -> list[Child]:
        """Return the children linked to the account."""
        items, _ = await self._collection("/parent/children")
        return [Child.from_dict(item) for item in items if "uuid" in item]

    async def get_subscription_days(
        self, child_uuid: str, start: date, end: date
    ) -> list[SubscriptionDay]:
        """Return attendance days for a child, inclusive of both dates."""
        items = await self._ranged("/parent/subscription-days", child_uuid, start, end)
        days = [
            SubscriptionDay.from_dict(item)
            for item in items
            if "uuid" in item and "date" in item
        ]
        # Guard against the server's filter and our decoding disagreeing.
        days = [day for day in days if start <= day.date <= end]
        return sorted(days, key=lambda day: day.date)

    async def get_journals(
        self, child_uuid: str, start: date, end: date
    ) -> list[JournalEntry]:
        """Return journal entries for a child, inclusive of both dates."""
        items = await self._ranged("/parent/journals", child_uuid, start, end)
        entries = [
            entry
            for entry in (JournalEntry.from_dict(i) for i in items if "uuid" in i)
            if start <= entry.happened_at.date() <= end
        ]
        return sorted(entries, key=lambda entry: entry.happened_at)
