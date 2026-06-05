#!/usr/bin/env python3

# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

"""Build the native c2pa C FFI library from a local c2pa-rs checkout.

This is the counterpart to download_artifacts.py: instead of
downloading a released prebuilt c2pa-rs native library,
it compiles from local sources and places the built library
where setup.py expects it (artifacts/{platform_id}/).

The path to the c2pa-rs sources is taken from the C2PA_RS_PATH environment
variable (or the first positional argument).

Pass --clean to run a full `cargo clean` first, forcing a from-scratch rebuild.
Pass --debug to build the debug profile instead of the default release profile.
"""

import os
import sys
import shutil
import argparse
import platform
import subprocess
from pathlib import Path

# The crate in c2pa-rs that produces the native library.
FFI_PACKAGE = "c2pa-c-ffi"
# Extra c2pa-c-ffi features to enable on top of the crate defaults
FFI_FEATURES = "file_io"
ROOT_ARTIFACTS_DIR = Path("artifacts")
# Where the package loads the library from at runtime for an editable install.
PACKAGE_LIBS_DIR = Path("src/c2pa/libs")

# Library file name per OS (matches what setup.py/lib.py load at runtime).
LIB_NAMES = {
    "darwin": "libc2pa_c.dylib",
    "linux": "libc2pa_c.so",
    "windows": "c2pa_c.dll",
}


