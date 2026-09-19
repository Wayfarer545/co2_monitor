"""Config and options flow for the ZyTemp CO2 integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CO2_THRESHOLD_MAX,
    CO2_THRESHOLD_MIN,
    CONF_CO2_CRITICAL,
    CONF_CO2_WARNING,
    CONF_TEMPERATURE_OFFSET,
    DEFAULT_CO2_CRITICAL,
    DEFAULT_CO2_WARNING,
    DEFAULT_TEMPERATURE_OFFSET,
    DEVICE_NAME,
    DOMAIN,
    TEMPERATURE_OFFSET_LIMIT,
)
from .device import DeviceNotFound, ZyTempDevice, find_device_paths

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CO2_WARNING, default=DEFAULT_CO2_WARNING): NumberSelector(
            NumberSelectorConfig(
                min=CO2_THRESHOLD_MIN,
                max=CO2_THRESHOLD_MAX,
                step=50,
                unit_of_measurement="ppm",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_CO2_CRITICAL, default=DEFAULT_CO2_CRITICAL): NumberSelector(
            NumberSelectorConfig(
                min=CO2_THRESHOLD_MIN,
                max=CO2_THRESHOLD_MAX,
                step=50,
                unit_of_measurement="ppm",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_TEMPERATURE_OFFSET, default=DEFAULT_TEMPERATURE_OFFSET
        ): NumberSelector(
            NumberSelectorConfig(
                min=-TEMPERATURE_OFFSET_LIMIT,
                max=TEMPERATURE_OFFSET_LIMIT,
                step=0.1,
                unit_of_measurement="°C",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)


def _probe_device() -> None:
    """Open the sensor briefly to prove it answers. Blocking."""
    device = ZyTempDevice()
    device.open()
    device.close()


class ZyTempConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle adding the sensor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the sensor found on this machine.

        There is nothing to configure: the device carries no serial number worth
        the name, and its hidraw node moves between replugs, so it is located
        afresh every time rather than recorded here.
        """
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        paths = await self.hass.async_add_executor_job(find_device_paths)

        if not paths:
            errors["base"] = "no_device"
        elif user_input is not None:
            try:
                await self.hass.async_add_executor_job(_probe_device)
            except DeviceNotFound:
                errors["base"] = "no_device"
            except PermissionError:
                errors["base"] = "permission_denied"
            except OSError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=DEVICE_NAME, data={})

        return self.async_show_form(
            step_id="user",
            errors=errors,
            description_placeholders={"path": paths[0] if paths else "-"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ZyTempOptionsFlow:
        """Return the options flow that tunes the alarm thresholds."""
        return ZyTempOptionsFlow()


class ZyTempOptionsFlow(OptionsFlow):
    """Let the user tune the alarm thresholds and the temperature offset."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the thresholds."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_CO2_CRITICAL] <= user_input[CONF_CO2_WARNING]:
                errors[CONF_CO2_CRITICAL] = "critical_not_above_warning"
            else:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )
