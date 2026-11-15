"""환기 (채널3): 켜기/끄기, 약·중·강. 켜고 끄는 간격 최소 20초."""
from __future__ import annotations

import asyncio
import time

from homeassistant.components.fan import FanEntity, FanEntityFeature

from . import protocol as p
from .const import DOMAIN, FAN_MIN_TOGGLE_SECONDS, FAN_SUB
from .entity import WallpadEntity

SPEEDS = [p.FAN_LOW, p.FAN_MID, p.FAN_HIGH]


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([WallpadFan(hass.data[DOMAIN][entry.entry_id])])


class WallpadFan(WallpadEntity, FanEntity):
    _signal = "fan"
    _attr_speed_count = 3
    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    def __init__(self, wp) -> None:
        super().__init__(wp, "fan", "환기", "fan", "fan")
        self._last_power = 0.0

    @property
    def available(self) -> bool:
        return self.wp.state.fan_on is not None

    @property
    def is_on(self):
        return self.wp.state.fan_on

    @property
    def percentage(self):
        if not self.wp.state.fan_on:
            return 0
        sp = self.wp.state.fan_speed
        return {p.FAN_LOW: 33, p.FAN_MID: 66, p.FAN_HIGH: 100}.get(sp, 33)

    def _sync(self, f: bytes) -> bool:
        return p.is_reply(f, p.DEV_FAN, FAN_SUB)

    async def _power(self, on: bool) -> None:
        wait = FAN_MIN_TOGGLE_SECONDS - (time.monotonic() - self._last_power)
        if wait > 0:
            await asyncio.sleep(wait)
        want = p.ON if on else p.OFF
        if await self.wp.heat.send(
            p.fan_power_cmd(on, FAN_SUB), sync=self._sync,
            verify=lambda f: p.is_reply(f, p.DEV_FAN, FAN_SUB) and len(f) >= 12 and f[8] == want,
        ):
            self._last_power = time.monotonic()

    async def _speed(self, speed: int) -> None:
        await self.wp.heat.send(
            p.fan_speed_cmd(speed, FAN_SUB), sync=self._sync,
            verify=lambda f: p.is_reply(f, p.DEV_FAN, FAN_SUB) and len(f) >= 12 and f[9] == speed,
        )

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs) -> None:
        if not self.wp.state.fan_on:
            await self._power(True)
        if percentage:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs) -> None:
        await self._power(False)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        if not self.wp.state.fan_on:
            await self._power(True)
        idx = min(2, max(0, round(percentage / 33.4) - 1)) if percentage < 100 else 2
        await self._speed(SPEEDS[idx])
