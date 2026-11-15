"""EW11(RS485 → TCP) 연결 하나를 담당: 수신 파싱, 자동 재접속, 응답 직후 전송 + 확인·재시도."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable

from .protocol import extract_frames

_LOGGER = logging.getLogger(__name__)

Predicate = Callable[[bytes], bool]


class Ew11Bus:
    def __init__(self, name: str, host: str, port: int, on_frame: Callable[[str, bytes], None]) -> None:
        self.name = name
        self.host = host
        self.port = port
        self._on_frame = on_frame
        self._writer: asyncio.StreamWriter | None = None
        self._waiters: list[tuple[Predicate, asyncio.Future]] = []
        self._send_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.connected = False

    def start(self, create_task: Callable) -> None:
        self._task = create_task(self._run(), f"ht_wallpad_{self.name}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._writer:
            self._writer.close()

    async def _run(self) -> None:
        backoff = 2
        while True:
            try:
                reader, self._writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 10)
                self.connected = True
                backoff = 2
                _LOGGER.info("EW11 %s(%s) 연결됨", self.name, self.host)
                buf = bytearray()
                while True:
                    data = await asyncio.wait_for(reader.read(1024), 60)
                    if not data:
                        raise ConnectionError("연결 끊김")
                    buf += data
                    for frame in extract_frames(buf):
                        self._dispatch(frame)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("EW11 %s(%s) 연결 오류: %s — %s초 후 재접속", self.name, self.host, err, backoff)
            finally:
                self.connected = False
                if self._writer:
                    self._writer.close()
                    self._writer = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _dispatch(self, frame: bytes) -> None:
        for pred, fut in list(self._waiters):
            if not fut.done() and pred(frame):
                fut.set_result(frame)
        self._on_frame(self.name, frame)

    async def wait_for(self, pred: Predicate, timeout: float) -> bytes | None:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        item = (pred, fut)
        self._waiters.append(item)
        try:
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            return None
        finally:
            self._waiters.remove(item)

    async def send(self, packet: bytes, sync: Predicate, verify: Predicate, retries: int = 8) -> bool:
        """대상 기기의 응답(sync)이 지나간 직후에 보내고, verify 조건 프레임이 오면 성공."""
        async with self._send_lock:
            for attempt in range(1, retries + 1):
                if not self._writer:
                    _LOGGER.warning("EW11 %s 미연결 — 전송 대기", self.name)
                    await asyncio.sleep(2)
                    continue
                await self.wait_for(sync, 3)
                await asyncio.sleep(random.uniform(0.01, 0.12))
                fut: asyncio.Future = asyncio.get_running_loop().create_future()
                item = (verify, fut)
                self._waiters.append(item)
                try:
                    self._writer.write(packet)
                    await self._writer.drain()
                    await asyncio.wait_for(fut, 2.5)
                    _LOGGER.debug("전송 성공 %s (%d회): %s", self.name, attempt, packet.hex(" "))
                    return True
                except TimeoutError:
                    continue
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("전송 오류 %s: %s", self.name, err)
                finally:
                    self._waiters.remove(item)
            _LOGGER.warning("전송 실패 %s (%d회 시도): %s", self.name, retries, packet.hex(" "))
            return False
