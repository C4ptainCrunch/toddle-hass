"""Actions for the Toddle integration."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service import async_register_admin_service
import probatio

from .api import JournalEntry, SubscriptionDay, ToddleError
from .const import (
    ATTR_CHILD,
    ATTR_END_DATE,
    ATTR_START_DATE,
    DOMAIN,
    MAX_SERVICE_RANGE_DAYS,
)
from .coordinator import ToddleConfigEntry, daycare_now

SERVICE_GET_JOURNAL = "get_journal"
SERVICE_GET_ATTENDANCE = "get_attendance"

SERVICE_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_CHILD): cv.string,
        probatio.Optional(ATTR_START_DATE): cv.date,
        probatio.Optional(ATTR_END_DATE): cv.date,
    }
)


def _resolve_child(
    hass: HomeAssistant, device_id: str
) -> tuple[ToddleConfigEntry, str]:
    """Return the loaded config entry and child UUID for a child device."""
    device = dr.async_get(hass).async_get(device_id)
    child_uuid = entry = None
    if device is not None:
        child_uuid = next(
            (ident for domain, ident in device.identifiers if domain == DOMAIN), None
        )
        entry = hass.config_entries.async_get_entry(device.config_entry_id)
    if child_uuid is None or entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_child",
            translation_placeholders={"device_id": device_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry": entry.title},
        )
    toddle_entry: ToddleConfigEntry = entry
    return toddle_entry, child_uuid


def _resolve_range(call: ServiceCall) -> tuple[date, date]:
    today = daycare_now().date()
    start: date = call.data.get(ATTR_START_DATE, today)
    end: date = call.data.get(ATTR_END_DATE, start)
    if end < start:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_date_range"
        )
    if end - start > timedelta(days=MAX_SERVICE_RANGE_DAYS):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="date_range_too_long",
            translation_placeholders={"days": str(MAX_SERVICE_RANGE_DAYS)},
        )
    return start, end


def _journal_to_dict(entry: JournalEntry) -> dict[str, Any]:
    return {
        "uuid": entry.uuid,
        "type": entry.type.lower(),
        "message": entry.message,
        "sender": entry.sender,
        "happened_at": entry.happened_at.isoformat(),
        "created_at": entry.created_at.isoformat(),
        "priority": entry.priority,
    }


def _day_to_dict(day: SubscriptionDay) -> dict[str, Any]:
    return {
        "date": day.date.isoformat(),
        "status": day.status_at(daycare_now()).value,
        "state": day.state,
        "group": day.department.name if day.department else None,
        "daycare": day.daycare.name if day.daycare else None,
        "scheduled": [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in day.schedule_intervals()
        ],
        "presences": [
            {"start": start.isoformat(), "end": end.isoformat() if end else None}
            for start, end in day.presence_intervals()
        ],
        "absence": day.absence or None,
        "remark": day.remark or None,
    }


def _api_error(err: ToddleError) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="service_failed",
        translation_placeholders={"error": str(err)},
    )


async def _async_get_journal(call: ServiceCall) -> ServiceResponse:
    entry, child_uuid = _resolve_child(call.hass, call.data[ATTR_CHILD])
    start, end = _resolve_range(call)
    try:
        entries = await entry.runtime_data.client.get_journals(child_uuid, start, end)
    except ToddleError as err:
        raise _api_error(err) from err
    return {"entries": [_journal_to_dict(e) for e in entries]}


async def _async_get_attendance(call: ServiceCall) -> ServiceResponse:
    entry, child_uuid = _resolve_child(call.hass, call.data[ATTR_CHILD])
    start, end = _resolve_range(call)
    try:
        days = await entry.runtime_data.client.get_subscription_days(
            child_uuid, start, end
        )
    except ToddleError as err:
        raise _api_error(err) from err
    return {"days": [_day_to_dict(day) for day in days]}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Toddle actions."""
    for name, handler in (
        (SERVICE_GET_JOURNAL, _async_get_journal),
        (SERVICE_GET_ATTENDANCE, _async_get_attendance),
    ):
        async_register_admin_service(
            hass,
            DOMAIN,
            name,
            handler,
            schema=SERVICE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
