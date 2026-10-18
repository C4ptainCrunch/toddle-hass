"""Tests for the Toddle attendance calendar."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.toddle.api import TimeSlot, ToddleConnectionError
from custom_components.toddle.const import UPDATE_INTERVAL_IDLE

from .conftest import CHILD_UUID, fixture_days, fixture_journals

ENTITY_ID = "calendar.emma_attendance"


@pytest.fixture
def platforms() -> list[str]:
    """Only set up calendars."""
    return [Platform.CALENDAR]


async def test_calendars(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot the calendars; the next event is tomorrow's planned day."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_get_events(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test listing events over a range."""
    result = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            "entity_id": ENTITY_ID,
            "start_date_time": "2026-03-31T00:00:00+02:00",
            "end_date_time": "2026-04-05T00:00:00+02:00",
        },
        blocking=True,
        return_response=True,
    )
    assert result == snapshot


async def test_get_events_error(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Test API errors are reported."""
    mock_client.get_subscription_days.side_effect = ToddleConnectionError("down")
    with pytest.raises(HomeAssistantError, match="down"):
        await hass.services.async_call(
            CALENDAR_DOMAIN,
            "get_events",
            {"entity_id": ENTITY_ID, "duration": {"days": 1}},
            blocking=True,
            return_response=True,
        )


async def test_ongoing_event(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test an open presence is the current event."""
    today = fixture_days()[0]
    ongoing = replace(today, presences=(TimeSlot(today.presences[0].start, None),))

    async def get_days(child_uuid, start, end):
        return [ongoing] if child_uuid == CHILD_UUID else []

    mock_client.get_subscription_days.side_effect = get_days
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(ENTITY_ID)
    assert state.state == "on"
    assert state.attributes["message"] == "At daycare"
    assert state.attributes["location"] == "Voorbeeldcreche"


async def test_journal_events(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test journal entries are listed as calendar events."""
    result = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            "entity_id": "calendar.emma_journal",
            "start_date_time": "2026-03-30T00:00:00+02:00",
            "end_date_time": "2026-04-01T00:00:00+02:00",
        },
        blocking=True,
        return_response=True,
    )
    assert result == snapshot


async def test_journal_current_event(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a journal entry that just happened is the current event."""
    latest = fixture_journals()[-1]
    fresh = replace(
        latest,
        uuid="fresh",
        type="UNKNOWN",
        message="\n" + "x" * 100,
        happened_at=latest.happened_at.replace(hour=17, minute=25),
    )
    mock_client.get_journals.side_effect = None
    mock_client.get_journals.return_value = [latest, fresh]
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("calendar.emma_journal")
    assert state.state == "on"
    assert state.attributes["message"] == "📝 " + "x" * 79 + "…"
