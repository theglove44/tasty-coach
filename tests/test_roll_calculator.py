import unittest
from datetime import date

from utils.roll_calculator import (
    calculate_roll_down_and_out_scenario,
    calculate_roll_down_scenario,
)


class TestRollCalculator(unittest.TestCase):
    def test_roll_down_skips_iron_condor_strike_shift(self):
        """A single target strike is ambiguous for a four-leg iron condor."""
        current_position = {
            "expiration": date(2026, 5, 15),
            "dte": 22,
            "legs": [
                {"action": "BTO", "option_type": "PUT", "strike": 25.0, "quantity": 1},
                {"action": "STO", "option_type": "PUT", "strike": 30.0, "quantity": 1},
                {"action": "STO", "option_type": "CALL", "strike": 45.0, "quantity": 1},
                {"action": "BTO", "option_type": "CALL", "strike": 50.0, "quantity": 1},
            ],
        }

        scenarios = calculate_roll_down_scenario(
            current_position,
            target_strikes=[28.0],
            new_chain_data={"options": []},
            current_chain_data={"options": []},
        )

        self.assertEqual(scenarios, [])

    def test_roll_down_and_out_skips_iron_condor_strike_shift(self):
        """A single target strike is ambiguous for a four-leg iron condor."""
        current_position = {
            "expiration": date(2026, 5, 15),
            "dte": 22,
            "legs": [
                {"action": "BTO", "option_type": "PUT", "strike": 25.0, "quantity": 1},
                {"action": "STO", "option_type": "PUT", "strike": 30.0, "quantity": 1},
                {"action": "STO", "option_type": "CALL", "strike": 45.0, "quantity": 1},
                {"action": "BTO", "option_type": "CALL", "strike": 50.0, "quantity": 1},
            ],
        }

        scenarios = calculate_roll_down_and_out_scenario(
            current_position,
            target_strikes=[28.0],
            target_expirations=[date(2026, 6, 19)],
            new_chain_data={date(2026, 6, 19): {"options": []}},
            current_chain_data={"options": []},
        )

        self.assertEqual(scenarios, [])


if __name__ == "__main__":
    unittest.main()
