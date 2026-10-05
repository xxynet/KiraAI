import asyncio


async def start_adapter(adapter):
    """Schedule the public lifetime coroutine without waiting for it to finish."""
    task = asyncio.create_task(adapter.start())
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    await asyncio.sleep(0)
    return task
