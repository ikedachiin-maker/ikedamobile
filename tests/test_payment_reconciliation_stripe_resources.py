import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import payment_reconciliation


class StripeResource:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class PaymentIntent:
    def __init__(self, payment_id, metadata, amount, status="succeeded"):
        self.id = payment_id
        self.metadata = metadata
        self.amount = amount
        self.status = status


class PaymentIntentList:
    def __init__(self, intents):
        self.intents = intents

    def auto_paging_iter(self):
        return iter(self.intents)


class PaymentReconciliationStripeResourceTests(unittest.TestCase):
    def test_snapshot_matches_stripe_metadata_resource(self):
        snapshot = {
            "application_id": "application_test",
            "plan": "consul",
            "lines": 1,
            "email": "test@example.com",
            "amount": 3000,
        }
        intent = PaymentIntent(
            "pi_test_resource",
            StripeResource(
                {
                    "application_id": "application_test",
                    "plan": "consul",
                    "lines": "1",
                    "email": "test@example.com",
                }
            ),
            3000,
        )

        self.assertTrue(payment_reconciliation._snapshot_matches_intent(snapshot, intent))

    def test_recent_reconciliation_accepts_stripe_metadata_resource(self):
        intent = PaymentIntent(
            "pi_test_resource",
            StripeResource({"application_id": "application_test"}),
            3000,
        )

        with (
            patch.object(
                payment_reconciliation.stripe.PaymentIntent,
                "list",
                return_value=PaymentIntentList([intent]),
            ),
            patch.object(
                payment_reconciliation,
                "record_succeeded_payment",
                return_value={"status": "recorded"},
            ) as record_payment,
        ):
            summary = payment_reconciliation.reconcile_recent_payments()

        self.assertEqual(summary, {"checked": 1, "recorded": 1, "pending": 0, "needs_review": 0})
        record_payment.assert_called_once_with("pi_test_resource")


if __name__ == "__main__":
    unittest.main()
