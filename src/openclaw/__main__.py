"""Entry point: python -m openclaw"""

import asyncio

from openclaw.app import FochsApp


def main() -> None:
    app = FochsApp()
    asyncio.run(app.start())


if __name__ == "__main__":
    main()
