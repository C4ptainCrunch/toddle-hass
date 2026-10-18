"""The Toddle integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .api import ToddleClient
from .const import CONF_DEVICE_ID, CONF_TENANT, DEVICE_NAME, DOMAIN
from .coordinator import ToddleConfigEntry, ToddleDataUpdateCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Toddle actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ToddleConfigEntry) -> bool:
    """Set up Toddle from a config entry."""
    client = ToddleClient(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        tenant=entry.data[CONF_TENANT],
        device_id=entry.data[CONF_DEVICE_ID],
        device_name=DEVICE_NAME,
    )
    coordinator = ToddleDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ToddleConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ToddleConfigEntry, device: DeviceEntry
) -> bool:
    """Allow removing a child's device once the child left the account."""
    if entry.state is not ConfigEntryState.LOADED:
        return True
    children = entry.runtime_data.data.children
    return not any(
        domain == DOMAIN and identifier in children
        for domain, identifier in device.identifiers
    )
