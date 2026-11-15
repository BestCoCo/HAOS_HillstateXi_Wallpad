"""현대HT 월패드 (힐스테이트 자이 아산센텀) — EW11 3대를 통한 RS485 연동.

설정은 화면(설정 → 기기 및 서비스)에서 한다. configuration.yaml 의 ht_wallpad: 가 있으면
처음 한 번 화면 설정으로 가져오고, 그 뒤에는 YAML 을 지워도 된다.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from . import protocol as p
from .bus import Ew11Bus
from .config_flow import CONF_FAN_AREA, CONF_MAIN_AREA, CONF_ROOMS_TEXT
from .const import (
    CONF_ELEVATOR_HOST, CONF_HEAT_HOST, CONF_LIGHT_HOST, CONF_PORT, CONF_PROTECTED_OUTLETS, CONF_ROOMS,
    DEFAULT_PORT, DOMAIN, EVENT, SIGNAL_UPDATE,
)
from .rooms import default_rooms_text, parse_hex_list, parse_rooms

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.CLIMATE, Platform.FAN, Platform.SWITCH,
             Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

HEX = vol.All(cv.string, lambda v: int(str(v), 16))
ROOM_SCHEMA = vol.Schema({
    vol.Required("id"): cv.slug,
    vol.Required("name"): cv.string,
    vol.Required("light_group"): HEX,
    vol.Optional("lights", default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("heat"): HEX,
    vol.Optional("area"): cv.string,
})
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema({
            vol.Required(CONF_ELEVATOR_HOST): cv.string,
            vol.Required(CONF_LIGHT_HOST): cv.string,
            vol.Required(CONF_HEAT_HOST): cv.string,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            vol.Optional(CONF_PROTECTED_OUTLETS, default=[]): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(CONF_ROOMS): vol.All(cv.ensure_list, [ROOM_SCHEMA]),
            vol.Optional(CONF_FAN_AREA, default="거실"): cv.string,
            vol.Optional(CONF_MAIN_AREA, default="현관"): cv.string,
        })
    },
    extra=vol.ALLOW_EXTRA,
)


class Wallpad:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        data, opts = entry.data, entry.options
        self.state = p.WallpadState()
        self.parser = p.Parser(self.state)
        self.protected = parse_hex_list(opts.get(CONF_PROTECTED_OUTLETS, ""))
        try:
            self.rooms, areas = parse_rooms(opts.get(CONF_ROOMS_TEXT) or default_rooms_text())
        except ValueError as err:
            _LOGGER.error("방 배치 설정 오류(%s) — 기본값 사용", err)
            self.rooms, areas = parse_rooms(default_rooms_text())
        names = {rid: rname for rid, rname, *_ in self.rooms}
        self._devices = {rid: (f"월패드 {names[rid]}", areas[rid]) for rid in names}
        self._devices["fan"] = ("월패드 환기", opts.get(CONF_FAN_AREA, "거실"))
        self._devices["main"] = ("월패드", opts.get(CONF_MAIN_AREA, "현관"))
        port = data.get(CONF_PORT, DEFAULT_PORT)
        self.ev = Ew11Bus("elevator", data[CONF_ELEVATOR_HOST], port, self._on_frame, self._on_status)
        self.light = Ew11Bus("light", data[CONF_LIGHT_HOST], port, self._on_frame, self._on_status)
        self.heat = Ew11Bus("heat", data[CONF_HEAT_HOST], port, self._on_frame, self._on_status)
        self.buses = [self.ev, self.light, self.heat]

    def device_meta(self, key: str) -> tuple[str, str | None]:
        """기기 이름과 영역. 영역은 HA에 이미 있는 이름일 때만 돌려준다 (새 영역을 만들지 않음)."""
        name, area = self._devices.get(key, ("월패드", None))
        if area and ar.async_get(self.hass).async_get_area_by_name(area) is None:
            _LOGGER.warning("영역 '%s'이(가) HA에 없어 '%s' 기기는 영역 없이 만듭니다", area, name)
            area = None
        return name, area

    def _on_status(self, bus: str, connected: bool) -> None:
        if not connected:
            _LOGGER.warning("EW11 %s 연결 끊김 — 자동 재접속 중", bus)
        self.hass.loop.call_soon_threadsafe(async_dispatcher_send, self.hass, f"{SIGNAL_UPDATE}_conn")

    def _on_frame(self, bus: str, frame: bytes) -> None:
        changed, events = self.parser.feed(frame)
        for name in changed:
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{name}")
        for kind, data in events:
            self.hass.bus.async_fire(EVENT, {"type": kind, **data})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """YAML(ht_wallpad:)이 있으면 화면 설정으로 가져온다. 이미 화면 설정이 있으면 무시."""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN])
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    wallpad = Wallpad(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = wallpad
    for bus in wallpad.buses:
        bus.start(lambda coro, name: entry.async_create_background_task(hass, coro, name))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_change))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    wallpad: Wallpad = hass.data[DOMAIN].pop(entry.entry_id)
    for bus in wallpad.buses:
        await bus.stop()
    return ok


async def _reload_on_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
