"""Calculator must stay fast and safe."""
import time, unittest
from tools import execute_tool


def calc(expr):
    return execute_tool("calculate", {"expression": expr})


class CalculatorTests(unittest.TestCase):
    def test_normal_math_still_works(self):
        self.assertEqual(calc("(2 + 3) * 4"), "20")
        self.assertEqual(calc("25 * 4"), "100")
        self.assertEqual(calc("10 / 4"), "2.5")
        self.assertEqual(calc("7 // 2"), "3")
        self.assertEqual(calc("2 ** 10"), "1024")
        self.assertEqual(calc("2 ** -1"), "0.5")
        self.assertEqual(calc("2 ** 1000")[:6], "107150")   # big but fine

    def test_huge_powers_are_refused_quickly(self):
        for expr in ("9**9**9**9", "2**100000", "((9**100)**100)**100", "10**10**10"):
            start = time.time()
            result = calc(expr)
            self.assertTrue(result.startswith("Error:"), (expr, result))
            self.assertLess(time.time() - start, 1.0, expr)

    def test_long_expression_refused(self):
        self.assertTrue(calc("1+" * 150 + "1").startswith("Error:"))

    def test_divide_by_zero_is_an_error_not_a_crash(self):
        self.assertTrue(calc("1/0").startswith("Error:"))

    def test_letters_still_blocked(self):
        self.assertTrue(calc("__import__('os')").startswith("Error:"))


if __name__ == "__main__":
    unittest.main()


class TimezoneTests(unittest.TestCase):
    def test_known_zone_and_utc(self):
        import tools
        self.assertIn("UTC", tools.get_current_time("UTC"))

    def test_bad_name_gives_clear_error(self):
        import tools
        with self.assertRaises(ValueError) as cm:
            tools.get_current_time("Nowhere/Land")
        self.assertIn("Unknown timezone", str(cm.exception))

    def test_missing_database_tells_user_to_install_tzdata(self):
        import tools
        from unittest import mock
        from zoneinfo import ZoneInfoNotFoundError
        with mock.patch.object(tools, "ZoneInfo", side_effect=ZoneInfoNotFoundError("x")):
            with self.assertRaises(ValueError) as cm:
                tools.get_current_date("Asia/Tokyo")
        self.assertIn("pip install tzdata", str(cm.exception))
