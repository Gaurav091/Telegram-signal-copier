"""Test: does SystemExit in a background asyncio task propagate through run_until_complete?"""
import asyncio, sys

async def bad_task():
    await asyncio.sleep(0.1)
    raise SystemExit(1)

async def main():
    t = asyncio.create_task(bad_task())
    print("main: task created, waiting 0.5s", flush=True)
    try:
        await asyncio.sleep(0.5)
        print("main: sleep done normally", flush=True)
    except BaseException as e:
        print(f"main: caught {type(e).__name__}: {e}", flush=True)
        raise

try:
    asyncio.run(main())
    print("asyncio.run completed")
except SystemExit as e:
    print(f"Caught SystemExit({e.code}) from asyncio.run")
except BaseException as e:
    print(f"Caught {type(e).__name__}: {e} from asyncio.run")
