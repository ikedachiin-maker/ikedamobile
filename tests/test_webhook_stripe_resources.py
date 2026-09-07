import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import webhook


class StripeResource:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class StripeWebhookResourceTests(unittest.TestCase):
    def post_event(self, event):
        with (
            patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "test-secret"}),
            patch.object(
                webhook.stripe.Webhook,
                "construct_event",
                return_value=event,
            ),
        ):
            return webhook.app.test_client().post(
                "/webhook",
                data=b"{}",
                headers={"Stripe-Signature": "test-signature"},
            )

    def test_payment_intent_stripe_resource_is_recorded(self):
        event = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": StripeResource(
                    {
                        "id": "pi_test_resource",
                        "metadata": {"application_id": "application_test"},
                    }
                )
            },
        }

        with patch.object(
            webhook,
            "record_succeeded_payment",
            return_value={"status": "recorded"},
        ) as record_payment:
            response = self.post_event(event)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "recorded"})
        record_payment.assert_called_once_with("pi_test_resource")

    def test_checkout_session_stripe_resource_sends_form_link(self):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": StripeResource(
                    {
                        "id": "cs_test_resource",
                        "customer_details": {"email": "test@example.com"},
                        "amount_total": 300000,
                    }
                )
            },
        }

        with (
            patch.object(webhook, "load_reminder_log", return_value={}),
            patch.object(webhook, "send_form_link", return_value=True) as send_form_link,
            patch.object(webhook, "save_reminder_log") as save_reminder_log,
        ):
            response = self.post_event(event)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})
        send_form_link.assert_called_once_with("test@example.com", 3000)
        save_reminder_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
