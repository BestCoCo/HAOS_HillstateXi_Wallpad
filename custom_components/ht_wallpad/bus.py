"""EW11(RS485 → TCP) 연결 하나를 담당: 수신 파싱, 자동 재접속, 응답 직후 전송 + 확인·재시도."""
from __future__ import annotations

import asyncio
import logging
import random
import socket
from collections.abc import Callable

from .protocol import extract_frames

_LOGGER = logging.getLogger(__name__)

Predicate = Callable[[bytes], bool]

IDLE_TIMEOUT = 15  # 이 시간 동안 데이터가 없으면 끊긴 연결로 보고 다시 연결 (월패드는 ~1초마다 폴링)
MAX_BACKOFF = 30


class Ew11Bus:
    def __init__(
        self, name: str, host: str, port: int, on_frame: Callable[[str, bytes], None],
        on_status: Callable[[str, bool], None] | None = None,
    ) -> None:
        self.name = name
        self._on_status = on_status
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
                self._keepalive(self._writer)
                _LOGGER.info("EW11 %s(%s) 연결됨", self.name, self.host)
                buf = bytearray()
                got_data = False
                while True:
                    try:
                        data = await asyncio.wait_for(reader.read(1024), IDLE_TIMEOUT)
                    except TimeoutError as err:
                        raise ConnectionError(f"{IDLE_TIMEOUT}초 동안 수신 없음") from err
                    if not data:
                        raise ConnectionError("연결 끊김")
                    if not got_data:
                        got_data = True
                        backoff = 2
                        self._set_connected(True)
                    buf += data
                    for frame in extract_frames(buf):
                        self._dispatch(frame)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("EW11 %s(%s) 연결 오류: %s — %s초 후 재접속", self.name, self.host, err, backoff)
            finally:
                self._set_connected(False)
                if self._writer:
                    self._writer.close()
                    self._writer = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            if self._on_status:
                self._on_status(self.name, value)

    @staticmethod
    def _keepalive(writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        if sock is None:
            return
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for opt, val in (("TCP_KEEPIDLE", 10), ("TCP_KEEPALIVE", 10), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3)):
                if hasattr(socket, opt):
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), val)
        except OSError:
            pass

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

    async def send_before(self, packet: bytes, after: Predicate, verify: Predicate,
                          delays: list[float], verify_timeout: float = 4.0) -> bool:
        """after 프레임이 지나간 뒤 delays[i] 초에 보내고(다음 폴링 직전), verify 가 오면 성공."""
        async with self._send_lock:
            for attempt, delay in enumerate(delays, 1):
                if not self._writer:
                    await asyncio.sleep(2)
                    continue
                if await self.wait_for(after, 5) is None:
                    continue
                await asyncio.sleep(delay)
                fut: asyncio.Future = asyncio.get_running_loop().create_future()
                item = (verify, fut)
                self._waiters.append(item)
                try:
                    self._writer.write(packet)
                    await self._writer.drain()
                    await asyncio.wait_for(fut, verify_timeout)
                    _LOGGER.info("미리 보내기 성공 %s (%d회, %.2f초)", self.name, attempt, delay)
                    return True
                except TimeoutError:
                    continue
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("전송 오류 %s: %s", self.name, err)
                finally:
                    self._waiters.remove(item)
            _LOGGER.warning("미리 보내기 실패 %s (%d회)", self.name, len(delays))
            return False

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
