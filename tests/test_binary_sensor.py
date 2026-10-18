"""Tests for the Toddle binary sensors."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.toddle.api import TimeSlot
from custom_components.toddle.const import UPDATE_INTERVAL_IDLE

from .conftest import CHILD_UUID, fixture_days


@pytest.fixture
def platforms() -> list[str]:
    """Only set up binary sensors."""
    return [Platform.BINARY_SENSOR]


async def test_binary_sensors(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot all binary sensors."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_checked_in(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the sensor turns on while checked in."""
    today = fixture_days()[0]
    ongoing = replace(today, presences=(TimeSlot(today.presences[0].start, None),))

    async def get_days(child_uuid, start, end):
        return [ongoing] if child_uuid == CHILD_UUID else []

    mock_client.get_subscription_days.side_effect = get_days
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("binary_sensor.emma_at_daycare").state == "on"
