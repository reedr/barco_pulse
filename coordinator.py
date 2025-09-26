"""Coordinator."""

from datetime import timedelta
import logging
from typing import Self

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .device import BarcoDevice

_LOGGER = logging.getLogger(__name__)

class BarcoCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry[Self], device: BarcoDevice
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Barco Coordinator",
            config_entry=config_entry,
            update_interval=timedelta(seconds=30),
            setup_method=self.async_init,
            update_method=self._async_update_data,
            always_update=False,
        )
        self._device = device

    @property
    def device(self) -> BarcoDevice:
        """The device handle."""
        return self._device

    async def async_init(self):
        """Init the device."""
        await self.device.async_init(self.update_callback)

    async def _async_update_data(self):
        """Polling update."""
        try:
            await self.device.update_data()
        except Exception as err:
            _LOGGER.error("Error updating data: %s", err)
            raise UpdateFailed(err) from err
        return self.device.data

    @callback
    def update_callback(self, data):
        """Incoming data callback."""
        self.hass.add_job(self.async_set_updated_data, data)

type BarcoConfigEntry = ConfigEntry[Self]
