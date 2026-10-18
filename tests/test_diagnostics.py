"""Tests for the Toddle diagnostics."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from .conftest import BABY_UUID, CHILD_UUID


async def test_diagnostics(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    snapshot: SnapshotAssertion,
) -> None:
    """Test diagnostics are redacted."""
    result = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    assert result == snapshot(exclude=props("entry_id", "created_at", "modified_at"))
    text = str(result)
    for secret in (
        "hunter2",
        "sofie@example.com",
        "Emma Louise",
        "999999999",
        "Goed gegeten",
        "Voorbeeldcreche",
        "Voorbeeldgroep",
        CHILD_UUID,
        BABY_UUID,
    ):
        assert secret not in text
