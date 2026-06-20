"""Config flow for Annke integration."""
from __future__ import annotations

import voluptuous as vol
import requests
from requests.auth import HTTPDigestAuth

from homeassistant import config_entries
from homeassistant.data_entry_flow import AbortFlow

from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN


def _test_connection_sync(host: str, username: str, password: str) -> str:
    """Returns device name on success, raises on failure."""
    r = requests.get(
        f"http://{host}/ISAPI/System/deviceInfo",
        auth=HTTPDigestAuth(username, password),
        timeout=10,
    )
    r.raise_for_status()
    from xml.etree import ElementTree as ET
    root = ET.fromstring(r.text)
    name = root.find("{http://www.std-cgi.com/ver20/XMLSchema}deviceName")
    return name.text if name is not None else "Annke"


class AnnkeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        title = "Annke"

        if user_input is not None:
            try:
                title = await self.hass.async_add_executor_job(
                    _test_connection_sync,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{title} ({user_input[CONF_HOST]})",
                    data=user_input,
                )
            except AbortFlow:
                raise
            except requests.HTTPError as e:
                errors["base"] = "invalid_auth" if e.response.status_code in (401, 403) else "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_USERNAME, default="admin"): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )
