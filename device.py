"""Stewart Barco Device."""

import asyncio
import json
import logging

from homeassistant.core import HomeAssistant, callback

from .const import Barco_CONNECT_TIMEOUT, Barco_LOGIN_TIMEOUT, Barco_PORT

_LOGGER = logging.getLogger(__name__)

DEVICE_SYSTEM_STATE = "system.state"
DEVICE_INLET_T = "environment.temperature.inlet.value"
DEVICE_OUTLET_T = "environment.temperature.outlet.value"
DEVICE_LASER_STATUS = "illumination.sources.laser.status"
DEVICE_LASER_ON = "laser_on"
DEVICE_HDMI_SIGNAL = "image.connector.hdmi.detectedsignal"
DEVICE_OUTPUT_SIZE = "image.resolution.processing.size"
DEVICE_INPUT_ACTIVE = "input_active"
DEVICE_INPUT_SIGNAL = "input_signal"
DEVICE_OUTPUT_HRES = "output_hres"
DEVICE_OUTPUT_VRES = "output_vres"
DEVICE_OUTPUT_RES = "output_res"
DEVICE_MAINBOARD_T = "environment.temperature.mainboard.value"
DEVICE_ILLUM_STATE = "illumination.state"
DEVICE_ILLUM_ON = "illumination_on"

PROPERTY_SUBS = [
    DEVICE_SYSTEM_STATE,
    DEVICE_INLET_T,
    DEVICE_OUTLET_T,
    DEVICE_MAINBOARD_T,
    DEVICE_LASER_STATUS,
    DEVICE_HDMI_SIGNAL,
    DEVICE_OUTPUT_SIZE,
    DEVICE_ILLUM_STATE
]

