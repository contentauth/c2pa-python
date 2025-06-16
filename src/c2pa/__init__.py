try:
    from importlib.metadata import version
    __version__ = version("c2pa-python")
except ImportError:
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
