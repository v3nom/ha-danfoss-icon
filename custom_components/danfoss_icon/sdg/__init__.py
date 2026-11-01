"""Async Python client for the SecureDeviceGrid (SDG) protocol.

A port of the client side of OpenSDG by Pavel Fedin (Sonic-Amiga):
https://github.com/Sonic-Amiga/opensdg (GPL-3.0). SecureDeviceGrid is
proprietary technology of Trifork; this code is for non-commercial use.

Vendored unchanged from devireg-ha by infestdead
(https://github.com/infestdead/devireg-ha, GPL-3.0, commit b7685a5).
Keep it in sync with upstream rather than editing it here.
"""

from .errors import (
    ConnectionRefused,
    PairingFailed,
    PeerTimeout,
    ProtocolError,
    SDGError,
)
from .grid import DANFOSS_SERVERS, Grid, generate_private_key, public_key
from .tunnel import Tunnel

__all__ = [
    "DANFOSS_SERVERS",
    "ConnectionRefused",
    "Grid",
    "PairingFailed",
    "PeerTimeout",
    "ProtocolError",
    "SDGError",
    "Tunnel",
    "generate_private_key",
    "public_key",
]
