# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.

"""
Canonical list of profiling scenario names.

Single source of truth shared by:
- run_profile.py (driver)
- scenarios.py

This module intentionally has zero imports so the driver can read the names
without pulling in c2pa or any other dependency.
"""

SCENARIO_NAMES = (
    "reader_jpeg", "reader_mp4", "reader_wav",
    "builder_sign_jpeg", "builder_sign_gif", "builder_sign_heic",
    "builder_sign_m4a", "builder_sign_png", "builder_sign_webp",
    "builder_sign_avi", "builder_sign_mp4", "builder_sign_tiff",
    "builder_sign_jpeg_parent_of",
    "builder_sign_jpeg_component_of",
    "builder_sign_jpeg_parent_and_component",
    "builder_sign_jpeg_parent_and_component_mixed_mime",
    "builder_sign_jpeg_two_components_same_mime",
    "builder_sign_jpeg_two_components_mixed_mime",
    "builder_sign_jpeg_archive_roundtrip",
)
