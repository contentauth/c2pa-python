# Copyright 2025 Adobe. All rights reserved.
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

try:
    from importlib.metadata import version
    __version__ = version("c2pa-python")
except ImportError:  # pragma: no cover
    __version__ = "unknown"

from .c2pa import (
    Builder,
    C2paError,
    Reader,
    C2paSigningAlg,
    C2paSignerInfo,
    Signer,
    Stream,
    sdk_version,
    read_ingredient_file
)  # NOQA

# Re-export C2paError and its subclasses
__all__ = [
    'Builder',
    'C2paError',
    'Reader',
    'C2paSigningAlg',
    'C2paSignerInfo',
    'Signer',
    'Stream',
    'sdk_version',
    'read_ingredient_file'
]
