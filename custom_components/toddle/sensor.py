"""Sensors for the Toddle integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import JournalEntry, PresenceStatus
from .coordinator import ChildData, ToddleConfigEntry, daycare_now
from .entity import ToddleChildEntity, async_setup_child_entities

PARALLEL_UPDATES = 0

# Home Assistant limits states to 255 characters; the full text is kept in
# the attributes.
MAX_STATE_LENGTH = 255


def _truncate(text: str) -> str:
    if len(text) <= MAX_STATE_LENGTH:
        return text
    return text[: MAX_STATE_LENGTH - 1].rstrip() + "…"


def _journal_attributes(entry: JournalEntry | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "message": entry.message,
        "type": entry.type.lower(),
        "happened_at": entry.happened_at.isoformat(),
        "priority": entry.priority,
    }


def _status(data: ChildData) -> str:
    day = data.today_day
    return (day.status_at(daycare_now()) if day else PresenceStatus.NO_DAYCARE).value


def _time_at_daycare(data: ChildData) -> float | None:
    if (day := data.today_day) is None or not day.presences:
        return None
    return round(day.time_present(daycare_now()).total_seconds() / 60)


@dataclass(frozen=True, kw_only=True)
class ToddleSensorEntityDescription(SensorEntityDescription):
    """Describes a Toddle sensor."""

    value_fn: Callable[[ChildData], str | int | float | date | datetime | None]
    attributes_fn: Callable[[ChildData], dict[str, Any] | None] = lambda _: None


SENSORS: tuple[ToddleSensorEntityDescription, ...] = (
    ToddleSensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in PresenceStatus],
        value_fn=_status,
    ),
    ToddleSensorEntityDescription(
        key="check_in",
        translation_key="check_in",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: day.check_in if (day := data.today_day) else None,
    ),
    ToddleSensorEntityDescription(
        key="check_out",
        translation_key="check_out",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: day.check_out if (day := data.today_day) else None,
    ),
    ToddleSensorEntityDescription(
        key="scheduled_drop_off",
        translation_key="scheduled_drop_off",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            day.scheduled_start
            if (day := data.today_day) and day.is_attending
            else None
        ),
    ),
    ToddleSensorEntityDescription(
        key="scheduled_pick_up",
        translation_key="scheduled_pick_up",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            day.scheduled_end if (day := data.today_day) and day.is_attending else None
        ),
    ),
    ToddleSensorEntityDescription(
        key="time_at_daycare",
        translation_key="time_at_daycare",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=_time_at_daycare,
    ),
    ToddleSensorEntityDescription(
        key="next_daycare_day",
        translation_key="next_daycare_day",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: day.date if (day := data.next_day) else None,
    ),
    ToddleSensorEntityDescription(
        key="latest_journal_entry",
        translation_key="latest_journal_entry",
        value_fn=lambda data: (
            _truncate(entry.message) if (entry := data.latest_journal()) else None
        ),
        attributes_fn=lambda data: _journal_attributes(data.latest_journal()),
    ),
    ToddleSensorEntityDescription(
        key="last_meal",
        translation_key="last_meal",
        value_fn=lambda data: (
            _truncate(entry.message)
            if (entry := data.latest_journal("NUTRITION"))
            else None
        ),
        attributes_fn=lambda data: _journal_attributes(
            data.latest_journal("NUTRITION")
        ),
    ),
    ToddleSensorEntityDescription(
        key="last_nap",
        translation_key="last_nap",
        value_fn=lambda data: (
            _truncate(entry.message)
            if (entry := data.latest_journal("SLEEP"))
            else None
        ),
        attributes_fn=lambda data: _journal_attributes(data.latest_journal("SLEEP")),
    ),
    ToddleSensorEntityDescription(
        key="journal_entries_today",
        translation_key="journal_entries_today",
        value_fn=lambda data: len(data.journals_today),
    ),
    ToddleSensorEntityDescription(
        key="remark",
        translation_key="remark",
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            _truncate(" — ".join(filter(None, (day.absence, day.remark))))
            if (day := data.today_day) and (day.absence or day.remark)
            else None
        ),
    ),
    ToddleSensorEntityDescription(
        key="group",
        translation_key="group",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.group,
    ),
    ToddleSensorEntityDescription(
        key="daycare",
        translation_key="daycare",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.daycare,
    ),
    ToddleSensorEntityDescription(
        key="birth_date",
        translation_key="birth_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.child.birth_date,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToddleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Toddle sensors."""
    async_setup_child_entities(
        entry,
        async_add_entities,
        lambda coordinator, data: (
            ToddleSensor(coordinator, data.child, description)
            for description in SENSORS
        ),
    )


class ToddleSensor(ToddleChildEntity, SensorEntity):
    """A sensor describing one aspect of a child's day."""

    entity_description: ToddleSensorEntityDescription
    _unrecorded_attributes = frozenset({"message"})

    @property
    def native_value(self) -> str | int | float | date | datetime | None:
        """Return the state of the sensor."""
        if (data := self.child_data) is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the full journal entry for journal sensors."""
        if (data := self.child_data) is None:
            return None
        return self.entity_description.attributes_fn(data)
