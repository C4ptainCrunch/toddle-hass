"""Tests for the Toddle config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.toddle.api import (
    Parent,
    ToddleAuthenticationError,
    ToddleConnectionError,
    ToddleInvalidTenantError,
    ToddleResponseError,
)
from custom_components.toddle.const import CONF_DEVICE_ID, CONF_TENANT, DOMAIN

from .conftest import ENTRY_DATA, PARENT_UUID

USER_INPUT = {
    CONF_EMAIL: "sofie@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_TENANT: " Brussel ",
}

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


async def test_user_flow(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """Test the happy path."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sofie Peeters"
    assert result["result"].unique_id == PARENT_UUID
    data = result["data"]
    assert data[CONF_EMAIL] == "sofie@example.com"
    assert data[CONF_PASSWORD] == "hunter2"
    assert data[CONF_TENANT] == "brussel"
    assert len(data[CONF_DEVICE_ID]) == 36


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ToddleAuthenticationError, {"base": "invalid_auth"}),
        (ToddleInvalidTenantError, {"tenant": "invalid_tenant"}),
        (ToddleConnectionError, {"base": "cannot_connect"}),
        (ToddleResponseError("boom"), {"base": "unknown"}),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    side_effect: Exception,
    error: dict[str, str],
) -> None:
    """Test errors are shown and the flow can recover."""
    mock_client.get_me.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == error

    mock_client.get_me.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_without_name(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """Test the email is used as title when the account has no name."""
    mock_client.get_me.return_value = Parent(
        uuid=PARENT_UUID, given_name="", family_name="", email="x@example.com"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["title"] == "sofie@example.com"


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test the same account can't be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test re-authentication."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["email"] == "sofie@example.com"

    mock_client.get_me.side_effect = ToddleAuthenticationError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.get_me.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {**ENTRY_DATA, CONF_PASSWORD: "new-password"}


async def test_reauth_wrong_account(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test re-authentication with another account is refused."""
    mock_config_entry.add_to_hass(hass)
    mock_client.get_me.return_value = Parent(
        uuid="other", given_name="A", family_name="B", email="a@example.com"
    )
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert mock_config_entry.data == ENTRY_DATA


async def test_reconfigure(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test reconfiguration."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    mock_client.get_me.side_effect = ToddleConnectionError
    new = {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "pw", CONF_TENANT: "Gent"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.get_me.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {
        **ENTRY_DATA,
        CONF_EMAIL: "new@example.com",
        CONF_PASSWORD: "pw",
        CONF_TENANT: "gent",
    }


async def test_reconfigure_wrong_account(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test reconfiguring to another account is refused."""
    mock_config_entry.add_to_hass(hass)
    mock_client.get_me.return_value = Parent(
        uuid="other", given_name="A", family_name="B", email="a@example.com"
    )
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
