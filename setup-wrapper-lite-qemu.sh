#!/bin/sh
# Wrapper Lite QEMU launcher for macOS and Linux. Windows uses setup-wrapper-lite-qemu.cmd.
here="$(cd "$(dirname "$0")" && pwd)"
for python in python3 python; do
    if command -v "$python" >/dev/null 2>&1 && "$python" -c "import sys; sys.exit(sys.version_info < (3, 8))" 2>/dev/null; then
        exec "$python" "$here/scripts/wrappers/setup_qemu.py" "$@"
    fi
done
echo "Setup failed: Python 3.8 or newer is required (python3)." >&2
exit 1
