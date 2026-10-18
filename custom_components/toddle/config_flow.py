"""Config flow for the Toddle integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import uuid

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import probatio

from .api import (
    Parent,
    ToddleAuthenticationError,
    ToddleClient,
    ToddleConnectionError,
    ToddleError,
    ToddleInvalidTenantError,
)
from .const import (
    CONF_DEVICE_ID,
    CONF_TENANT,
    DEFAULT_TENANT,
    DEVICE_NAME,
    DOMAIN,
    LOGGER,
)

EMAIL_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
)
PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)


def _credentials_schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(
                CONF_EMAIL, default=defaults.get(CONF_EMAIL, probatio.UNDEFINED)
            ): (EMAIL_SELECTOR),
            probatio.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
            probatio.Required(
                CONF_TENANT, default=defaults.get(CONF_TENANT, DEFAULT_TENANT)
            ): TextSelector(),
        }
    )


def _without_password(user_input: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return form input to echo back, never including the password."""
    if user_input is None:
        return None
    return {k: v for k, v in user_input.items() if k != CONF_PASSWORD}


class ToddleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Toddle."""

    VERSION = 1
    MINOR_VERSION = 1

    async def _async_validate(
        self, data: Mapping[str, Any], device_id: str
    ) -> tuple[Parent | None, dict[str, str]]:
        """Log in and return the parent account, or form errors."""
        client = ToddleClient(
            async_get_clientsession(self.hass),
            data[CONF_EMAIL],
            data[CONF_PASSWORD],
            tenant=data[CONF_TENANT],
            device_id=device_id,
            device_name=DEVICE_NAME,
        )
        try:
            return await client.get_me(), {}
        except ToddleInvalidTenantError:
            return None, {CONF_TENANT: "invalid_tenant"}
        except ToddleAuthenticationError:
            return None, {"base": "invalid_auth"}
        except ToddleConnectionError:
            return None, {"base": "cannot_connect"}
        except ToddleError:
            LOGGER.exception("Unexpected response from the Toddle API")
            return None, {"base": "unknown"}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_TENANT] = user_input[CONF_TENANT].strip().lower()
            device_id = str(uuid.uuid4())
            parent, errors = await self._async_validate(user_input, device_id)
            if parent is not None:
                await self.async_set_unique_id(parent.uuid)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=parent.name or user_input[CONF_EMAIL],
                    data={**user_input, CONF_DEVICE_ID: device_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _credentials_schema({}), _without_password(user_input)
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle rejected credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            parent, errors = await self._async_validate(
                data, entry.data[CONF_DEVICE_ID]
            )
            if parent is not None:
                await self.async_set_unique_id(parent.uuid)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_PASSWORD): PASSWORD_SELECTOR}
            ),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the credentials or tenant of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_TENANT] = user_input[CONF_TENANT].strip().lower()
            parent, errors = await self._async_validate(
                user_input, entry.data[CONF_DEVICE_ID]
            )
            if parent is not None:
                await self.async_set_unique_id(parent.uuid)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _credentials_schema(entry.data), _without_password(user_input)
            ),
            errors=errors,
        )
