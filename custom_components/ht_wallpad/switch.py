"""대기전력 콘센트 (채널2): 차단/해제, 자동/수동. protected_outlets 에 넣은 콘센트는 스위치를 만들지 않음."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity

from . import protocol as p
from .const import DOMAIN, OUTLETS_PER_ROOM
from .entity import WallpadEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    wp = hass.data[DOMAIN]
    ents = []
    for rid, rname, group, _c, _h in wp.rooms:
        for n in range(1, OUTLETS_PER_ROOM + 1):
            oid = group | n
            if oid in wp.protected:
                _LOGGER.info("보호 콘센트 %02x(%s %d구)는 스위치를 만들지 않음", oid, rname, n)
                continue
            ents.append(OutletPower(wp, rid, rname, group, n))
            ents.append(OutletAuto(wp, rid, rname, group, n))
    async_add_entities(ents)


def outlet_verify(group: int, n: int, field: str, want: int):
    oid = group | n

    def pred(f: bytes) -> bool:
        if f[3] != p.DEV_OUTLET or f[4] != p.CMD_REPLY:
            return False
        if f[6] == oid:  # 개별 명령 응답
            return (f[5] == 0x40 and field == "power" and f[8] == want) or (
                f[5] == 0x57 and field == "mode" and f[8] == want)
        if f[6] == group and f[7] == 0x00:  # 그룹 상태 응답
            data = f[8:-2]
            for k in range(0, len(data) - 8, 9):
                if data[k] == oid:
                    return data[k + (1 if field == "power" else 8)] == want
        return False

    return pred


class _Outlet(WallpadEntity, SwitchEntity):
    _signal = "outlet"

    def __init__(self, wp, oid_str, name, group, n) -> None:
        super().__init__(wp, oid_str, name, "switch")
        self.group = group
        self.oid = group | n
        self.n = n

    @property
    def _o(self):
        return self.wp.state.outlets.get(self.oid)

    @property
    def available(self) -> bool:
        return self._o is not None

    def _sync(self, f: bytes) -> bool:
        return p.is_reply(f, p.DEV_OUTLET, self.group)


class OutletPower(_Outlet):
    _attr_icon = "mdi:power-socket-de"

    def __init__(self, wp, rid, rname, group, n) -> None:
        super().__init__(wp, f"outlet_{rid}_{n}", f"{rname} 콘센트 {n}", group, n)

    @property
    def is_on(self):
        return self._o.on if self._o else None

    async def _set(self, on: bool) -> None:
        await self.wp.light.send(p.outlet_power_cmd(self.oid, on), sync=self._sync,
                                 verify=outlet_verify(self.group, self.n, "power", p.ON if on else p.OFF))

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


class OutletAuto(_Outlet):
    _attr_icon = "mdi:power-sleep"

    def __init__(self, wp, rid, rname, group, n) -> None:
        super().__init__(wp, f"outlet_{rid}_{n}_auto", f"{rname} 콘센트 {n} 자동차단", group, n)

    @property
    def is_on(self):
        return self._o.auto if self._o else None

    async def _set(self, auto: bool) -> None:
        await self.wp.light.send(p.outlet_mode_cmd(self.oid, auto), sync=self._sync,
                                 verify=outlet_verify(self.group, self.n, "mode", p.OUTLET_AUTO if auto else p.OUTLET_MANUAL))

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
