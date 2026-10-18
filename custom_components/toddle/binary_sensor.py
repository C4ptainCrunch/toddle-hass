"""Binary sensors for the Toddle integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ToddleConfigEntry
from .entity import ToddleChildEntity, async_setup_child_entities

PARALLEL_UPDATES = 0

AT_DAYCARE = BinarySensorEntityDescription(
    key="at_daycare",
    translation_key="at_daycare",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToddleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Toddle binary sensors."""
    async_setup_child_entities(
        entry,
        async_add_entities,
        lambda coordinator, data: [
            ToddleAtDaycareSensor(coordinator, data.child, AT_DAYCARE)
        ],
    )


class ToddleAtDaycareSensor(ToddleChildEntity, BinarySensorEntity):
    """Whether a child is currently checked in at daycare."""

    @property
    def is_on(self) -> bool | None:
        """Return true while the child is checked in."""
        if (data := self.child_data) is None:
            return None
        return day.is_present if (day := data.today_day) else False
