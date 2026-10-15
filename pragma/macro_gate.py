"""Interface seam for Begonya macro bias integration.

This intentionally does not copy or reimplement Begonya's macro engine yet.
The adapter can be replaced with a bridge to Begonya's real output later.
"""
from dataclasses import dataclass
from enum import IntEnum


class Bias(IntEnum):
    SHORT = -1
    NEUTRAL = 0
    LONG = 1


@dataclass(frozen=True)
class MacroDecision:
    bias: Bias
    source: str = "mock"
    reason: str = "Macro engine not connected"


class MacroGate:
    def get_bias(self) -> MacroDecision:
        """Safe default: neutral until a real macro source is connected."""
        return MacroDecision(bias=Bias.NEUTRAL)
