"""현대HT 월패드 (힐스테이트 자이 아산센텀) — EW11 3대를 통한 RS485 연동."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from . import protocol as p
from .bus import Ew11Bus
from .const import (
    CONF_ELEVATOR_HOST, CONF_HEAT_HOST, CONF_LIGHT_HOST, CONF_PORT, CONF_PROTECTED_OUTLETS, CONF_ROOMS,
    DEFAULT_PORT, DEFAULT_PROTECTED_OUTLETS, DEFAULT_ROOMS, DOMAIN, EVENT, SIGNAL_UPDATE,
)

HEX = vol.All(cv.string, lambda v: int(str(v), 16))

ROOM_SCHEMA = vol.Schema(
    {
        vol.Required("id"): cv.slug,
        vol.Required("name"): cv.string,
        vol.Required("light_group"): HEX,  # 예: "10"
        vol.Optional("lights", default=[]): vol.All(cv.ensure_list, [cv.string]),  # 회로 이름들
        vol.Optional("heat"): HEX,  # 예: "11"
    }
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.CLIMATE, Platform.FAN, Platform.SWITCH,
             Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_ELEVATOR_HOST): cv.string,
                vol.Required(CONF_LIGHT_HOST): cv.string,
                vol.Required(CONF_HEAT_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Optional(CONF_PROTECTED_OUTLETS, default=[f"{x:02x}" for x in DEFAULT_PROTECTED_OUTLETS]):
                    vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(CONF_ROOMS): vol.All(cv.ensure_list, [ROOM_SCHEMA]),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class Wallpad:
    def __init__(self, hass: HomeAssistant, conf: dict) -> None:
        self.hass = hass
        self.state = p.WallpadState()
        self.parser = p.Parser(self.state)
        self.protected = {int(str(x), 16) for x in conf[CONF_PROTECTED_OUTLETS]}
        if conf.get(CONF_ROOMS):
            self.rooms = [
                (r["id"], r["name"], r["light_group"], r["lights"], r.get("heat")) for r in conf[CONF_ROOMS]
            ]
        else:
            self.rooms = DEFAULT_ROOMS
        port = conf[CONF_PORT]
        self.ev = Ew11Bus("elevator", conf[CONF_ELEVATOR_HOST], port, self._on_frame)
        self.light = Ew11Bus("light", conf[CONF_LIGHT_HOST], port, self._on_frame)
        self.heat = Ew11Bus("heat", conf[CONF_HEAT_HOST], port, self._on_frame)
        self.buses = [self.ev, self.light, self.heat]

    def _on_frame(self, bus: str, frame: bytes) -> None:
        changed, events = self.parser.feed(frame)
        for name in changed:
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{name}")
        for kind, data in events:
            self.hass.bus.async_fire(EVENT, {"type": kind, **data})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config[DOMAIN]
    wallpad = Wallpad(hass, conf)
    hass.data[DOMAIN] = wallpad
    for bus in wallpad.buses:
        bus.start(lambda coro, name: hass.async_create_background_task(coro, name))

    async def _stop(_event) -> None:
        for bus in wallpad.buses:
            await bus.stop()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop)
    for platform in PLATFORMS:
        hass.async_create_task(async_load_platform(hass, platform, DOMAIN, {}, config))
    return True
