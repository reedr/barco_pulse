"""Stewart Barco Device."""

import asyncio
import json
import logging
from wakeonlan import send_magic_packet

from homeassistant.core import HomeAssistant, callback

from .const import (
    MANUFACTURER,
    BARCO_CONNECT_TIMEOUT,
    BARCO_LOGIN_TIMEOUT,
    BARCO_PORT,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_SYSTEM_TARGETSTATE = "system.targetstate"
DEVICE_SYSTEM_STATE = "system.state"
DEVICE_INLET_T = "environment.temperature.inlet.value"
DEVICE_OUTLET_T = "environment.temperature.outlet.value"
DEVICE_LASER_STATUS = "illumination.sources.laser.status"
DEVICE_LASER_ON = "laser"
DEVICE_HDMI_SIGNAL = "image.connector.hdmi.detectedsignal"
DEVICE_OUTPUT_SIZE = "image.resolution.processing.size"
DEVICE_INPUT_ACTIVE = "input_active"
DEVICE_INPUT_SIGNAL = "input_signal"
DEVICE_OUTPUT_HRES = "output_hres"
DEVICE_OUTPUT_VRES = "output_vres"
DEVICE_OUTPUT_RES = "output_res"
DEVICE_MAINBOARD_T = "environment.temperature.mainboard.value"
DEVICE_ILLUM_STATE = "illumination.state"
DEVICE_ILLUM_ON = "illumination"
DEVICE_MODEL = "system.modelname"
DEVICE_SERIAL_NUM = "system.serialnumber"
DEVICE_INPUT_SOURCE = "image.window.main.source"
DEVICE_INPUT_SOURCE_LIST = "image.source.list"

PROPERTY_SUBS = [
    DEVICE_SYSTEM_TARGETSTATE,
    DEVICE_SYSTEM_STATE,
    DEVICE_INLET_T,
    DEVICE_OUTLET_T,
    DEVICE_MAINBOARD_T,
    DEVICE_LASER_STATUS,
    DEVICE_HDMI_SIGNAL,
    DEVICE_OUTPUT_SIZE,
    DEVICE_ILLUM_STATE,
    DEVICE_INPUT_SOURCE,
]

PROPERTY_INIT = PROPERTY_SUBS


class BarcoDevice:
    """Represents a single Barco device."""

    def __init__(self, hass: HomeAssistant, host: str, mac: str) -> None:
        """Set up class."""

        _LOGGER.info("Initialize Barco Pulse device (host=%s, mac=%s)", host, mac)
        self._hass = hass
        self._host = host
        self._mac = mac
        self._device_id = None
        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter
        self._init_event = asyncio.Event()
        self._online = False
        self._poweron_pending = False
        self._callback = None
        self._listener = None
        self._request_id = None
        self._requests = {}
        self._data = {}
        self._sleeping = True

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

    def _wake_on_lan(self) -> None:
        """Wake the device via wake on lan."""
        send_magic_packet(self._mac)

    async def wakeup(self) -> None:
        """Wake up the device."""
        _LOGGER.info("Attempting to wake projector at %s", self._mac)
        await self._hass.async_add_executor_job(self._wake_on_lan)

    async def check_connection(self, test: bool = False) -> None:
        """Establish a connection."""
        if self._online:
            if not self._writer.is_closing():
                return

            _LOGGER.debug("Closing connection in check_connection")
            self._connection_closed()
            if self._listener is not None:
                self._listener.cancel()
                self._listener = None

        try:
            _LOGGER.debug("Attempting to establish new connection")
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, BARCO_PORT),
                timeout=BARCO_CONNECT_TIMEOUT,
            )
            self._request_id = 1
            self.send_request(
                "property.get", {"property": [DEVICE_MODEL, DEVICE_SERIAL_NUM]}
            )
            resp = await asyncio.wait_for(
                self._reader.read(1000), timeout=BARCO_LOGIN_TIMEOUT
            )
            result = self.decode_response(resp)
            if result is None:
                return False
            for prop, val in result["result"].items():
                self._data[prop] = val
            self._device_id = f"{MANUFACTURER}:{self._data[DEVICE_SERIAL_NUM]}"
            if test:
                self._connection_closed()
            else:
                self._online = True
                self._sleeping = False
                self._listener = asyncio.create_task(self.listener())
                self.send_request("property.subscribe", {"property": PROPERTY_SUBS})
                await asyncio.wait_for(self._init_event.wait(), timeout=BARCO_LOGIN_TIMEOUT)
                self.send_request("property.get", {"property": PROPERTY_INIT})
                self.send_request("image.source.list", "[]")
                if self._poweron_pending:
                    self.send_request("system.poweron", "[]")
                    self._poweron_pending = False

        except Exception as err:
            _LOGGER.debug("Connection failed: %s", err)
            raise err

    def send_request(self, method: str, params: dict) -> None:
        """Format and send command."""
        req_id = self._request_id
        self._request_id += 1
        req = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
        reqstr = json.dumps(req)
        _LOGGER.debug("-> %s", reqstr)
        self._requests[req_id] = req
        self._writer.write(reqstr.encode("ascii"))
        return req_id

    def decode_response(self, resp: str) -> dict | None:
        """Decode the json response."""
        try:
            _LOGGER.debug("<- %s", resp)
            jresp = json.loads(resp)
            if jresp.get("jsonrpc") == "2.0" and "error" not in jresp:
                return jresp

        except json.JSONDecodeError as exc:
            _LOGGER.error("Decode error: %s", exc)

        return None

    async def test_connection(self) -> None:
        """Test a connect."""
        await self.wakeup()
        await self.check_connection(test=True)

    async def send_command(self, method: str, params: str) -> None:
        """Make an API call."""
        if not self._online and method in ("system.gotoready", "system.poweron"):
            await self.wakeup()
            if method == "system.poweron":
                self._poweron_pending = True
        else:
            await self.check_connection()
            self.send_request(method, params)

    async def update_data(self) -> None:
        """Stuff that has to be polled."""
        _LOGGER.debug("Updating data")
        await self.send_command("property.get", {"property": [DEVICE_SYSTEM_TARGETSTATE, DEVICE_SYSTEM_STATE]})

    @property
    def is_on(self) -> bool:
        """Is Projector on."""
        return self._data.get(DEVICE_SYSTEM_TARGETSTATE) in ["on", "conditioning"]

    @property
    def source_list(self) -> list[str]:
        """Return source list."""
        return self._data.get(DEVICE_INPUT_SOURCE_LIST)

    @property
    def source(self) -> str:
        """Current source."""
        return self._data.get(DEVICE_INPUT_SOURCE)

    async def turn_on(self) -> None:
        """Turn on the power."""
        await self.send_command("system.poweron", "[]")

    async def turn_off(self) -> None:
        """Turn on the power."""
        await self.send_command("system.poweroff", "[]")

    async def select_source(self, source: str) -> None:
        """Set the input."""
        await self.send_command("property.set", {"property": DEVICE_INPUT_SOURCE, "value": source})

    async def async_init(self, data_callback: callback) -> None:
        """Initialize the device."""
        await self.wakeup()
        self._callback = data_callback

    async def listener(self) -> None:
        """Listen for status updates from device."""

        while self._online and not self._sleeping:
            try:
                buf = await self._reader.read(4096)
                if len(buf) == 0:
                    _LOGGER.error("Connection closed")
                    self._online = False
                else:
                    jbufs = buf.split(b'{"jsonrpc')
                    for jbuf in jbufs[1:]:
                        resp = self.decode_response(b'{"jsonrpc' + jbuf)
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
                                elif req["method"] == "image.source.list":
                                    self._data[DEVICE_INPUT_SOURCE_LIST] = resp.get("result")
                        elif resp.get("method") == "property.changed":
                            self.property_update(resp["params"]["property"][0])

            except asyncio.IncompleteReadError as err:
                _LOGGER.error("Connection lost: %s", err)
                self._online = False
                self._reader.close()
                self._writer.close()

        _LOGGER.info("Closing connection in listener")
        self._connection_closed()

    def _connection_closed(self) -> None:
        """Connection closed."""
        self._writer.close()
        self._online = False
        self._init_event.clear()
        self._requests.clear()
        self._data.clear()
        if self._callback is not None:
            self._callback(self._data)

    def property_update(self, updates) -> None:
        """Update properties."""
        try:
            if updates is None:
                return
            for n, v in updates.items():
                _LOGGER.debug("Projector update: %s=%s", n, v)
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
                    if v != self._data.get(n):
                        if n == DEVICE_SYSTEM_STATE:
                            _LOGGER.info("Projector state: %s", v)
                        elif n == DEVICE_SYSTEM_TARGETSTATE:
                            _LOGGER.info("Projector target state: %s", v)
                        if n in (DEVICE_SYSTEM_STATE, DEVICE_SYSTEM_TARGETSTATE) and v == "eco":
                            _LOGGER.info("Projector going to sleep")
                            self._sleeping = True
                        self._data[n] = v
            if self._callback is not None:
                self._callback(self._data)

        except Exception as exc:
            _LOGGER.error("Exception in property update: %s", exc)
