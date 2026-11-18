import asyncio
import unittest
from decimal import Decimal

from starter import recommend_price, sample_fetch_offers


class RecommendPriceTests(unittest.IsolatedAsyncioTestCase):
    def assert_result(self, result, price, decision):
        self.assertIsInstance(result["price"], Decimal)
        self.assertEqual(result["price"], Decimal(price))
        self.assertEqual(result["decision"], decision)
        self.assertIsInstance(result["reason"], str)
        self.assertTrue(result["reason"].strip())

    async def test_normal_calculation_from_assignment(self):
        result = await recommend_price(
            sample_fetch_offers, Decimal("4900.00"), Decimal("4500.00")
        )
        self.assert_result(result, "4728.00", "APPLY")

    async def test_filters_own_shop_unknown_and_slow_delivery(self):
        async def fetch():
            return {"status": "success", "offers": [
                {"seller": "MyShOp", "price": Decimal("1.00"), "delivery_days": 0},
                {"seller": "UNKNOWN", "price": Decimal("2.00"), "delivery_days": None},
                {"seller": "SLOW", "price": Decimal("3.00"), "delivery_days": 7},
                {"seller": "BOUNDARY", "price": Decimal("150.00"), "delivery_days": 6},
                {"seller": "FAST", "price": Decimal("160.00"), "delivery_days": 0},
            ]}

        self.assert_result(
            await recommend_price(fetch, Decimal("150.00"), Decimal("1.00")),
            "147.75", "APPLY",
        )

    async def test_rounds_discount_down_to_kopeck(self):
        async def fetch():
            return {"status": "success", "offers": [
                {"seller": "PARTS", "price": Decimal("123.45"), "delivery_days": 1},
            ]}

        # 123.45 * 0.985 = 121.59825, rounding down gives 121.59.
        self.assert_result(
            await recommend_price(fetch, Decimal("120.00"), Decimal("1.00")),
            "121.59", "APPLY",
        )

    async def test_respects_minimum_price(self):
        async def fetch():
            return {"status": "success", "offers": [
                {"seller": "PARTS", "price": Decimal("80.00"), "delivery_days": 1},
            ]}

        self.assert_result(
            await recommend_price(fetch, Decimal("100.00"), Decimal("90.00")),
            "90.00", "APPLY",
        )

    async def test_no_eligible_offers_holds_even_below_minimum(self):
        for offers in ([], [
            {"seller": "MYSHOP", "price": Decimal("50.00"), "delivery_days": 1},
            {"seller": "UNKNOWN", "price": Decimal("60.00"), "delivery_days": None},
            {"seller": "SLOW", "price": Decimal("70.00"), "delivery_days": 8},
        ]):
            with self.subTest(offers=offers):
                async def fetch():
                    return {"status": "success", "offers": offers}

                self.assert_result(
                    await recommend_price(fetch, Decimal("80.00"), Decimal("90.00")),
                    "80.00", "HOLD",
                )

    async def test_non_success_status_holds_even_with_offers(self):
        for status in ("partial", "error"):
            with self.subTest(status=status):
                async def fetch():
                    return {"status": status, "offers": [
                        {"seller": "PARTS", "price": Decimal("50.00"), "delivery_days": 1},
                    ]}

                self.assert_result(
                    await recommend_price(fetch, Decimal("80.00"), Decimal("90.00")),
                    "80.00", "HOLD",
                )

    async def test_source_exception_holds_current_price(self):
        async def fetch():
            raise RuntimeError("source unavailable")

        self.assert_result(
            await recommend_price(fetch, Decimal("80.00"), Decimal("90.00")),
            "80.00", "HOLD",
        )

    async def test_timeout_holds_and_cancels_pending_source(self):
        cancelled = asyncio.Event()

        async def fetch():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        # Outer guard prevents a broken implementation hanging the test suite.
        result = await asyncio.wait_for(
            recommend_price(fetch, Decimal("80.00"), Decimal("90.00"), timeout_s=0.01),
            timeout=1.0,
        )
        self.assert_result(result, "80.00", "HOLD")
        self.assertTrue(cancelled.is_set())

    async def test_thirty_percent_boundary_in_both_directions(self):
        cases = (
            ("71.07", "1.00", "70.00", "APPLY"),
            ("71.06", "1.00", "69.99", "REVIEW"),
            ("131.98", "1.00", "130.00", "APPLY"),
            ("132.00", "1.00", "130.02", "REVIEW"),
            # Check the threshold after min_price has been applied.
            ("100.00", "130.00", "130.00", "APPLY"),
            ("100.00", "130.01", "130.01", "REVIEW"),
        )
        for competitor, minimum, expected, decision in cases:
            with self.subTest(competitor=competitor, minimum=minimum):
                async def fetch():
                    return {"status": "success", "offers": [
                        {"seller": "PARTS", "price": Decimal(competitor), "delivery_days": 1},
                    ]}

                self.assert_result(
                    await recommend_price(fetch, Decimal("100.00"), Decimal(minimum)),
                    expected, decision,
                )

    async def test_caller_cancellation_is_not_converted_to_hold(self):
        started = asyncio.Event()

        async def fetch():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            recommend_price(fetch, Decimal("100.00"), Decimal("90.00"))
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
