import unittest

import numpy as np
import pandas as pd

from pragma.trigger_engine import evaluate_trigger


class TP1RiskGateTests(unittest.TestCase):
    def test_far_tp2_cannot_rescue_low_tp1_rr(self):
        close = 100.0 + 0.25 * np.sin(np.arange(30) * 1.3)
        close[-2] = 90.0
        close[-1] = 99.8
        open_ = close.copy()
        high = close + 0.15
        low = close - 0.15
        open_[-1] = close[-1] - 0.10
        high[-1] = close[-1] + 0.20
        low[-1] = close[-1] - 0.20
        volume = np.full(30, 10.0)
        volume[-2] = 100.0
        bars = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "tick_volume": volume,
        })

        result = evaluate_trigger(
            bars, "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=[100.5, 110.0],
        )
        self.assertEqual(result.take_profit_1, 100.5)
        self.assertEqual(result.take_profit_2, 110.0)
        self.assertEqual(result.take_profit, result.take_profit_1)
        self.assertLess(result.rr_ratio, 1.5)
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "LOW_RR")


if __name__ == "__main__":
    unittest.main()
