"""대기전력 콘센트 (채널2): 차단/해제, 자동/수동.

보호 콘센트(protected_outlets, 예: 서버 전원)는 스위치를 만들되, 전원 차단·자동차단 켜기는
"보호 콘센트 잠금 해제" 스위치를 먼저 켠 뒤 60초 안에만 실행된다 (실행 후 바로 다시 잠김).
잠긴 상태에서 누르면 실행하지 않고 오류 메시지를 띄운다."""
from __future__ import annotations

import logging
import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from . import protocol as p
from .const import DOMAIN, OUTLETS_PER_ROOM
from .entity import WallpadEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    wp = hass.data[DOMAIN][entry.entry_id]
    ents = []
    for rid, rname, group, _c, _h in wp.rooms:
        for n in range(1, OUTLETS_PER_ROOM + 1):
            oid = group | n
            ents.append(OutletPower(wp, rid, rname, group, n))
            ents.append(OutletAuto(wp, rid, rname, group, n))
    if wp.protected:
        ents.append(ProtectedUnlock(wp))
    async_add_entities(ents)


UNLOCK_SECONDS = 60


def _guard(wp, name: str) -> None:
    """보호 콘센트의 위험한 동작 전에 호출. 잠겨 있으면 HomeAssistantError(화면에 메시지)."""
    if time.monotonic() > getattr(wp, "unlock_until", 0):
        raise HomeAssistantError(
            f"{name}은(는) 보호된 콘센트입니다 (서버 등). "
            f"'보호 콘센트 잠금 해제'를 켠 뒤 {UNLOCK_SECONDS}초 안에 다시 누르세요."
        )
    wp.unlock_until = 0  # 한 번 실행하면 바로 다시 잠금
    wp.intentional_until = time.monotonic() + 300  # 5분 동안은 자동 복구하지 않음
    for cb in list(getattr(wp, "unlock_listeners", [])):
        cb()


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

    def __init__(self, wp, oid_str, name, group, n, rid) -> None:
        super().__init__(wp, oid_str, name, "switch", rid)
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
        super().__init__(wp, f"outlet_{rid}_{n}", f"{rname} 콘센트 {n}", group, n, rid)

    @property
    def is_on(self):
        return self._o.on if self._o else None

    async def _set(self, on: bool) -> None:
        await self.wp.light.send(p.outlet_power_cmd(self.oid, on), sync=self._sync,
                                 verify=outlet_verify(self.group, self.n, "power", p.ON if on else p.OFF))

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        if self.oid in self.wp.protected:
            _guard(self.wp, self.name)
        await self._set(False)


class OutletAuto(_Outlet):
    _attr_icon = "mdi:power-sleep"

    def __init__(self, wp, rid, rname, group, n) -> None:
        super().__init__(wp, f"outlet_{rid}_{n}_auto", f"{rname} 콘센트 {n} 자동차단", group, n, rid)

    @property
    def is_on(self):
        return self._o.auto if self._o else None

    async def _set(self, auto: bool) -> None:
        await self.wp.light.send(p.outlet_mode_cmd(self.oid, auto), sync=self._sync,
                                 verify=outlet_verify(self.group, self.n, "mode", p.OUTLET_AUTO if auto else p.OUTLET_MANUAL))

    async def async_turn_on(self, **kwargs) -> None:
        if self.oid in self.wp.protected:
            _guard(self.wp, self.name)
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


class ProtectedUnlock(WallpadEntity, SwitchEntity):
    """켜면 60초 동안 보호 콘센트의 차단·자동차단 켜기를 허용. 시간이 지나거나 한 번 실행하면 자동으로 꺼짐."""
    _attr_icon = "mdi:lock-open-alert"

    def __init__(self, wp) -> None:
        super().__init__(wp, "outlet_protect_unlock", "보호 콘센트 잠금 해제", "switch")
        wp.unlock_until = 0
        wp.unlock_listeners = [self._relocked]
        self._cancel = None

    @property
    def is_on(self) -> bool:
        return time.monotonic() < self.wp.unlock_until

    def _relocked(self) -> None:
        if self._cancel:
            self._cancel()
            self._cancel = None
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        self.wp.unlock_until = time.monotonic() + UNLOCK_SECONDS
        if self._cancel:
            self._cancel()
        self._cancel = self.hass.loop.call_later(UNLOCK_SECONDS + 0.5, self.async_write_ha_state).cancel
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.wp.unlock_until = 0
        self._relocked()
