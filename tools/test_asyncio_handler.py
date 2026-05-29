"""Test that our custom exception handler prevents sys.exit on background task failures."""
import asyncio
import sys

async def failing_task():
    await asyncio.sleep(0.1)
    raise RuntimeError('background task failed')

async def test():
    loop = asyncio.get_running_loop()
    def handler(loop, ctx):
        exc = ctx.get('exception')
        msg = ctx.get('message', '')
        print(f'[handler] caught: {msg} | {exc}', flush=True)
    loop.set_exception_handler(handler)
    t = asyncio.create_task(failing_task())
    await asyncio.sleep(0.5)
    print('main still running', flush=True)

asyncio.run(test())
print('completed ok')
