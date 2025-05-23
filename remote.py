"""Remote platform."""

from collections.abc import Iterable
import logging
from typing import Any

from homeassistant.components.remote import RemoteEntity, RemoteEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BarcoConfigEntry, BarcoCoordinator
from .entity import BarcoEntity

_LOGGER = logging.getLogger(__name__)

REMOTE_DESC = RemoteEntityDescription(
    key="projector",
    translation_key="Projector"
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BarcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Remote entity."""
    coord = config_entry.runtime_data

    async_add_entities([BarcoRemote(coord)])


class BarcoRemote(RemoteEntity, BarcoEntity):
    """Screen as a Remote."""

    def __init__(self, coord: BarcoCoordinator) -> None:
        """Get going."""
        super().__init__(coord, REMOTE_DESC)

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self.coordinator.device.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        await self.coordinator.device.turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the device off."""
        await self.coordinator.device.turn_off()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send command to device."""
        await self.coordinator.device.send_command(command)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.schedule_update_ha_state()
