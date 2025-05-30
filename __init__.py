"""Barco Pulse integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .coordinator import BarcoConfigEntry, BarcoCoordinator
from .device import BarcoDevice

_PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.REMOTE, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Set up Barco device from a config entry."""

    dev = BarcoDevice(
        hass,
        entry.data[CONF_HOST]
    )
    coord = BarcoCoordinator(hass, entry, dev)
    entry.runtime_data = coord
    await coord.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BarcoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
