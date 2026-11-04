import hashlib
import hmac
import json
import unittest
from decimal import Decimal
from unittest.mock import patch

from payments.rollypay import (RollyPayClient, confirmed_paid_for_order,
                               parse_payment_event, verify_signature)


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.raw = b'{"event_type":"payment.paid"}'
        self.timestamp = "1700000000"
        self.secret = "only-for-tests"
        self.sig = hmac.new(self.secret.encode(),
                            self.timestamp.encode() + b"." + self.raw,
                            hashlib.sha256).hexdigest()

    def test_good_signature(self):
        self.assertTrue(verify_signature(self.raw, self.timestamp, self.sig,
                                         self.secret, now=1700000000))

    def test_tampering_and_expiration(self):
        self.assertFalse(verify_signature(self.raw + b"x", self.timestamp,
                                          self.sig, self.secret, now=1700000000))
        self.assertFalse(verify_signature(self.raw, self.timestamp, self.sig,
                                          self.secret, now=1700000400))
        self.assertFalse(verify_signature(self.raw, self.timestamp, "invalid",
                                          self.secret, now=1700000000))
        self.assertFalse(verify_signature(self.raw, "invalid", self.sig,
                                          self.secret, now=1700000000))


class EventTests(unittest.TestCase):
    def setUp(self):
        self.event = {"event_type": "payment.paid", "payment_id": "pay_123",
                      "order_id": "order_99", "status": "paid", "amount": "99.00",
                      "currency": "RUB", "test": False}

    def test_parse_and_compare(self):
        parsed = parse_payment_event(json.dumps(self.event).encode())
        remote = {"payment_id": "pay_123", "order_id": "order_99",
                  "status": "paid", "payment_currency": "RUB", "amount": "99.00"}
        order = {"id": "order_99", "payment_id": "pay_123",
                 "currency": "RUB", "amount": "99.00"}
        self.assertTrue(confirmed_paid_for_order(parsed, remote, order))
        parsed["is_test"] = True
        self.assertFalse(confirmed_paid_for_order(parsed, remote, order))
        parsed["is_test"] = False
        order["amount"] = "199.00"
        self.assertFalse(confirmed_paid_for_order(parsed, remote, order))

    def test_bad_or_incomplete_event(self):
        for change in ({"test": None}, {"amount": "NaN"},
                       {"status": "created"}, {"order_id": "invalid/id"}):
            with self.subTest(change=change):
                data = dict(self.event, **change)
                with self.assertRaises(ValueError):
                    parse_payment_event(json.dumps(data).encode())

    @patch("payments.rollypay.urlopen")
    def test_balance_api_nonce(self, open_url):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _): return b'{"available_usdt":"0.00"}'
        open_url.return_value = Response()
        self.assertTrue(RollyPayClient("test-key").api_healthy())
        req = open_url.call_args.args[0]
        self.assertEqual(req.get_header("X-api-key"), "test-key")
        self.assertTrue(req.get_header("X-nonce"))
        self.assertTrue(req.full_url.endswith("/balance"))

    @patch("payments.rollypay.urlopen")
    def test_sandbox_only(self, open_url):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _): return b'{"pay_url":"https://pay.rollypay.io/test"}'
        open_url.return_value = Response()
        RollyPayClient("test-key").create_sandbox_payment(order_id="order_1",
                         amount=Decimal("99.00"), description="Test")
        req = open_url.call_args.args[0]
        self.assertTrue(json.loads(req.data)["test"])


if __name__ == "__main__":
    unittest.main()
