"""Serialize pyad operations on the thread that owns their COM objects."""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial


def initialize_com() -> None:
    if sys.platform == "win32":
        import pythoncom

        pythoncom.CoInitialize()


def uninitialize_com() -> None:
    if sys.platform == "win32":
        import pythoncom

        pythoncom.CoUninitialize()


class ADWorker:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(
            max_workers=1, initializer=initialize_com, thread_name_prefix="ad"
        )

    async def run(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.executor, partial(function, *args)
        )

    async def close(self) -> None:
        await self.run(uninitialize_com)
        self.executor.shutdown(wait=True)
