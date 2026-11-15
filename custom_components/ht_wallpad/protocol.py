"""현대HT(Imazu 계열) 월패드 RS485 프로토콜 — HA와 무관한 순수 파이썬.

프레임: F7 | 길이 | 01 | 기기 | 명령 | 종류 | 번호 | 데이터… | XOR | EE
  - 길이 = F7부터 EE까지 전체 바이트 수
  - XOR  = F7부터 XOR 바로 앞까지 XOR
  - 명령: 01 상태요청(월패드), 02 제어(월패드/HA), 04 응답(기기)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce

HEADER = 0xF7
FOOTER = 0xEE

CMD_QUERY = 0x01
CMD_CONTROL = 0x02
CMD_REPLY = 0x04

DEV_HEAT = 0x18
DEV_LIGHT = 0x19
DEV_GAS = 0x1B
DEV_OUTLET = 0x1F
DEV_BATCH = 0x2A  # 일괄 스위치
DEV_FAN = 0x2B
DEV_ELEVATOR = 0x34
DEV_TIME = 0x44
DEV_HALL_BUTTON = 0x48  # 일괄 스위치의 복도등 버튼

ON = 0x01
OFF = 0x02
HEAT_ON = 0x01
HEAT_OFF = 0x04
HEAT_AWAY = 0x07

FAN_LOW = 0x01
FAN_MID = 0x03
FAN_HIGH = 0x07

OUTLET_AUTO = 0x01
OUTLET_MANUAL = 0x02


def xor(data: bytes) -> int:
    return reduce(lambda a, b: a ^ b, data, 0)


def build(device: int, cmd: int, kind: int, sub: int, *data: int) -> bytes:
    body = bytes([HEADER, 0, 0x01, device, cmd, kind, sub, *data])
    body = bytes([HEADER, len(body) + 2]) + body[2:]
    return body + bytes([xor(body), FOOTER])


def extract_frames(buf: bytearray) -> list[bytes]:
    """버퍼에서 완성된 프레임을 꺼내고(체크섬 검사) 나머지는 버퍼에 남긴다."""
    frames: list[bytes] = []
    while True:
        start = buf.find(HEADER)
        if start < 0:
            buf.clear()
            break
        if start:
            del buf[:start]
        if len(buf) < 2:
            break
        length = buf[1]
        if length < 8 or length > 64:
            del buf[:1]
            continue
        if len(buf) < length:
            break
        frame = bytes(buf[:length])
        if frame[-1] == FOOTER and xor(frame[:-2]) == frame[-2]:
            frames.append(frame)
            del buf[:length]
        else:
            del buf[:1]
    return frames


# ---------------------------------------------------------------- 명령 생성
def light_cmd(sub: int, on: bool) -> bytes:
    """sub = 그룹(0x10…)이면 방 전체, 그룹+회로(0x11…)이면 회로 하나."""
    return build(DEV_LIGHT, CMD_CONTROL, 0x40, sub, ON if on else OFF, 0x00)


def outlet_power_cmd(oid: int, on: bool) -> bytes:
    return build(DEV_OUTLET, CMD_CONTROL, 0x40, oid, ON if on else OFF, 0x00)


def outlet_mode_cmd(oid: int, auto: bool) -> bytes:
    return build(DEV_OUTLET, CMD_CONTROL, 0x57, oid, OUTLET_AUTO if auto else OUTLET_MANUAL, 0x00)


def heat_power_cmd(room: int, on: bool) -> bytes:
    return build(DEV_HEAT, CMD_CONTROL, 0x46, room, HEAT_ON if on else HEAT_OFF, 0x00)


def heat_target_cmd(room: int, temp: int) -> bytes:
    return build(DEV_HEAT, CMD_CONTROL, 0x45, room, int(temp) & 0xFF, 0x00)


def fan_power_cmd(on: bool, sub: int = 0x11) -> bytes:
    return build(DEV_FAN, CMD_CONTROL, 0x40, sub, ON if on else OFF, 0x00)


def fan_speed_cmd(speed: int, sub: int = 0x11) -> bytes:
    return build(DEV_FAN, CMD_CONTROL, 0x42, sub, speed, 0x00)


# ---------------------------------------------------------------- 상태
@dataclass
class OutletState:
    on: bool | None = None
    auto: bool | None = None
    watt: int | None = None


@dataclass
class HeatState:
    mode: int | None = None  # 01 난방 / 04 꺼짐 / 07 외출
    current: int | None = None
    target: int | None = None


@dataclass
class WallpadState:
    lights: dict[int, bool] = field(default_factory=dict)  # key = 회로 sub (0x11…)
    outlets: dict[int, OutletState] = field(default_factory=dict)  # key = 콘센트 번호 (0x11…)
    heats: dict[int, HeatState] = field(default_factory=dict)  # key = 방 번호 (0x11…)
    fan_on: bool | None = None
    fan_speed: int | None = None
    ev_calling: bool | None = None
    ev_status: int | None = None  # 00 대기 / a6 이동 / b6 출발·감속 / 01 도착
    ev_floor: str | None = None
    batch_off: bool | None = None  # 일괄소등 설정
    hall_pressed: bool | None = None


def floor_text(raw: int) -> str | None:
    if raw == 0:
        return None
    if raw >> 4 == 0xB:
        return f"B{raw & 0x0F}"
    return f"{raw:02x}".lstrip("0") or "0"


class Parser:
    """프레임을 받아 상태를 갱신하고, 바뀐 항목 이름(set)과 이벤트(list)를 돌려준다."""

    def __init__(self, state: WallpadState) -> None:
        self.s = state

    def feed(self, f: bytes) -> tuple[set[str], list[tuple[str, dict]]]:
        changed: set[str] = set()
        events: list[tuple[str, dict]] = []
        dev, cmd, kind, sub = f[3], f[4], f[5], f[6]
        s = self.s

        if dev == DEV_ELEVATOR and cmd == CMD_QUERY and len(f) >= 13:
            st, fl = f[8], f[9]
            if s.ev_status != st:
                s.ev_status = st
                changed.add("elevator")
            text = floor_text(fl) if st else None
            if s.ev_floor != text:
                s.ev_floor = text
                changed.add("elevator")
            return changed, events

        if cmd != CMD_REPLY:
            return changed, events

        if dev == DEV_LIGHT and kind == 0x40:
            group = sub & 0xF0
            if sub & 0x0F == 0:
                if f[7] == 0x00:  # 상태 응답: 회로별
                    for i, v in enumerate(f[8:-2], 1):
                        self._set(s.lights, group | i, v == ON, changed, "light")
                else:  # 방 전체 명령 응답
                    for key in [k for k in s.lights if k & 0xF0 == group]:
                        self._set(s.lights, key, f[8] == ON, changed, "light")
            else:
                self._set(s.lights, sub, f[8] == ON, changed, "light")

        elif dev == DEV_OUTLET:
            if kind == 0x40 and sub & 0x0F == 0 and f[7] == 0x00:
                data = f[8:-2]
                for k in range(0, len(data) - 8, 9):
                    blk = data[k : k + 9]
                    o = s.outlets.setdefault(blk[0], OutletState())
                    new = (blk[1] == ON, blk[8] == OUTLET_AUTO, int.from_bytes(blk[2:4], "big"))
                    if (o.on, o.auto, o.watt) != new:
                        o.on, o.auto, o.watt = new
                        changed.add("outlet")
            elif kind == 0x40 and sub & 0x0F:
                o = s.outlets.setdefault(sub, OutletState())
                if o.on != (f[8] == ON):
                    o.on = f[8] == ON
                    changed.add("outlet")
            elif kind == 0x57 and sub & 0x0F:
                o = s.outlets.setdefault(sub, OutletState())
                if o.auto != (f[8] == OUTLET_AUTO):
                    o.auto = f[8] == OUTLET_AUTO
                    changed.add("outlet")

        elif dev == DEV_HEAT and kind in (0x45, 0x46) and len(f) >= 13:
            h = s.heats.setdefault(sub, HeatState())
            new = (f[8], f[9], f[10])
            if (h.mode, h.current, h.target) != new:
                h.mode, h.current, h.target = new
                changed.add("heat")

        elif dev == DEV_FAN and len(f) >= 12:
            new = (f[8] == ON, f[9])
            if (s.fan_on, s.fan_speed) != new:
                s.fan_on, s.fan_speed = new
                changed.add("fan")

        elif dev == DEV_ELEVATOR and len(f) >= 11:
            calling = f[8] == 0x06
            if s.ev_calling is not None and s.ev_calling != calling:
                events.append(("elevator_called" if calling else "elevator_arrived", {}))
            if s.ev_calling != calling:
                s.ev_calling = calling
                changed.add("elevator")

        elif dev == DEV_BATCH and len(f) >= 14:
            off = f[9] == 0x01
            if s.batch_off is not None and s.batch_off != off:
                events.append(("batch_off_set" if off else "batch_off_released", {}))
            if s.batch_off != off:
                s.batch_off = off
                changed.add("batch")

        elif dev == DEV_HALL_BUTTON and len(f) >= 13:
            pressed = f[10] == 0x01
            if s.hall_pressed is False and pressed:
                events.append(("hall_button_pressed", {}))
            s.hall_pressed = pressed

        return changed, events

    @staticmethod
    def _set(d: dict, key: int, value: bool, changed: set[str], name: str) -> None:
        if d.get(key) != value:
            d[key] = value
            changed.add(name)


# ---------------------------------------------------------------- 전송 시점/확인 조건
def is_reply(f: bytes, device: int, sub: int | None = None) -> bool:
    return f[3] == device and f[4] == CMD_REPLY and (sub is None or f[6] == sub)
