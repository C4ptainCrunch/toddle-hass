"""Tests for the Toddle journal events."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.toddle.const import UPDATE_INTERVAL_IDLE

from .conftest import fixture_journals

ENTITY_ID = "event.emma_journal"


@pytest.fixture
def platforms() -> list[str]:
    """Only set up events."""
    return [Platform.EVENT]


async def test_events(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot the event entities; existing entries don't fire."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN


@pytest.mark.parametrize(
    ("journal_type", "event_type"),
    [("HEALTH", "health"), ("SOMETHING_NEW", "other")],
)
async def test_new_entry_fires(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
    journal_type: str,
    event_type: str,
) -> None:
    """Test a new journal entry fires an event once."""
    new = replace(
        fixture_journals()[-1], uuid="new", type=journal_type, message="Koortsje"
    )
    mock_client.get_journals.side_effect = None
    mock_client.get_journals.return_value = [*fixture_journals(), new]

    for _ in range(2):
        freezer.tick(UPDATE_INTERVAL_IDLE)
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(ENTITY_ID)
    assert state.attributes["event_type"] == event_type
    assert state.attributes["message"] == "Koortsje"
    assert state.attributes["journal_type"] == journal_type
    assert state.attributes["uuid"] == "new"
    first_fired = state.state
    assert first_fired != STATE_UNKNOWN
    # The second refresh had nothing new, so the event wasn't fired again.
    assert first_fired == "2026-03-31T15:30:00.000+00:00"