class BarcoDevice:
    """Represents a single Barco device."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str
    ) -> None:
        """Set up class."""

        self._hass = hass
        self._host = host
        self._device_id = f"Barco:{host}"
        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter
        self._init_event = asyncio.Event()
        self._online = False
        self._callback = None
        self._listener = None
        self._request_id = None
        self._requests = {}
        self._data = {}

    @property
    def device_id(self) -> str:
        """Use the mac."""
        return self._device_id

    @property
    def online(self) -> bool:
        """Return status."""
        return self._online

    @property
    def data(self) -> dict:
        """Return data."""
        return self._data

    @property
    def sensors(self) -> list[str]:
        """Return the sensor names."""
        return PROPERTY_SUBS

    def get_sensor_value(self, name: str):
        """Return the sensor."""
        return self._data.get(name)


    async def open_connection(self, test: bool = False) -> bool:
        """Establish a connection."""
        if self.online:
            return True

        try:
            _LOGGER.debug("Establish new connection")
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, Barco_PORT),
                timeout=Barco_CONNECT_TIMEOUT,
            )
            self._request_id = 1
            self.send_request("property.get", {"property": [DEVICE_SYSTEM_STATE]})
            resp = await asyncio.wait_for(
                self._reader.read(1000), timeout=Barco_LOGIN_TIMEOUT
            )
            result = self.decode_response(resp)
            if result is None:
                return False
            if test:
                self._writer.close()
            else:
                self._data[DEVICE_SYSTEM_STATE] = result["result"]
                self._online = True
                self._listener = asyncio.create_task(self.listener())

        except (TimeoutError, OSError, asyncio.IncompleteReadError) as err:
            self._online = False
            _LOGGER.error("Connect sequence error %s", err)
            raise ConnectionError("Connect sequence error") from err

        return True

    def send_request (self, method: str, params: dict) -> None:
        """Format and send command."""
        req_id = self._request_id
        self._request_id += 1
        req = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
        reqstr = json.dumps(req)
        _LOGGER.debug("-> %s", reqstr)
        self._requests[req_id] = req
        self._writer.write(reqstr.encode("ascii"))
        return req_id

    def decode_response (self, resp: str) -> dict | None:
        """Decode the json response."""
        try:
            _LOGGER.debug("<- %s", resp)
            jresp = json.loads(resp)
            if jresp.get("jsonrpc") == "2.0" and "error" not in jresp:
                return jresp

        except json.JSONDecodeError as exc:
            _LOGGER.error("Decode error: %s", exc)

        return None

    async def test_connection(self) -> bool:
        """Test a connect."""
        return await self.open_connection(test=True)

    async def send_command(self, method: str, params: str) -> int:
        """Make an API call."""
        if await self.open_connection():
            return self.send_request(method, params)
        return -1

    async def update_data(self) -> bool:
        """Stuff that has to be polled."""
        # return await self.send_command("environment.getcontrolblocks",{"type": "Sensor", "valuetype": "Temperature"})
        return True

    @property
    def is_on(self) -> bool:
        """Is Projector on."""
        return self._data.get(DEVICE_SYSTEM_STATE) in ["on", "conditioning"]

    async def turn_on(self) -> bool:
        """Turn on the power."""
        return self.send_command("system.poweron", "[]") > 0

    async def turn_off(self) -> bool:
        """Turn on the power."""
        return self.send_command("system.poweroff", "[]") > 0

    async def async_init(self, data_callback: callback) -> dict:
        """Query position and wait for response."""
        await self.send_command("property.subscribe",{"property": PROPERTY_SUBS})
        await asyncio.wait_for(self._init_event.wait(), timeout=Barco_LOGIN_TIMEOUT)
        self._callback = data_callback
        await self.send_command("property.get",{"property": PROPERTY_SUBS})
        return self._data

    async def listener(self) -> None:
        """Listen for status updates from device."""

        while True:
            try:
                buf = await self._reader.read(4096)
                if len(buf) == 0:
                    _LOGGER.error("Connection closed")
                    break
                resp = self.decode_response(buf)
                if resp is None:
                    continue

                req_id = resp.get("id")
                if req_id is not None:
                    req = self._requests[req_id]
                    _LOGGER.debug("req_id=%d req=%s", req_id, req)
                    if req is not None:
                        del self._requests[req_id]
                        if req["method"] == "property.subscribe":
                            _LOGGER.debug("listener initialized")
                            self._init_event.set()
                        elif req["method"] == "property.get":
                            self.property_update(resp.get("result"))
                elif resp.get("method") == "property.changed":
                    self.property_update(resp["params"]["property"][0])

            except asyncio.IncompleteReadError as err:
                _LOGGER.error("Connection lost: %s", err)
                break

        self._writer.close()
        self._online = False

    def property_update(self, updates) -> None:
        """Update properties."""
        _LOGGER.debug("update: %s", updates)
        try:
            if updates is None:
                return
            for n, v in updates.items():
                if n == DEVICE_HDMI_SIGNAL:
                    self._data[DEVICE_INPUT_ACTIVE] = v["active"]
                    self._data[DEVICE_INPUT_SIGNAL] = v["name"]
                elif n == DEVICE_OUTPUT_SIZE:
                    pixels = self._data[DEVICE_OUTPUT_HRES] = v["pixels"]
                    lines = self._data[DEVICE_OUTPUT_VRES] = v["lines"]
                    self._data[DEVICE_OUTPUT_RES] = f"{pixels}x{lines}"
                elif n in (DEVICE_INLET_T, DEVICE_OUTLET_T, DEVICE_MAINBOARD_T):
                    self._data[n] = (v / 5 * 9) + 32
                elif n == DEVICE_ILLUM_STATE:
                    self._data[DEVICE_ILLUM_ON] = (v == "On")
                elif n == DEVICE_LASER_STATUS:
                    self._data[DEVICE_LASER_ON] = (v == "On")
                    self._data[DEVICE_LASER_STATUS] = v
                else:
                    self._data[n] = v
                    if n == DEVICE_SYSTEM_STATE:
                        _LOGGER.info("Projector state: %s", v)
            if self._callback is not None:
                self._callback(self._data)

        except Exception as exc:
            _LOGGER.error("Exception in property update: %s", exc)
