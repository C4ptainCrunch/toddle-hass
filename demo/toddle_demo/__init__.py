"""Dev-only: serve the test fixtures, moved to the current week, instead of the API.

Used by the ``demo`` docker compose profile to take screenshots without real data.
Any email, password and tenant are accepted when adding the Toddle integration.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from custom_components.toddle.api import (
    DAYCARE_TZ,
    Child,
    JournalEntry,
    Parent,
    SubscriptionDay,
    ToddleClient,
)
from custom_components.toddle.const import DOMAIN as TODDLE_DOMAIN

DOMAIN = "toddle_demo"
FIXTURES = Path("/fixtures")
# The fixtures' "today" (see tests/conftest.py); it is moved to the real today.
FIXTURE_TODAY = date(2026, 3, 31)


_DATA: dict[str, Any] = {}


def _read_fixtures() -> dict[str, Any]:
    return {p.name: json.loads(p.read_text()) for p in FIXTURES.glob("*.json")}


def _load(name: str) -> Any:
    return _DATA[name]


def _shift(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seconds = (datetime.now(DAYCARE_TZ).date() - FIXTURE_TODAY).days * 86400
    return [
        item | {key: item[key] + seconds for key in keys if key in item}
        for item in items
    ]


async def _login(self: ToddleClient) -> None:
    return None


async def _get_me(self: ToddleClient) -> Parent:
    return Parent.from_dict(_load("me.json"))


async def _get_children(self: ToddleClient) -> list[Child]:
    return [Child.from_dict(c) for c in _load("children.json")["data"]]


async def _get_subscription_days(
    self: ToddleClient, child_uuid: str, start: date, end: date
) -> list[SubscriptionDay]:
    items = _shift(_load("subscription_days.json")["data"], ("date",))
    days = (
        SubscriptionDay.from_dict(i) for i in items if i["child"]["uuid"] == child_uuid
    )
    return [d for d in days if start <= d.date <= end]


async def _get_journals(
    self: ToddleClient, child_uuid: str, start: date, end: date
) -> list[JournalEntry]:
    items = _shift(_load("journals.json")["data"], ("happened_at", "created_at"))
    entries = (JournalEntry.from_dict(i) for i in items)
    # Journal fixtures all belong to the first child.
    first = _load("children.json")["data"][0]["uuid"]
    return [
        e
        for e in entries
        if child_uuid == first and start <= e.happened_at.date() <= end
    ]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Patch the Toddle client and reload entries set up before the patch."""
    _DATA.update(await hass.async_add_executor_job(_read_fixtures))
    ToddleClient.login = _login  # type: ignore[method-assign]
    ToddleClient.get_me = _get_me  # type: ignore[method-assign]
    ToddleClient.get_children = _get_children  # type: ignore[method-assign]
    ToddleClient.get_subscription_days = _get_subscription_days  # type: ignore[method-assign]
    ToddleClient.get_journals = _get_journals  # type: ignore[method-assign]
    for entry in hass.config_entries.async_entries(TODDLE_DOMAIN):
        hass.config_entries.async_schedule_reload(entry.entry_id)
    return True
