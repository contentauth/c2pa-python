#!/bin/bash
set -e

cd /workspace
export PYTHONPATH=/workspace/src

# Download the Linux native library into the volume-mounted workspace.
# Runs at container start so libs land in the host-mounted tree,
# not in a build layer that gets shadowed by the -v mount.
C2PA_VERSION=$(cat c2pa-native-version.txt)
ARCH=$(uname -m)

if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    PLATFORM="aarch64-unknown-linux-gnu"
else
    PLATFORM="x86_64-unknown-linux-gnu"
fi

echo "Downloading c2pa native lib: $C2PA_VERSION / $PLATFORM"
C2PA_LIBS_PLATFORM=$PLATFORM python scripts/download_artifacts.py "$C2PA_VERSION"

# Replicate what setup.py copy_platform_libraries() does:
# So the correct Linux library is here for the Dockerfile
python - <<EOF
import shutil
from pathlib import Path
src = Path("artifacts/$PLATFORM")
dst = Path("src/c2pa/libs")
dst.mkdir(parents=True, exist_ok=True)
for f in src.glob("*"):
    if f.is_file():
        shutil.copy2(f, dst / f.name)
        print(f"  copied {f.name}")
EOF

echo "src/c2pa/libs contents: $(ls src/c2pa/libs/)"

exec "$@"
