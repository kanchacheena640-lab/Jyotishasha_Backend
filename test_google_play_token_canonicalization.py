"""Google Play purchase tokens reach Google and the payment ledger as the same exact string.

Before this fix a client-sent alias such as "TOKEN#1" was used verbatim as the ledger key while the URL sent to
Google dropped the fragment, so the real purchase verified again under a new key: one purchase could be redeemed
any number of times. Aliases are now refused before any Google call, path segments are percent-encoded, and the
identifiers Google echoes back must match. Database-free and network-free: the Google session is a mock.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

import requests
from flask import Flask

os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")

from modules.payments import google_play_provider as provider_module
from modules.payments.google_play_identifiers import (
    MAX_PURCHASE_TOKEN_LENGTH, is_valid_product_id, is_valid_purchase_token, path_segment,
)
from modules.payments.google_play_models import GooglePlayVerificationStatus
from modules.payments.google_play_provider import GooglePlayProvider

# The shape of a real Google Play purchase token (letters, digits, ".", "-", "_"; ~150-200 characters).
REAL_TOKEN = ("ncpgjlamebnkhbkhfapdmhbo.AO-J1OxQn4Zq8vJ3sZ_1yR7bY9tL0kWm2pXc5aDfGhJkLmNoPqRsTuVwXyZ-abcdEFGH"
              "ijklMNOPqrstUVWX_yz0123456789-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789.aBcDeFgHiJ")
PACKAGE = "com.jyotishasha.app"
BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"

ALIASES = [
    REAL_TOKEN + "#1", REAL_TOKEN + "#", REAL_TOKEN + "?x=1", REAL_TOKEN + "&x", REAL_TOKEN + "/",
    "x/../../reports51/tokens/" + REAL_TOKEN, "%2e%2e/%2e%2e/reports51/tokens/" + REAL_TOKEN,
    REAL_TOKEN.replace(".", "%2E", 1), " " + REAL_TOKEN, REAL_TOKEN + " ", REAL_TOKEN + "\n", REAL_TOKEN + "\x00",
    REAL_TOKEN + "é", REAL_TOKEN + ":acknowledge", ".", "..", "...", "", "a" * (MAX_PURCHASE_TOKEN_LENGTH + 1),
    None, 12345, ["x"],
]


def ok_response(body):
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = body
    return response


class IdentifierRuleTests(unittest.TestCase):
    def test_real_token_shapes_are_accepted_and_path_encoding_is_the_identity(self):
        for token in (REAL_TOKEN, "a", "A-b_c.d~e", "x" * MAX_PURCHASE_TOKEN_LENGTH, "1.2.3"):
            with self.subTest(token=token):
                self.assertTrue(is_valid_purchase_token(token))
                self.assertEqual(path_segment(token), token)

    def test_aliases_and_unsafe_tokens_are_refused(self):
        for token in ALIASES:
            with self.subTest(token=token):
                self.assertFalse(is_valid_purchase_token(token))

    def test_product_ids(self):
        for product_id in ("reports51", "reports99", "relationship_report199", "asknow8q", "chat.pack_10", "9pack"):
            self.assertTrue(is_valid_product_id(product_id), product_id)
        for product_id in ("Reports99", "reports99#", "reports99/../reports51", "../reports51", ".reports", "_x",
                           "reports 99", "reports-99", "", "r" * 140, None, 99):
            self.assertFalse(is_valid_product_id(product_id), product_id)

    def test_path_segment_encodes_separators(self):
        self.assertEqual(path_segment("a/b?c#d"), "a%2Fb%3Fc%23d")


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        patcher = patch.object(provider_module, "get_android_publisher_session", return_value=self.session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def verify_product(self, token, product_id="reports51", body=None):
        self.session.get.return_value = ok_response(body if body is not None else {"purchaseState": 0})
        return GooglePlayProvider().verify_product_purchase(
            purchase_token=token, product_id=product_id, package_name=PACKAGE)

    def test_product_aliases_never_reach_google(self):
        for token in ALIASES:
            with self.subTest(token=token):
                self.session.reset_mock()
                result = self.verify_product(token)
                self.assertEqual(result.verification_status, GooglePlayVerificationStatus.INVALID_TOKEN)
                self.session.get.assert_not_called()

    def test_malformed_product_ids_never_reach_google(self):
        for product_id in ("reports99/../reports51", "reports99#", "Reports51", "../x"):
            with self.subTest(product_id=product_id):
                self.session.reset_mock()
                result = self.verify_product(REAL_TOKEN, product_id)
                self.assertEqual(result.verification_status, GooglePlayVerificationStatus.INVALID_TOKEN)
                self.session.get.assert_not_called()

    def test_valid_product_purchase_requests_exactly_the_stored_token(self):
        result = self.verify_product(REAL_TOKEN)
        self.assertEqual(result.verification_status, GooglePlayVerificationStatus.VERIFIED)
        url = self.session.get.call_args.args[0]
        expected = f"{BASE}/applications/{PACKAGE}/purchases/products/reports51/tokens/{REAL_TOKEN}"
        self.assertEqual(url, expected)
        # What actually goes on the wire is the same path: no fragment, query or dot-segment rewriting.
        self.assertEqual(requests.Request("GET", url).prepare().url, expected)
        self.assertEqual(result.purchase_token, REAL_TOKEN)

    def test_google_echo_of_a_different_token_or_product_is_refused(self):
        for body in ({"purchaseState": 0, "purchaseToken": REAL_TOKEN + "x"},
                     {"purchaseState": 0, "productId": "reports99"}):
            with self.subTest(body=body):
                result = self.verify_product(REAL_TOKEN, body=body)
                self.assertEqual(result.verification_status, GooglePlayVerificationStatus.INVALID_TOKEN)

    def test_google_echo_of_the_same_identifiers_or_none_still_verifies(self):
        for body in ({"purchaseState": 0}, {"purchaseState": 0, "purchaseToken": REAL_TOKEN, "productId": "reports51"}):
            with self.subTest(body=body):
                self.assertEqual(self.verify_product(REAL_TOKEN, body=body).verification_status,
                                 GooglePlayVerificationStatus.VERIFIED)

    def test_subscription_aliases_never_reach_google_and_valid_token_is_exact(self):
        for token in ALIASES:
            with self.subTest(token=token):
                self.session.reset_mock()
                result = GooglePlayProvider().verify_subscription_purchase(purchase_token=token, package_name=PACKAGE)
                self.assertEqual(result.verification_status, GooglePlayVerificationStatus.INVALID_TOKEN)
                self.session.get.assert_not_called()
        self.session.reset_mock()
        self.session.get.return_value = ok_response({"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE"})
        GooglePlayProvider().verify_subscription_purchase(purchase_token=REAL_TOKEN, package_name=PACKAGE)
        self.assertEqual(self.session.get.call_args.args[0],
                         f"{BASE}/applications/{PACKAGE}/purchases/subscriptionsv2/tokens/{REAL_TOKEN}")

    def test_acknowledge_encodes_the_google_supplied_subscription_id(self):
        verification = MagicMock(verification_status=GooglePlayVerificationStatus.VERIFIED,
                                 acknowledgement_state="ACKNOWLEDGEMENT_STATE_PENDING",
                                 purchase_state="SUBSCRIPTION_STATE_ACTIVE", subscription_id="plan/../x",
                                 product_id=None)
        posted = MagicMock(spec=requests.Response)
        posted.status_code = 200
        self.session.post.return_value = posted
        with patch.object(GooglePlayProvider, "verify_subscription_purchase", return_value=verification):
            GooglePlayProvider().acknowledge_subscription(purchase_token=REAL_TOKEN, package_name=PACKAGE)
        url = self.session.post.call_args.args[0]
        self.assertIn("/purchases/subscriptions/plan%2F..%2Fx/tokens/", url)
        self.assertTrue(url.endswith(f"/tokens/{REAL_TOKEN}:acknowledge"))


class ReportConfirmRouteTests(unittest.TestCase):
    def setUp(self):
        from routes import routes_google_report_confirm as route_module
        self.route_module = route_module
        app = Flask(__name__)
        app.register_blueprint(route_module.routes_google_report_confirm)
        self.client = app.test_client()

    def post(self, token, product_id="reports51"):
        body = {"purchase_token": token, "product_id": product_id, "name": "N", "email": "e@example.invalid",
                "product": "promotion_timing"}
        with patch.object(self.route_module, "PaymentService") as service:
            response = self.client.post("/api/reports/google/confirm", json=body)
        return response, service

    def test_aliases_and_bad_product_ids_get_400_before_any_payment_processing(self):
        for token, product_id in [(t, "reports51") for t in ALIASES if isinstance(t, str) and t] + \
                                 [(REAL_TOKEN, "reports99/../reports51"), (REAL_TOKEN, "Reports51")]:
            with self.subTest(token=token, product_id=product_id):
                response, service = self.post(token, product_id)
                self.assertEqual(response.status_code, 400)
                service.assert_not_called()

    def test_a_valid_token_is_passed_on_unchanged_as_the_ledger_identity(self):
        response, service = self.post(REAL_TOKEN)
        payment_request = service.return_value.process_payment.call_args.args[0]
        self.assertEqual(payment_request.payment_id, REAL_TOKEN)
        self.assertEqual(payment_request.reference, REAL_TOKEN)
        self.assertEqual(payment_request.metadata, {"product_id": "reports51"})


class SubscriptionConfirmRouteTests(unittest.TestCase):
    def test_aliases_get_400_before_any_payment_processing(self):
        from flask_jwt_extended import JWTManager, create_access_token
        from routes import routes_google_purchase_confirm as route_module
        app = Flask(__name__)
        app.config["JWT_SECRET_KEY"] = "local-test-secret-not-used-anywhere-else-0123456789"
        JWTManager(app)
        app.register_blueprint(route_module.routes_google_purchase_confirm)
        with app.app_context():
            headers = {"Authorization": f"Bearer {create_access_token(identity='7')}"}
        client = app.test_client()
        with patch("modules.subscription.dual_write_adapter.resolve_profile_id_from_account_user_id", return_value=7), \
             patch.object(route_module, "PaymentService") as service:
            for token in [t for t in ALIASES if isinstance(t, str) and t]:
                with self.subTest(token=token):
                    response = client.post("/api/subscription/google/confirm", headers=headers,
                                           json={"purchase_token": token, "platform": "ANDROID"})
                    self.assertEqual(response.status_code, 400)
            service.assert_not_called()


class ChatPackTests(unittest.TestCase):
    def test_a_chat_pack_alias_is_refused_without_a_google_call_or_grant(self):
        from modules.services import chatpack_google_verify as chat
        product_id = next(iter(chat.CHATPACK_PRODUCT_MAP))
        session = MagicMock()
        with patch.object(chat, "ChatPack") as packs, patch.object(chat, "db") as db, \
             patch.object(chat, "_emit_chatpack_event"), \
             patch.object(provider_module, "GOOGLE_PLAY_PACKAGE_NAME", PACKAGE), \
             patch.object(provider_module, "get_android_publisher_session", return_value=session):
            packs.query.filter_by.return_value.first.return_value = None
            result = chat.verify_google_chatpack(7, product_id, REAL_TOKEN + "#replay")
        self.assertFalse(result["success"])
        session.get.assert_not_called()
        db.session.add.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
