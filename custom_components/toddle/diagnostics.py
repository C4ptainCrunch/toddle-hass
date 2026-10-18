"""Diagnostics support for the Toddle integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID
from .coordinator import ToddleConfigEntry, daycare_now

TO_REDACT_ENTRY = {CONF_EMAIL, CONF_PASSWORD, CONF_DEVICE_ID, "unique_id", "title"}
TO_REDACT_DATA = {
    "uuid",
    "name",
    "subscription_day_uuid",
    "display_name",
    "birth_date",
    "child_code",
    "qr_code_url",
    "message",
    "remark",
    "absence",
    "exception",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ToddleConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    children = [
        {
            "child": asdict(data.child),
            "today": data.today.isoformat(),
            "status": (
                data.today_day.status_at(daycare_now()).value
                if data.today_day
                else None
            ),
            "days": [asdict(day) for day in data.days],
            "journals": [asdict(entry) for entry in data.journals],
        }
        for data in coordinator.data.children.values()
    ]
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT_ENTRY),
        "update_interval": str(coordinator.update_interval),
        "last_update_success": coordinator.last_update_success,
        "children": async_redact_data(children, TO_REDACT_DATA),
    }
