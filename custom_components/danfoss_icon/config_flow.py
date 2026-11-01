"""Config flow for Danfoss Icon."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import CannotConnect, InvalidOtp, NotIcon, PairingResult, pair
from .const import (
    CONF_HOUSE_NAME,
    CONF_OTP,
    CONF_PEER_ID,
    CONF_PRIVATE_KEY,
    CONF_USER_NAME,
    DEFAULT_USER_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OTP): str,
        vol.Optional(CONF_USER_NAME, default=DEFAULT_USER_NAME): str,
    }
)


class IconConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair Home Assistant with a house shared from the Danfoss Icon app."""

    VERSION = 1

    async def _pair(self, user_input: dict[str, Any]) -> tuple[PairingResult | None, dict[str, str]]:
        try:
            return await pair(user_input[CONF_OTP], user_input[CONF_USER_NAME]), {}
        except InvalidOtp:
            return None, {"base": "invalid_otp"}
        except CannotConnect:
            return None, {"base": "cannot_connect"}
        except NotIcon:
            return None, {"base": "not_icon"}
        except Exception:
            _LOGGER.exception("Unexpected error while pairing")
            return None, {"base": "unknown"}

    @staticmethod
    def _entry_data(result: PairingResult) -> dict[str, Any]:
        return {
            CONF_PRIVATE_KEY: result.private_key,
            CONF_PEER_ID: result.peer_id,
            CONF_HOUSE_NAME: result.house_name,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._pair(user_input)
            if result:
                # One entry per master controller
                await self.async_set_unique_id(result.peer_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=result.house_name, data=self._entry_data(result)
                )

        return self.async_show_form(step_id="user", data_schema=STEP_SCHEMA, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair again, for example after removing Home Assistant in the app."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._pair(user_input)
            if result:
                await self.async_set_unique_id(result.peer_id)
                self._abort_if_unique_id_mismatch(reason="wrong_house")
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data=self._entry_data(result)
                )

        return self.async_show_form(
            step_id="reconfigure", data_schema=STEP_SCHEMA, errors=errors
        )