def get_platform_identifier():
    """Get the platform identifier (arch-os) for the host system.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        if machine == "arm64":
            return "aarch64-apple-darwin"
        elif machine == "x86_64":
            return "x86_64-apple-darwin"
        else:
            return "universal-apple-darwin"
    elif system == "windows":
        return "x86_64-pc-windows-msvc"
    elif system == "linux":
        if machine in ["arm64", "aarch64"]:
            return "aarch64-unknown-linux-gnu"
        else:
            return "x86_64-unknown-linux-gnu"
    else:
        raise ValueError(f"Unsupported operating system: {system}")


def resolve_c2pa_rs_path(cli_path=None):
    """Resolve and validate the path to the local c2pa-rs sources."""
    raw = os.environ.get("C2PA_RS_PATH") or cli_path

    if not raw:
        print(
            "Error: C2PA_RS_PATH is not set.\n"
            "Set it to the path of the local c2pa-rs checkout, for example:\n"
            "  export C2PA_RS_PATH=/path/to/c2pa-rs\n"
            "  make build-from-source C2PA_RS_PATH=$C2PA_RS_PATH"
        )
        sys.exit(1)

    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        print(f"Error: C2PA_RS_PATH is not a directory: {path}")
        sys.exit(1)

    if not (path / "c2pa_c_ffi" / "Cargo.toml").is_file():
        print(
            f"Error: {path} does not look like a c2pa-rs checkout."
        )
        sys.exit(1)

    return path


def clean_workspace(c2pa_rs_path):
    """Remove all prior c2pa-rs build artifacts (cleans workspace).
    """
    cmd = ["cargo", "clean"]
    print(f"Running: {' '.join(cmd)} (cwd={c2pa_rs_path})")
    try:
        subprocess.run(cmd, cwd=c2pa_rs_path, check=True)
    except FileNotFoundError:
        print(
            "Error: 'cargo' was not found. Install the Rust toolchain "
            "(https://rust-lang.org/tools/install/) and ensure cargo is on PATH:\n"
            '  export PATH="$HOME/.cargo/bin:$PATH"'
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: cargo clean failed (exit code {e.returncode}).")
        sys.exit(e.returncode)


def run_cargo(c2pa_rs_path, extra_args=None, debug=False):
    """Build the FFI crate in the c2pa-rs checkout (release unless debug=True)."""
    cmd = ["cargo", "build", "-p", FFI_PACKAGE, "--features", FFI_FEATURES]
    if not debug:
        cmd.insert(2, "--release")
    if extra_args:
        cmd += extra_args
    print(f"Running: {' '.join(cmd)} (cwd={c2pa_rs_path})")
    try:
        subprocess.run(cmd, cwd=c2pa_rs_path, check=True)
    except FileNotFoundError:
        print(
            "Error: 'cargo' was not found. Install the Rust toolchain "
            "(https://rust-lang.org/tools/install/) and ensure cargo is on PATH:\n"
            '  export PATH="$HOME/.cargo/bin:$PATH"'
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: cargo build failed (exit code {e.returncode}).")
        sys.exit(e.returncode)


def build_universal_macos(c2pa_rs_path, debug=False):
    """Build both macOS arches and lipo them into one universal dylib.
    Returns the path to the universal libc2pa_c.dylib.
    """
    profile = "debug" if debug else "release"
    triples = ["aarch64-apple-darwin", "x86_64-apple-darwin"]
    per_arch_libs = []
    for triple in triples:
        run_cargo(c2pa_rs_path, ["--target", triple], debug=debug)
        lib = c2pa_rs_path / "target" / triple / profile / LIB_NAMES["darwin"]
        if not lib.is_file():
            print(
                f"Error: expected built library not found: {lib}\n"
            )
            sys.exit(1)
        per_arch_libs.append(lib)

    universal = c2pa_rs_path / "target" / profile / LIB_NAMES["darwin"]
    universal.parent.mkdir(parents=True, exist_ok=True)
    lipo_cmd = ["lipo", "-create", *map(str, per_arch_libs),
                "-output", str(universal)]
    print(f"Running: {' '.join(lipo_cmd)}")
    try:
        subprocess.run(lipo_cmd, check=True)
    except FileNotFoundError:
        print("Error: 'lipo' was not found (it ships with the Xcode command line tools).")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: lipo failed (exit code {e.returncode}).")
        sys.exit(e.returncode)
    return universal


def build_native(c2pa_rs_path, debug=False):
    """Build the FFI crate for the host arch. Returns the built library path."""
    profile = "debug" if debug else "release"
    run_cargo(c2pa_rs_path, debug=debug)
    lib_name = LIB_NAMES[platform.system().lower()]
    lib = c2pa_rs_path / "target" / profile / lib_name
    if not lib.is_file():
        print(f"Error: expected built library not found: {lib}")
        sys.exit(1)
    return lib


def copy_to_artifacts(lib_path, platform_id):
    """Copy the built library into artifacts/{platform_id}"""
    platform_dir = ROOT_ARTIFACTS_DIR / platform_id
    if platform_dir.exists():
        shutil.rmtree(platform_dir)
    platform_dir.mkdir(parents=True, exist_ok=True)

    dest = platform_dir / lib_path.name
    shutil.copy2(lib_path, dest)
    print(f"Copied {lib_path} -> {dest}")
    return dest


def stage_into_package(lib_path):
    """Copy the built library into src/c2pa/libs/.
    """
    if PACKAGE_LIBS_DIR.exists():
        shutil.rmtree(PACKAGE_LIBS_DIR)
    PACKAGE_LIBS_DIR.mkdir(parents=True, exist_ok=True)

    dest = PACKAGE_LIBS_DIR / lib_path.name
    shutil.copy2(lib_path, dest)
    print(f"Copied {lib_path} -> {dest}")
    return dest


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build the c2pa C FFI library from a local c2pa-rs checkout."
    )
    parser.add_argument(
        "c2pa_rs_path",
        nargs="?",
        help="Path to the local c2pa-rs sources (overridden by C2PA_RS_PATH).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Runs `cargo clean` first so local c2pa-rs is rebuilt.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build the FFI crate in debug profile instead of release.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    c2pa_rs_path = resolve_c2pa_rs_path(args.c2pa_rs_path)
    print(f"Using c2pa-rs sources at: {c2pa_rs_path}")

    system = platform.system().lower()

    # Determine the target platform id
    env_platform = os.environ.get("C2PA_LIBS_PLATFORM")
    if env_platform:
        print(f"Using platform from environment variable C2PA_LIBS_PLATFORM: {env_platform}")
        platform_id = env_platform
    elif system == "darwin":
        # Default macOS to a universal2 build.
        platform_id = "universal-apple-darwin"
    else:
        platform_id = get_platform_identifier()

    print(f"Target platform: {platform_id}")

    # Optionally start from a fully clean workspace.
    # Enabled via --clean.
    if args.clean:
        clean_workspace(c2pa_rs_path)

    if platform_id == "universal-apple-darwin":
        lib_path = build_universal_macos(c2pa_rs_path, args.debug)
    else:
        lib_path = build_native(c2pa_rs_path, args.debug)

    copy_to_artifacts(lib_path, platform_id)
    stage_into_package(lib_path)
    print("\nLocal native library built and staged successfully.")
    print(f"  c2pa-rs:  {c2pa_rs_path}")
    print(f"  platform: {platform_id}")
    print(f"  profile:  {'debug' if args.debug else 'release'}")


if __name__ == "__main__":
    main()
