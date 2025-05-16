"""Coordinator."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .device import BarcoDevice

_LOGGER = logging.getLogger(__name__)

type BarcoConfigEntry = ConfigEntry[BarcoCoordinator]


class BarcoCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(
        self, hass: HomeAssistant, config_entry: BarcoConfigEntry, device: BarcoDevice
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Barco Coordinator",
            config_entry=config_entry,
            setup_method=self.async_init,
            update_method=self.async_update,
            always_update=False,
        )
        self._device = device

    @property
    def device(self) -> BarcoDevice:
        """The device handle."""
        return self._device

    async def async_init(self):
        """Init the device."""
        _LOGGER.debug("async_init")
        await self.device.async_init(self.update_callback)

    async def async_update(self):
        """Don't poll."""
        _LOGGER.debug("async_update")
        await self.device.update_data()
        return self.device.data

    @callback
    def update_callback(self, data):
        """Incoming data callback."""
        self.hass.add_job(self.async_set_updated_data, data)
