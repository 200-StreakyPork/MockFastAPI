"""Explicit initialization and reset commands."""

import argparse
import asyncio

from mockfastapi.cache import get_redis
from mockfastapi.db import get_session
from mockfastapi.people.seed import seed


async def run(command: str) -> None:
    redis = get_redis()
    sessions = get_session()
    try:
        session = await anext(sessions)
        await seed(session, reset=command == "reset", redis=redis)
    finally:
        await sessions.aclose()
        await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize or reset MockFastAPI fixtures")
    parser.add_argument("command", choices=("seed", "reset"))
    args = parser.parse_args()
    asyncio.run(run(args.command))


if __name__ == "__main__":
    main()
