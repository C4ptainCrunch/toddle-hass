"""Fixtures for the Toddle tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.toddle.api import (
    Child,
    JournalEntry,
    Parent,
    SubscriptionDay,
    ToddleClient,
)
from custom_components.toddle.const import CONF_DEVICE_ID, CONF_TENANT, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
PARENT_UUID = "e0000000-0000-4000-8000-000000000001"
CHILD_UUID = "e1000000-0000-4000-8000-000000000001"
BABY_UUID = "e1000000-0000-4000-8000-000000000002"
# A Tuesday afternoon, after Emma was picked up.
NOW = "2026-03-31 17:00:00+02:00"

ENTRY_DATA = {
    CONF_EMAIL: "sofie@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_TENANT: "brussel",
    CONF_DEVICE_ID: "f0000000-0000-4000-8000-000000000001",
}


def load_fixture(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


def fixture_children() -> list[Child]:
    """Return the children fixture as models."""
    return [Child.from_dict(c) for c in load_fixture("children.json")["data"]]


def fixture_days() -> list[SubscriptionDay]:
    """Return the attendance fixture as models."""
    return [
        SubscriptionDay.from_dict(d)
        for d in load_fixture("subscription_days.json")["data"]
    ]


def fixture_journals() -> list[JournalEntry]:
    """Return the journal fixture as models."""
    return [JournalEntry.from_dict(j) for j in load_fixture("journals.json")["data"]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture(autouse=True)
def frozen_time(freezer: Any) -> None:
    """Freeze time on a daycare day."""
    freezer.move_to(NOW)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Sofie Peeters",
        unique_id=PARENT_UUID,
        data=dict(ENTRY_DATA),
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent setting up the entry from the config flow."""
    with patch("custom_components.toddle.async_setup_entry", return_value=True) as mock:
        yield mock


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Return a mocked Toddle client used by setup and config flow."""
    client = AsyncMock(spec=ToddleClient)
    client.get_me.return_value = Parent.from_dict(load_fixture("me.json"))
    client.get_children.return_value = fixture_children()

    async def days(child_uuid: str, start: date, end: date) -> list[SubscriptionDay]:
        if child_uuid != CHILD_UUID:
            return []
        return [d for d in fixture_days() if start <= d.date <= end]

    async def journals(child_uuid: str, start: date, end: date) -> list[JournalEntry]:
        if child_uuid != CHILD_UUID:
            return []
        return [j for j in fixture_journals() if start <= j.happened_at.date() <= end]

    client.get_subscription_days.side_effect = days
    client.get_journals.side_effect = journals
    with (
        patch("custom_components.toddle.ToddleClient", return_value=client),
        patch("custom_components.toddle.config_flow.ToddleClient", return_value=client),
    ):
        yield client


@pytest.fixture
def platforms() -> list[str]:
    """Platforms to set up; all by default."""
    return []


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    platforms: list[str],
) -> MockConfigEntry:
    """Set up the integration."""
    mock_config_entry.add_to_hass(hass)
    if platforms:
        with patch("custom_components.toddle.PLATFORMS", platforms):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    else:
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable all entities by default."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
        new_callable=PropertyMock,
    ):
        yield
