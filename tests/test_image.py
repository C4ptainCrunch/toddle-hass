"""Tests for the Toddle QR code image."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
import respx
from syrupy.assertion import SnapshotAssertion

from custom_components.toddle.const import UPDATE_INTERVAL_IDLE

from .conftest import fixture_children


@pytest.fixture(autouse=True)
def fixed_token() -> Generator[None]:
    """Make image access tokens deterministic."""
    with patch(
        "homeassistant.components.image._RND.getrandbits", return_value=0xC0FFEE
    ):
        yield


ENTITY_ID = "image.emma_qr_code"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16


@pytest.fixture
def platforms() -> list[str]:
    """Only set up images."""
    return [Platform.IMAGE]


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_images(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot the image entities; children without QR code get none."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_image_content_and_update(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    hass_client: ClientSessionGenerator,
    respx_mock: respx.MockRouter,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the image is served and follows URL changes."""
    emma, baby = fixture_children()
    respx_mock.get(emma.qr_code_url).respond(
        content=PNG, headers={"Content-Type": "image/png"}
    )
    client = await hass_client()
    resp = await client.get(f"/api/image_proxy/{ENTITY_ID}")
    assert resp.status == HTTPStatus.OK
    assert await resp.read() == PNG

    before = hass.states.get(ENTITY_ID).state
    new_url = "https://example.com/qr-new.png"
    mock_client.get_children.return_value = [replace(emma, qr_code_url=new_url), baby]
    freezer.tick(UPDATE_INTERVAL_IDLE)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY_ID).state != before

    respx_mock.get(new_url).respond(
        content=PNG + b"2", headers={"Content-Type": "image/png"}
    )
    resp = await client.get(f"/api/image_proxy/{ENTITY_ID}")
    assert await resp.read() == PNG + b"2"
