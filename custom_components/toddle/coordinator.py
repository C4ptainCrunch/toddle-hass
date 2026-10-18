"""Data update coordinator for the Toddle integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    DAYCARE_TZ,
    Child,
    JournalEntry,
    SubscriptionDay,
    ToddleAuthenticationError,
    ToddleClient,
    ToddleError,
)
from .const import (
    ACTIVE_HOURS_END,
    ACTIVE_HOURS_START,
    ATTENDANCE_LOOKAHEAD_DAYS,
    DOMAIN,
    JOURNAL_LOOKBACK_DAYS,
    LOGGER,
    UPDATE_INTERVAL_ACTIVE,
    UPDATE_INTERVAL_IDLE,
)

type ToddleConfigEntry = ConfigEntry[ToddleDataUpdateCoordinator]


def daycare_now() -> datetime:
    """Return the current time in the daycare time zone."""
    return dt_util.now(DAYCARE_TZ)


def is_active_period(now: datetime) -> bool:
    """Return whether daycare activity is likely at the given time."""
    local = now.astimezone(DAYCARE_TZ)
    return local.weekday() < 5 and ACTIVE_HOURS_START <= local.time() < ACTIVE_HOURS_END


@dataclass(frozen=True, slots=True)
class ChildData:
    """Everything known about one child after a refresh."""

    child: Child
    today: date
    days: tuple[SubscriptionDay, ...]
    journals: tuple[JournalEntry, ...]

    @property
    def today_day(self) -> SubscriptionDay | None:
        """Return today's attendance record, if any."""
        return next((day for day in self.days if day.date == self.today), None)

    @property
    def group(self) -> str | None:
        """Return the group (department) of the nearest attendance day."""
        return next((day.department.name for day in self.days if day.department), None)

    @property
    def daycare(self) -> str | None:
        """Return the daycare of the nearest attendance day."""
        return next((day.daycare.name for day in self.days if day.daycare), None)

    @property
    def next_day(self) -> SubscriptionDay | None:
        """Return the next planned daycare day after today."""
        return next(
            (day for day in self.days if day.date > self.today and day.is_attending),
            None,
        )

    @property
    def journals_today(self) -> list[JournalEntry]:
        """Return today's journal entries, oldest first."""
        return [e for e in self.journals if e.happened_at.date() == self.today]

    def latest_journal(self, journal_type: str | None = None) -> JournalEntry | None:
        """Return the most recent journal entry, optionally of a given type."""
        for entry in reversed(self.journals):
            if journal_type is None or entry.type == journal_type:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class ToddleData:
    """Coordinator payload."""

    children: dict[str, ChildData]


class ToddleDataUpdateCoordinator(DataUpdateCoordinator[ToddleData]):
    """Fetch children, attendance and journal entries for an account."""

    config_entry: ToddleConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ToddleConfigEntry, client: ToddleClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._interval(daycare_now()),
        )
        self.client = client

    @staticmethod
    def _interval(now: datetime) -> timedelta:
        return UPDATE_INTERVAL_ACTIVE if is_active_period(now) else UPDATE_INTERVAL_IDLE

    async def _async_update_data(self) -> ToddleData:
        """Fetch the latest data from the API."""
        now = daycare_now()
        today = now.date()
        try:
            children = await self.client.get_children()
            results = await asyncio.gather(
                *(self._fetch_child(child, today) for child in children)
            )
        except ToddleAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except ToddleError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self.update_interval = self._interval(now)
        data = ToddleData(children={result.child.uuid: result for result in results})
        self._sync_devices(data)
        return data

    async def _fetch_child(self, child: Child, today: date) -> ChildData:
        days, journals = await asyncio.gather(
            self.client.get_subscription_days(
                child.uuid, today, today + timedelta(days=ATTENDANCE_LOOKAHEAD_DAYS)
            ),
            self.client.get_journals(
                child.uuid, today - timedelta(days=JOURNAL_LOOKBACK_DAYS), today
            ),
        )
        return ChildData(
            child=child, today=today, days=tuple(days), journals=tuple(journals)
        )

    def _sync_devices(self, data: ToddleData) -> None:
        """Keep child devices in line with the account.

        Devices of children no longer linked to the account are removed, and
        the daycare and group shown on a device follow the child around.
        """
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            child_uuid = next(
                (ident for domain, ident in device.identifiers if domain == DOMAIN),
                None,
            )
            if child_uuid is None:
                continue
            if (child := data.children.get(child_uuid)) is None:
                LOGGER.debug("Removing stale device %s", device.name)
                registry.async_remove_device(device.id)
            elif (device.manufacturer, device.model) != (child.daycare, child.group):
                registry.async_update_device(
                    device.id, manufacturer=child.daycare, model=child.group
                )
