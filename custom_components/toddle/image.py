"""Image entities for the Toddle integration."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import Child
from .coordinator import ToddleConfigEntry, ToddleDataUpdateCoordinator
from .entity import ToddleChildEntity, async_setup_child_entities

PARALLEL_UPDATES = 0

QR_CODE = ImageEntityDescription(
    key="qr_code",
    translation_key="qr_code",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToddleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Toddle image entities."""
    async_setup_child_entities(
        entry,
        async_add_entities,
        lambda coordinator, data: (
            [ToddleQrCodeImage(hass, coordinator, data.child, QR_CODE)]
            if data.child.qr_code_url
            else []
        ),
    )


class ToddleQrCodeImage(ToddleChildEntity, ImageEntity):
    """The check-in QR code of a child."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ToddleDataUpdateCoordinator,
        child: Child,
        description: ImageEntityDescription,
    ) -> None:
        """Initialize the entity."""
        ToddleChildEntity.__init__(self, coordinator, child, description)
        ImageEntity.__init__(self, hass)
        self._attr_image_url = child.qr_code_url
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Pick up a new QR code URL."""
        if (data := self.child_data) is not None and (
            data.child.qr_code_url != self._attr_image_url
        ):
            self._attr_image_url = data.child.qr_code_url
            self._cached_image = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()
