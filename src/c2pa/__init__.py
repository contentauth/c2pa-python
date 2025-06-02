__version__ = "0.10.0"

from .c2pa import (
    Builder,
    C2paError,
    Reader,
    C2paSigningAlg,
    C2paSignerInfo,
    Signer,
    Stream,
    sdk_version
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
    'sdk_version'
]
