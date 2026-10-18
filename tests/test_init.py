"""Tests for setup, unload and the coordinator."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.toddle import async_remove_config_entry_device
from custom_components.toddle.api import (
    Child,
    NamedRef,
    ToddleAuthenticationError,
    ToddleConnectionError,
)
from custom_components.toddle.const import (
    DOMAIN,
    UPDATE_INTERVAL_ACTIVE,
    UPDATE_INTERVAL_IDLE,
)
from custom_components.toddle.coordinator import is_active_period

from .conftest import BABY_UUID, CHILD_UUID, fixture_children, fixture_days


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the entry sets up and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_devices(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test a device is created per child."""
    devices = dr.async_entries_for_config_entry(
        device_registry, init_integration.entry_id
    )
    by_name = {device.name: device for device in devices}
    assert set(by_name) == {"Emma", "Janssens"}
    emma = by_name["Emma"]
    assert emma.identifiers == {(DOMAIN, CHILD_UUID)}
    assert emma.manufacturer == "Voorbeeldcreche"
    assert emma.model == "Voorbeeldgroep"
    assert emma.serial_number == "999999999"


@pytest.mark.parametrize(
    ("side_effect", "state"),
    [
        (ToddleConnectionError, ConfigEntryState.SETUP_RETRY),
        (ToddleAuthenticationError, ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    side_effect: Exception,
    state: ConfigEntryState,
) -> None:
    """Test failures while setting up."""
    mock_client.get_children.side_effect = side_effect
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is state


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test rejected credentials during an update start a reauth flow."""
    mock_client.get_children.side_effect = ToddleAuthenticationError
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == init_integration.entry_id


async def test_update_failure_marks_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test entities become unavailable and recover."""
    entity_id = "binary_sensor.emma_at_daycare"
    assert hass.states.get(entity_id).state == "off"

    mock_client.get_children.side_effect = ToddleConnectionError
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    mock_client.get_children.side_effect = None
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(entity_id).state == "off"


async def test_update_interval(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test polling speeds up during daycare hours."""
    coordinator = init_integration.runtime_data
    assert coordinator.update_interval == UPDATE_INTERVAL_ACTIVE

    freezer.move_to("2026-03-31 20:00:00+02:00")
    await coordinator.async_refresh()
    assert coordinator.update_interval == UPDATE_INTERVAL_IDLE


@pytest.mark.parametrize(
    ("moment", "active"),
    [
        ("2026-03-31 06:29:00+02:00", False),
        ("2026-03-31 06:30:00+02:00", True),
        ("2026-03-31 18:59:00+02:00", True),
        ("2026-03-31 19:00:00+02:00", False),
        ("2026-04-04 10:00:00+02:00", False),
    ],
)
def test_is_active_period(moment: str, active: bool) -> None:
    """Test the active period helper."""
    assert is_active_period(dt_util.parse_datetime(moment)) is active


async def test_dynamic_and_stale_children(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test children joining and leaving the account."""
    emma, baby = fixture_children()
    mock_client.get_children.return_value = [emma]
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, BABY_UUID), init_integration.entry_id
        )
        is None
    )
    assert (
        entity_registry.async_get_entity_id("sensor", DOMAIN, f"{BABY_UUID}_status")
        is None
    )

    newcomer = Child(
        uuid="99999999-0000-4000-8000-000000000001",
        display_name="Lucas Janssens",
        birth_date=None,
        gender=None,
        child_code=None,
        qr_code_url=None,
    )
    mock_client.get_children.return_value = [emma, newcomer, baby]
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, newcomer.uuid), init_integration.entry_id
        )
        is not None
    )
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, BABY_UUID), init_integration.entry_id
        )
        is not None
    )
    assert hass.states.get("sensor.lucas_status").state == "no_daycare"


async def test_remove_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test only devices of children no longer linked can be removed."""
    assert await async_setup_component(hass, "config", {})
    emma = device_registry.async_get_device_by_identifier(
        (DOMAIN, CHILD_UUID), init_integration.entry_id
    )
    assert not await async_remove_config_entry_device(hass, init_integration, emma)

    other = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id, identifiers={(DOMAIN, "gone")}
    )
    assert await async_remove_config_entry_device(hass, init_integration, other)

    await hass.config_entries.async_unload(init_integration.entry_id)
    assert await async_remove_config_entry_device(hass, init_integration, emma)


async def test_refresh_after_interval(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the coordinator polls on its interval."""
    calls = mock_client.get_children.call_count
    freezer.tick(UPDATE_INTERVAL_ACTIVE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_client.get_children.call_count == calls + 1


async def test_device_follows_group(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the device shows the child's current group and daycare."""
    days = [
        replace(day, department=NamedRef("g2", "Vlinders")) for day in fixture_days()
    ]

    async def get_days(child_uuid, start, end):
        return days if child_uuid == CHILD_UUID else []

    mock_client.get_subscription_days.side_effect = get_days
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    emma = device_registry.async_get_device_by_identifier(
        (DOMAIN, CHILD_UUID), init_integration.entry_id
    )
    assert emma.model == "Vlinders"
    assert emma.manufacturer == "Voorbeeldcreche"
    baby = device_registry.async_get_device_by_identifier(
        (DOMAIN, BABY_UUID), init_integration.entry_id
    )
    assert baby.model is None
