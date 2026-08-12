"""Entry point for short-lived Qt user-interface processes."""
from __future__ import annotations

import sys


def main() -> int:
    if "--ring-process" in sys.argv:
        from ui.actions_ring_worker import main as worker_main

        return worker_main()
    if "--screenshot-process" in sys.argv:
        from ui.screenshot_worker import main as worker_main

        return worker_main()

    from main_qml import main as qt_main

    return qt_main()


if __name__ == "__main__":
    raise SystemExit(main())
