# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import asyncio

import app.factory as factory_module
from app.attributor_manager import AttributorManager


def test_cleanup_task_survives_exceptions(monkeypatch):
    """A single failed cleanup pass must not permanently stop the background
    cleanup loop -- otherwise expired attributors accumulate forever."""
    call_count = 0
    aim = AttributorManager()

    def flaky_cleanup():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated transient error")

    monkeypatch.setattr(aim, "cleanup_expired_attributors", flaky_cleanup)

    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(factory_module.asyncio, "sleep", fast_sleep)

    async def run():
        task = asyncio.create_task(factory_module._cleanup_expired_attributors(aim))
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    assert call_count >= 2, "cleanup loop stopped after the first exception instead of continuing"
