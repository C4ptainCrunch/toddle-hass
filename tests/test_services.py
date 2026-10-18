"""Tests for the Toddle actions."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.auth.models import Group
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from syrupy.assertion import SnapshotAssertion

from custom_components.toddle.api import ToddleConnectionError
from custom_components.toddle.const import DOMAIN

from .conftest import CHILD_UUID


def _child_device(device_registry: dr.DeviceRegistry, entry: MockConfigEntry) -> str:
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, CHILD_UUID), entry.entry_id
    )
    assert device
    return device.id


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("get_journal", {}),
        ("get_journal", {"start_date": "2026-03-30", "end_date": "2026-03-31"}),
        ("get_attendance", {"start_date": "2026-03-31", "end_date": "2026-04-04"}),
    ],
)
async def test_services(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    snapshot: SnapshotAssertion,
    service: str,
    data: dict[str, str],
) -> None:
    """Test the actions return data."""
    result = await hass.services.async_call(
        DOMAIN,
        service,
        {"child": _child_device(device_registry, init_integration), **data},
        blocking=True,
        return_response=True,
    )
    assert result == snapshot


@pytest.mark.parametrize("service", ["get_journal", "get_attendance"])
@pytest.mark.parametrize("user_kind", ["admin", "member", "restricted", "unknown"])
async def test_service_permissions(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    mock_client: AsyncMock,
    service: str,
    user_kind: str,
) -> None:
    """Only administrators may read child data through user-initiated actions."""
    user = MockUser(
        groups=[Group(name="Administrators", id=GROUP_ID_ADMIN, policy={})]
        if user_kind == "admin"
        else []
    )
    if user_kind != "unknown":
        user.add_to_hass(hass)
    if user_kind == "restricted":
        user.mock_policy({"entities": False})
    elif user_kind == "member":
        user.mock_policy({"entities": True})
    mock_client.get_journals.reset_mock()
    mock_client.get_subscription_days.reset_mock()
    call = hass.services.async_call(
        DOMAIN,
        service,
        {"child": _child_device(device_registry, init_integration)},
        context=Context(user_id=user.id),
        blocking=True,
        return_response=True,
    )
    if user_kind == "admin":
        assert await call
    else:
        with pytest.raises(UnknownUser if user_kind == "unknown" else Unauthorized):
            await call
        mock_client.get_journals.assert_not_awaited()
        mock_client.get_subscription_days.assert_not_awaited()


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"start_date": "2026-04-02", "end_date": "2026-04-01"}, "invalid_date_range"),
        ({"start_date": "2026-01-01", "end_date": "2026-06-01"}, "date_range_too_long"),
    ],
)
async def test_invalid_ranges(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    data: dict[str, str],
    match: str,
) -> None:
    """Test invalid date ranges are refused."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "get_journal",
            {"child": _child_device(device_registry, init_integration), **data},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == match


async def test_invalid_child(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test devices that aren't children are refused."""
    other_entry = MockConfigEntry(domain="other")
    other_entry.add_to_hass(hass)
    other = device_registry.async_get_or_create(
        config_entry_id=other_entry.entry_id, identifiers={("other", "x")}
    )
    # A device of another integration that happens to use a "toddle" identifier.
    spoofed = device_registry.async_get_or_create(
        config_entry_id=other_entry.entry_id, identifiers={(DOMAIN, CHILD_UUID)}
    )
    for device_id in ("unknown", other.id, spoofed.id):
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(
                DOMAIN,
                "get_attendance",
                {"child": device_id},
                blocking=True,
                return_response=True,
            )
        assert err.value.translation_key == "invalid_child"


async def test_entry_not_loaded(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test actions on an unloaded entry are refused."""
    device_id = _child_device(device_registry, init_integration)
    await hass.config_entries.async_unload(init_integration.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "get_journal",
            {"child": device_id},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "entry_not_loaded"


@pytest.mark.parametrize("service", ["get_journal", "get_attendance"])
async def test_api_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    mock_client: AsyncMock,
    service: str,
) -> None:
    """Test API errors are raised as Home Assistant errors."""
    mock_client.get_journals.side_effect = ToddleConnectionError("down")
    mock_client.get_subscription_days.side_effect = ToddleConnectionError("down")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            service,
            {"child": _child_device(device_registry, init_integration)},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "service_failed"
