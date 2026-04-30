#!/bin/sh
set -eu

RULE_NAME="69-mouser-logitech.rules"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SCRIPT_PATH="$SCRIPT_DIR/$(basename -- "$0")"
RULE_SOURCE="$SCRIPT_DIR/$RULE_NAME"
RULE_TARGET="/etc/udev/rules.d/$RULE_NAME"

if [ ! -f "$RULE_SOURCE" ]; then
    echo "Missing udev rule file: $RULE_SOURCE" >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    if command -v pkexec >/dev/null 2>&1; then
        exec pkexec /bin/sh "$SCRIPT_PATH"
    fi
    if command -v sudo >/dev/null 2>&1; then
        exec sudo /bin/sh "$SCRIPT_PATH"
    fi
    echo "This installer needs administrator privileges." >&2
    echo "Run: sudo /bin/sh \"$SCRIPT_PATH\"" >&2
    exit 1
fi

install -m 0644 "$RULE_SOURCE" "$RULE_TARGET"

if command -v modprobe >/dev/null 2>&1; then
    modprobe uinput 2>/dev/null || true
fi

if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules
    udevadm trigger
    udevadm settle 2>/dev/null || true
else
    echo "udevadm was not found; installed the rule but could not reload udev." >&2
fi

echo "Installed $RULE_TARGET"
echo "Reconnect your Logitech mouse, fully quit Mouser, then launch Mouser again."
echo "If desktop launch still cannot access the mouse, log out and back in once."
