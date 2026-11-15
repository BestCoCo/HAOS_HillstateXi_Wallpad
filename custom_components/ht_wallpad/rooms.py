"""방 배치 텍스트 ↔ 내부 구조 (HA와 무관).

한 줄에 방 하나:  id | 이름 | 영역 | 조명그룹 | 회로이름들(쉼표) | 난방번호
예)  geosil | 거실 | 거실 | 10 | 1,2,복도 | 11
     jubang | 주방 | 주방 | 60 | 1,2,3 |
- 조명그룹·난방번호는 16진수 두 자리 (10, 11 …). 난방이 없으면 비움
- 영역을 비우면 이름을 영역으로 씀. # 으로 시작하는 줄은 무시
"""
from __future__ import annotations

import re

from .const import DEFAULT_ROOMS

Room = tuple[str, str, int, list[str], int | None]


def rooms_to_text(rooms: list[Room], areas: dict[str, str] | None = None) -> str:
    areas = areas or {}
    lines = []
    for rid, name, group, lights, heat in rooms:
        lines.append(" | ".join([
            rid, name, areas.get(rid, name), f"{group:02x}", ",".join(lights), f"{heat:02x}" if heat else "",
        ]))
    return "\n".join(lines)


def parse_rooms(text: str) -> tuple[list[Room], dict[str, str]]:
    """잘못된 줄이 있으면 ValueError(줄 번호 포함)."""
    rooms: list[Room] = []
    areas: dict[str, str] = {}
    for no, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        parts += [""] * (6 - len(parts))
        rid, name, area, group, lights, heat = parts[:6]
        if not re.fullmatch(r"[a-z0-9_]+", rid or ""):
            raise ValueError(f"{no}번째 줄: id 는 영문 소문자·숫자·_ 만 ({rid!r})")
        if not name:
            raise ValueError(f"{no}번째 줄: 이름이 비어 있음")
        try:
            g = int(group, 16)
            h = int(heat, 16) if heat else None
        except ValueError as err:
            raise ValueError(f"{no}번째 줄: 조명그룹/난방번호는 16진수 (예 10, 11)") from err
        circuits = [x.strip() for x in lights.split(",") if x.strip()]
        if any(r[0] == rid for r in rooms):
            raise ValueError(f"{no}번째 줄: id 중복 ({rid})")
        rooms.append((rid, name, g, circuits, h))
        areas[rid] = area or name
    if not rooms:
        raise ValueError("방이 하나도 없음")
    return rooms, areas


def default_rooms_text() -> str:
    return rooms_to_text(DEFAULT_ROOMS)


def parse_hex_list(text: str) -> set[int]:
    out = set()
    for x in re.split(r"[,\s]+", text or ""):
        if x:
            out.add(int(x, 16))
    return out
