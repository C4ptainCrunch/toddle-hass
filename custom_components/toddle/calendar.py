"""Calendars for the Toddle integration."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityDescription,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DAYCARE_TZ, JournalEntry, PresenceStatus, SubscriptionDay, ToddleError
from .const import DOMAIN
from .coordinator import ChildData, ToddleConfigEntry, daycare_now
from .entity import ToddleChildEntity, async_setup_child_entities

# Calendar queries hit the API directly; don't hammer it.
PARALLEL_UPDATES = 1

ATTENDANCE = CalendarEntityDescription(key="attendance", translation_key="attendance")
JOURNAL = CalendarEntityDescription(key="journal_calendar", translation_key="journal")

# Journal entries are moments; give them a short duration so they're visible.
JOURNAL_EVENT_DURATION = timedelta(minutes=15)
# Language-neutral markers for the journal entry types.
JOURNAL_ICONS = {
    "GENERAL": "💬",
    "NUTRITION": "🍽️",
    "SLEEP": "😴",
    "BOWEL_MOVEMENT": "🧷",
    "ACTIVITY": "🎨",
    "HEALTH": "🩺",
}
SUMMARY_LENGTH = 80


def day_events(day: SubscriptionDay, now: datetime) -> list[CalendarEvent]:
    """Turn an attendance day into calendar events."""
    details = [
        f"Group: {day.department.name}" if day.department else "",
        day.absence,
        day.remark,
    ]
    description = "\n".join(filter(None, details)) or None
    location = day.daycare.name if day.daycare else None

    if intervals := day.presence_intervals():
        return [
            CalendarEvent(
                start=start,
                # While checked in, stretch the event to the scheduled pick-up.
                end=end or max(day.scheduled_end or now, now + timedelta(minutes=1)),
                summary="At daycare",
                description=description,
                location=location,
                uid=f"{day.uuid}-presence-{index}",
            )
            for index, (start, end) in enumerate(intervals)
        ]
    if day.status_at(now) is PresenceStatus.ABSENT:
        return [
            CalendarEvent(
                start=day.date,
                end=day.date + timedelta(days=1),
                summary="Absent",
                description=description,
                location=location,
                uid=f"{day.uuid}-absent",
            )
        ]
    if not day.is_planned:
        return []
    return [
        CalendarEvent(
            start=start,
            end=end,
            summary="Daycare (planned)",
            description=description,
            location=location,
            uid=f"{day.uuid}-schedule-{index}",
        )
        for index, (start, end) in enumerate(day.schedule_intervals())
    ]


def journal_event(entry: JournalEntry) -> CalendarEvent:
    """Turn a journal entry into a calendar event."""
    # Messages often open with a greeting on its own line; keep it all on one line.
    text = " ".join(entry.message.split())
    if len(text) > SUMMARY_LENGTH:
        text = text[: SUMMARY_LENGTH - 1].rstrip() + "…"
    icon = JOURNAL_ICONS.get(entry.type, "📝")
    return CalendarEvent(
        start=entry.happened_at,
        end=entry.happened_at + JOURNAL_EVENT_DURATION,
        summary=f"{icon} {text}".rstrip(),
        description=entry.message or None,
        uid=entry.uuid,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ToddleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Toddle calendars."""
    async_setup_child_entities(
        entry,
        async_add_entities,
        lambda coordinator, data: [
            ToddleAttendanceCalendar(coordinator, data.child, ATTENDANCE),
            ToddleJournalCalendar(coordinator, data.child, JOURNAL),
        ],
    )


class ToddleCalendar(ToddleChildEntity, CalendarEntity):
    """Base class for calendars backed by the coordinator and the API."""

    def _known_events(self, data: ChildData, now: datetime) -> Iterable[CalendarEvent]:
        """Return events from the coordinator data, in chronological order."""
        raise NotImplementedError

    async def _fetch_events(
        self, start: date, end: date, now: datetime
    ) -> Iterable[CalendarEvent]:
        """Fetch events between two daycare dates from the API."""
        raise NotImplementedError

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        if (data := self.child_data) is None:
            return None
        now = daycare_now()
        return next(
            (e for e in self._known_events(data, now) if e.end_datetime_local > now),
            None,
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events within a time range."""
        try:
            events = await self._fetch_events(
                start_date.astimezone(DAYCARE_TZ).date(),
                end_date.astimezone(DAYCARE_TZ).date(),
                daycare_now(),
            )
        except ToddleError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="calendar_fetch_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return [
            event
            for event in events
            if event.end_datetime_local > start_date
            and event.start_datetime_local < end_date
        ]


class ToddleAttendanceCalendar(ToddleCalendar):
    """Planned and actual attendance of a child."""

    def _known_events(self, data: ChildData, now: datetime) -> Iterable[CalendarEvent]:
        return (event for day in data.days for event in day_events(day, now))

    async def _fetch_events(
        self, start: date, end: date, now: datetime
    ) -> Iterable[CalendarEvent]:
        days = await self.coordinator.client.get_subscription_days(
            self.child_uuid, start, end
        )
        return (event for day in days for event in day_events(day, now))


class ToddleJournalCalendar(ToddleCalendar):
    """Journal entries about a child, at the time they happened."""

    def _known_events(self, data: ChildData, now: datetime) -> Iterable[CalendarEvent]:
        return (journal_event(entry) for entry in data.journals)

    async def _fetch_events(
        self, start: date, end: date, now: datetime
    ) -> Iterable[CalendarEvent]:
        entries = await self.coordinator.client.get_journals(
            self.child_uuid, start, end
        )
        return (journal_event(entry) for entry in entries)
