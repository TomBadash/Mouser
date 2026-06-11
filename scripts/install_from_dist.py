#!/usr/bin/env python3
"""Install an existing dist/Mouser build without rebuilding."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.windows_install import (
    default_install_root,
    finalize_windows_install,
    replace_tree,
    resolve_install_scope,
)


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("install_from_dist.py is Windows-only")

    build_output = ROOT / "dist" / "Mouser"
    scope = resolve_install_scope()
    install_path = (
        Path(os.environ["MOUSER_INSTALL_DIR"]).expanduser()
        if os.environ.get("MOUSER_INSTALL_DIR")
        else default_install_root(scope)
    )

    print(f"Installing {build_output} -> {install_path} ({scope} scope)")
    replace_tree(build_output, install_path)
    shell = finalize_windows_install(install_path, scope=scope)
    print(f"Installed: {shell['install_root']}")
    print(f"Start Menu: {shell['start_menu_shortcut']}")


if __name__ == "__main__":
    main()
