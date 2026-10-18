"""Event entities for the Toddle integration."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Child, JournalEntry
from .coordinator import ToddleConfigEntry, ToddleDataUpdateCoordinator
from .entity import ToddleChildEntity, async_setup_child_entities

PARALLEL_UPDATES = 0

# Journal types known to be used by daycares; anything else maps to "other".
JOURNAL_EVENT_TYPES = [
    "general",
    "nutrition",
    "sleep",
    "bowel_movement",
    "activity",
    "health",
    "other",
]

JOURNAL = EventEntityDescription(
    key="journal",
    translation_key="journal",
    event_types=JOURNAL_EVENT_TYPES,
)


def journal_event_type(entry: JournalEntry) -> str:
    """Return the event type for a journal entry."""
    event_type = entry.type.lower()
    return event_type if event_type in JOURNAL_EVENT_TYPES else "other"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToddleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Toddle journal event entities."""
    async_setup_child_entities(
        entry,
        async_add_entities,
        lambda coordinator, data: [
            ToddleJournalEvent(coordinator, data.child, JOURNAL)
        ],
    )


class ToddleJournalEvent(ToddleChildEntity, EventEntity):
    """Fires an event for every new journal entry about a child."""

    def __init__(
        self,
        coordinator: ToddleDataUpdateCoordinator,
        child: Child,
        description: EventEntityDescription,
    ) -> None:
        """Initialize the entity, treating entries already present as seen."""
        super().__init__(coordinator, child, description)
        data = self.child_data
        self._seen = {entry.uuid for entry in data.journals} if data else set()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire events for journal entries that were not seen before."""
        if (data := self.child_data) is not None:
            for entry in data.journals:
                if entry.uuid in self._seen:
                    continue
                self._seen.add(entry.uuid)
                self._trigger_event(
                    journal_event_type(entry),
                    {
                        "message": entry.message,
                        "journal_type": entry.type,
                        "happened_at": entry.happened_at.isoformat(),
                        "created_at": entry.created_at.isoformat(),
                        "sender": entry.sender,
                        "priority": entry.priority,
                        "uuid": entry.uuid,
                    },
                )
        super()._handle_coordinator_update()
