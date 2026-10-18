"""Tests for the Toddle sensors."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.toddle.api import JournalEntry, SubscriptionDay, TimeSlot
from custom_components.toddle.const import UPDATE_INTERVAL_IDLE

from .conftest import CHILD_UUID, fixture_days, fixture_journals


@pytest.fixture
def platforms() -> list[str]:
    """Only set up sensors."""
    return [Platform.SENSOR]


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sensors(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot all sensors."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def _refresh_with_days(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
    days: list[SubscriptionDay],
    journals: list[JournalEntry] | None = None,
) -> None:
    async def get_days(child_uuid, start, end):
        return days if child_uuid == CHILD_UUID else []

    mock_client.get_subscription_days.side_effect = get_days
    if journals is not None:
        mock_client.get_journals.side_effect = None
        mock_client.get_journals.return_value = journals
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_present(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a child that is checked in but not yet picked up."""
    today = fixture_days()[0]
    ongoing = replace(today, presences=(TimeSlot(today.presences[0].start, None),))
    await _refresh_with_days(hass, mock_client, freezer, [ongoing])

    assert hass.states.get("sensor.emma_status").state == "present"
    assert hass.states.get("sensor.emma_check_out").state == "unknown"
    # 08:45 until 17:30 (now) is 8h45m.
    state = hass.states.get("sensor.emma_time_at_daycare")
    assert float(state.state) == pytest.approx(8.75)
    assert hass.states.get("sensor.emma_next_daycare_day").state == "unknown"


async def test_absent_and_expected(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test absent and expected days."""
    today = fixture_days()[0]
    expected = replace(today, state="EXPECTED", presences=())
    await _refresh_with_days(hass, mock_client, freezer, [expected])
    assert hass.states.get("sensor.emma_status").state == "expected"
    assert hass.states.get("sensor.emma_scheduled_drop_off").state == (
        "2026-03-31T05:00:00+00:00"
    )
    # Once the scheduled pick-up time passed without a check-in, it's a miss.
    await _refresh_with_days(hass, mock_client, freezer, [expected])
    assert hass.states.get("sensor.emma_status").state == "absent"
    assert hass.states.get("sensor.emma_scheduled_drop_off").state == (
        "2026-03-31T05:00:00+00:00"
    )

    absent = replace(today, state="ABSENT", presences=(), absence="Ziek")
    await _refresh_with_days(hass, mock_client, freezer, [absent], journals=[])
    assert hass.states.get("sensor.emma_status").state == "absent"
    assert hass.states.get("sensor.emma_scheduled_drop_off").state == "unknown"
    assert hass.states.get("sensor.emma_time_at_daycare").state == "unknown"
    assert hass.states.get("sensor.emma_latest_journal_entry").state == "unknown"
    assert hass.states.get("sensor.emma_journal_entries_today").state == "0"

    await _refresh_with_days(hass, mock_client, freezer, [])
    assert hass.states.get("sensor.emma_status").state == "no_daycare"
    assert hass.states.get("sensor.emma_group").state == "unknown"


async def test_long_message_truncated(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test journal messages longer than a state allows are truncated."""
    entry = replace(fixture_journals()[-1], message="z" * 400)
    await _refresh_with_days(hass, mock_client, freezer, fixture_days(), [entry])
    state = hass.states.get("sensor.emma_last_nap")
    assert len(state.state) == 255
    assert state.state.endswith("…")
    assert state.attributes["message"] == "z" * 400
    assert (
        state.attributes["happened_at"]
        == dt_util.parse_datetime("2026-03-31T13:37:00+02:00").isoformat()
    )


async def test_next_day_skips_absences(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test an absent day without a reason isn't the next daycare day."""
    today, tomorrow, *_ = fixture_days()
    absent = replace(tomorrow, state="ABSENT", absence="")
    await _refresh_with_days(hass, mock_client, freezer, [today, absent])
    assert hass.states.get("sensor.emma_next_daycare_day").state == "unknown"
