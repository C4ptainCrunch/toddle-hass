"""Base entity for the Toddle integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Child
from .const import DOMAIN
from .coordinator import ChildData, ToddleConfigEntry, ToddleDataUpdateCoordinator


def child_device_info(child: Child, data: ChildData | None) -> DeviceInfo:
    """Return device info for a child.

    The daycare and group are shown where Home Assistant would normally show
    the manufacturer and model.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, child.uuid)},
        name=child.first_name,
        manufacturer=data.daycare if data else None,
        model=data.group if data else None,
        serial_number=child.child_code,
        entry_type=DeviceEntryType.SERVICE,
    )


class ToddleChildEntity(CoordinatorEntity[ToddleDataUpdateCoordinator]):
    """An entity that represents an aspect of one child."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ToddleDataUpdateCoordinator,
        child: Child,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.child_uuid = child.uuid
        self._attr_unique_id = f"{child.uuid}_{description.key}"
        self._attr_device_info = child_device_info(
            child, coordinator.data.children.get(child.uuid)
        )

    @property
    def child_data(self) -> ChildData | None:
        """Return the latest data for this child."""
        return self.coordinator.data.children.get(self.child_uuid)

    @property
    def available(self) -> bool:
        """Return whether the child is still part of the account."""
        return super().available and self.child_data is not None


def async_setup_child_entities(
    entry: ToddleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[ToddleDataUpdateCoordinator, ChildData], Iterable[Entity]],
) -> None:
    """Add entities for every child, including children linked later on."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_children() -> None:
        # Children that left had their device (and entities) removed; forget
        # them so they are recreated should they ever come back.
        known.intersection_update(coordinator.data.children)
        new = [
            data
            for uuid, data in coordinator.data.children.items()
            if uuid not in known
        ]
        if not new:
            return
        known.update(data.child.uuid for data in new)
        async_add_entities(
            entity for data in new for entity in factory(coordinator, data)
        )

    _add_new_children()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_children))
