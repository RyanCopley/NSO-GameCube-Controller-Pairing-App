"""
BLE Event Loop

Shared asyncio daemon thread for all BLE operations.
Singleton — one event loop serves all controller slots.
"""

import asyncio
import concurrent.futures
import threading
from typing import Optional


class BleEventLoop:
    """Manages a shared asyncio event loop running in a daemon thread."""

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    def start(self):
        """Start the asyncio event loop thread if not already running."""
        if self.is_running:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop(self):
        """Stop the event loop and join the thread."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None

    def get_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    def submit(self, coro) -> concurrent.futures.Future:
        """Submit a coroutine to the event loop. Returns a concurrent.futures.Future."""
        if not self._loop or not self._loop.is_running():
            raise RuntimeError("BLE event loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)
