"""Brevo SMTP relay + Gmail fallback for paid-report email. Mocked smtplib only:
no network connection is opened and no email is sent."""
import contextlib
import io
import os
import ssl
import tempfile
import unittest
from email.utils import parseaddr, parsedate_to_datetime
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, call, patch

import email_utils
from modules.payments.report_delivery_service import (
    attachment_filename, deliver_generated_report, delivery_message, report_display_name,
)

GMAIL_ENV = {"SENDER_EMAIL": "legacy.sender@gmail.com", "SENDER_PASSWORD": "gmail-app-pw-SECRET"}
BREVO_ENV = {
    "SMTP_HOST": "smtp-relay.brevo.com", "SMTP_PORT": "587",
    "SMTP_USER": "relay-login@smtp-brevo.example", "SMTP_PASSWORD": "brevo-smtp-key-SECRET",
    "SENDER_EMAIL": "reports@jyotishasha.com", "SENDER_NAME": "Jyotishasha Pvt. Ltd.",
    "REPLY_TO": "support@jyotishasha.com",
}
SECRETS = ("gmail-app-pw-SECRET", "brevo-smtp-key-SECRET")
PDF = b"%PDF-1.7\n" + bytes(range(256)) * 8 + b"\n%%EOF"


def env(values):
    """Exactly these variables (nothing inherited from the machine or .env)."""
    return patch.dict(os.environ, values, clear=True)


class _Base(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="career_report_Ravi_Kumar_")
        handle.write(PDF)
        handle.close()
        self.path = handle.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    def send(self, values, *args, **kwargs):
        out = io.StringIO()
        with env(values), patch("email_utils.smtplib.SMTP") as smtp, contextlib.redirect_stdout(out):
            email_utils.send_email("buyer@example.com", "Your Career Report", "Hello Ravi,\n\nBody.", self.path, *args, **kwargs)
        server = smtp.return_value
        return smtp, server, server.send_message.call_args.args[0], out.getvalue()


class TransportSelectionTests(_Base):
    def test_gmail_fallback_when_relay_settings_absent(self):
        smtp, server, msg, _ = self.send(GMAIL_ENV)
        smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=email_utils.SMTP_TIMEOUT_SECONDS)
        server.login.assert_called_once_with("legacy.sender@gmail.com", "gmail-app-pw-SECRET")
        self.assertEqual(parseaddr(msg["From"])[1], "legacy.sender@gmail.com")
        self.assertIsNone(msg["Reply-To"])

    def test_brevo_relay_uses_smtp_credentials_and_starttls_before_login(self):
        smtp, server, msg, _ = self.send(BREVO_ENV)
        smtp.assert_called_once_with("smtp-relay.brevo.com", 587, timeout=email_utils.SMTP_TIMEOUT_SECONDS)
        self.assertEqual(server.method_calls[:2], [call.starttls(context=ANY), call.login("relay-login@smtp-brevo.example", "brevo-smtp-key-SECRET")])
        server.send_message.assert_called_once()
        server.quit.assert_called_once()

    def test_starttls_verifies_certificate_and_hostname(self):
        for values in (GMAIL_ENV, BREVO_ENV):
            _, server, _, _ = self.send(values)
            context = server.starttls.call_args.kwargs["context"]
            self.assertIsInstance(context, ssl.SSLContext)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertGreater(len(context.get_ca_certs()), 0)

    def test_relay_port_default_and_override(self):
        no_port = {k: v for k, v in BREVO_ENV.items() if k != "SMTP_PORT"}
        smtp, *_ = self.send(no_port)
        self.assertEqual(smtp.call_args.args[1], 587)
        smtp, *_ = self.send({**BREVO_ENV, "SMTP_PORT": "2525"})
        self.assertEqual(smtp.call_args.args[1], 2525)

    def test_partial_relay_config_raises_before_connecting_and_names_only_variables(self):
        partial = {k: v for k, v in BREVO_ENV.items() if k != "SMTP_PASSWORD"}
        with env(partial), patch("email_utils.smtplib.SMTP") as smtp:
            with self.assertRaises(ValueError) as caught:
                email_utils.send_email("buyer@example.com", "s", "b", self.path)
        smtp.assert_not_called()
        self.assertIn("SMTP_PASSWORD", str(caught.exception))
        for value in partial.values():
            self.assertNotIn(value, str(caught.exception))

    def test_settings_resolve_at_send_time(self):
        with env(GMAIL_ENV):
            self.assertEqual(email_utils.smtp_settings()["transport"], "gmail")
        with env(BREVO_ENV):
            self.assertEqual(email_utils.smtp_settings()["transport"], "smtp-relay")


class HeaderTests(_Base):
    def test_from_reply_to_and_dkim_aligned_domain(self):
        _, _, msg, _ = self.send(BREVO_ENV)
        self.assertEqual(msg["From"], "\"Jyotishasha Pvt. Ltd.\" <reports@jyotishasha.com>")
        self.assertEqual(parseaddr(msg["From"])[1].rpartition("@")[2], "jyotishasha.com")
        self.assertEqual(msg["Reply-To"], "support@jyotishasha.com")
        self.assertEqual(msg["To"], "buyer@example.com")
        self.assertEqual(msg["Subject"], "Your Career Report")

    def test_valid_date_and_message_id(self):
        _, _, msg, _ = self.send(BREVO_ENV)
        self.assertIsNotNone(parsedate_to_datetime(msg["Date"]).tzinfo)
        mid = msg["Message-ID"]
        self.assertTrue(mid.startswith("<") and mid.endswith("@jyotishasha.com>"), mid)
        _, _, second, _ = self.send(BREVO_ENV)
        self.assertNotEqual(mid, second["Message-ID"])

    def test_sender_name_defaults_when_unset(self):
        values = {k: v for k, v in BREVO_ENV.items() if k != "SENDER_NAME"}
        _, _, msg, _ = self.send(values)
        self.assertEqual(parseaddr(msg["From"]), ("Jyotishasha Pvt. Ltd.", "reports@jyotishasha.com"))


class BodyAndAttachmentTests(_Base):
    def test_structure_plain_html_and_pdf(self):
        _, _, msg, _ = self.send(BREVO_ENV, attachment_filename="Jyotishasha-Career-Report.pdf")
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        parts = msg.get_payload()
        self.assertEqual(len(parts), 2)  # same top-level shape the existing tests assert
        alternative, pdf = parts
        self.assertEqual([p.get_content_type() for p in alternative.get_payload()], ["text/plain", "text/html"])
        self.assertIn("Hello Ravi,", alternative.get_payload()[0].get_content())
        self.assertIn("<p>Hello Ravi,</p>", alternative.get_payload()[1].get_content())
        self.assertEqual(pdf.get_content_type(), "application/pdf")
        self.assertEqual(pdf.get_filename(), "Jyotishasha-Career-Report.pdf")

    def test_pdf_bytes_are_identical(self):
        _, _, msg, _ = self.send(BREVO_ENV)
        pdf = msg.get_payload()[1]
        self.assertEqual(pdf.get_payload(decode=True), PDF)
        self.assertEqual(pdf["Content-Transfer-Encoding"], "base64")

    def test_default_attachment_name_never_uses_disk_path(self):
        _, _, msg, _ = self.send(GMAIL_ENV)
        name = msg.get_payload()[1].get_filename()
        self.assertEqual(name, "Jyotishasha-Report.pdf")
        self.assertNotIn("Ravi", name)

    def test_html_escapes_text_and_links_only_existing_urls(self):
        html = email_utils._html_body("Hello <b>Ravi</b> & co,\n\nReview:\nhttps://www.jyotishasha.com/review#t=abc.def")
        self.assertIn("Hello &lt;b&gt;Ravi&lt;/b&gt; &amp; co,", html)
        self.assertIn('<a href="https://www.jyotishasha.com/review#t=abc.def">https://www.jyotishasha.com/review#t=abc.def</a>', html)
        self.assertEqual(html.count("<a "), 1)
        self.assertNotIn("<img", html)

    def test_non_ascii_text_never_goes_out_as_raw_8bit(self):
        # Short Devanagari lines are what the stdlib would otherwise send as 8bit.
        for body in ("Hello राम,\n\nPlease find attached your report.",
                     "नमस्ते,\n\nअपना अनुभव साझा करें:\nhttps://www.jyotishasha.com/hi/review#t=abc"):
            with self.subTest(body=body[:12]):
                with env(BREVO_ENV), patch("email_utils.smtplib.SMTP") as smtp, contextlib.redirect_stdout(io.StringIO()):
                    email_utils.send_email("buyer@example.com", "Your Career Report", body, self.path)
                msg = smtp.return_value.send_message.call_args.args[0]
                plain, html = msg.get_payload()[0].get_payload()
                self.assertEqual(plain["Content-Transfer-Encoding"], "base64")
                self.assertEqual(html["Content-Transfer-Encoding"], "base64")
                self.assertEqual(plain.get_content().rstrip("\n"), body)
                wire = msg.as_bytes(policy=msg.policy.clone(linesep="\r\n"))
                self.assertTrue(wire.isascii())
                self.assertLessEqual(max(len(line) for line in wire.split(b"\r\n")), 998)

    def test_ascii_text_uses_7bit_or_quoted_printable(self):
        _, _, msg, _ = self.send(BREVO_ENV)
        plain, html = msg.get_payload()[0].get_payload()
        self.assertIn(plain["Content-Transfer-Encoding"], ("7bit", "quoted-printable"))
        self.assertIn(html["Content-Transfer-Encoding"], ("7bit", "quoted-printable"))

    def test_hindi_body_survives(self):
        out = io.StringIO()
        with env(BREVO_ENV), patch("email_utils.smtplib.SMTP") as smtp, contextlib.redirect_stdout(out):
            email_utils.send_email("buyer@example.com", "Your Career Report", "नमस्ते,\n\nअपना अनुभव साझा करें", self.path)
        msg = smtp.return_value.send_message.call_args.args[0]
        plain, html = msg.get_payload()[0].get_payload()
        self.assertIn("अपना अनुभव साझा करें", plain.get_content())
        self.assertIn("अपना अनुभव साझा करें", html.get_content())


class FailureTests(_Base):
    def test_login_failure_propagates_unchanged_and_closes(self):
        with env(BREVO_ENV), patch("email_utils.smtplib.SMTP") as smtp:
            smtp.return_value.login.side_effect = RuntimeError("535 auth failed")
            with self.assertRaises(RuntimeError) as caught:
                email_utils.send_email("buyer@example.com", "s", "b", self.path)
        self.assertEqual(str(caught.exception), "535 auth failed")
        smtp.return_value.send_message.assert_not_called()
        smtp.return_value.close.assert_called_once()

    def test_connect_timeout_propagates(self):
        with env(BREVO_ENV), patch("email_utils.smtplib.SMTP", side_effect=TimeoutError("timed out")):
            with self.assertRaises(TimeoutError):
                email_utils.send_email("buyer@example.com", "s", "b", self.path)

    def test_quit_failure_after_accepted_send_is_not_a_failure(self):
        with env(BREVO_ENV), patch("email_utils.smtplib.SMTP") as smtp, contextlib.redirect_stdout(io.StringIO()):
            smtp.return_value.quit.side_effect = OSError("connection reset")
            email_utils.send_email("buyer@example.com", "s", "b", self.path)
        smtp.return_value.send_message.assert_called_once()

    def test_invalid_pdf_never_connects(self):
        with open(self.path, "wb") as f:
            f.write(b"not a pdf")
        with env(BREVO_ENV), patch("email_utils.smtplib.SMTP") as smtp:
            with self.assertRaises(ValueError):
                email_utils.send_email("buyer@example.com", "s", "b", self.path)
        smtp.assert_not_called()

    def test_no_secret_in_success_log(self):
        for values in (GMAIL_ENV, BREVO_ENV):
            *_, log = self.send(values)
            for secret in SECRETS:
                self.assertNotIn(secret, log)


def order(**overrides):
    values = dict(
        id=42, name="Ravi Kumar", email="buyer@example.com", product="career_report",
        language="en", payment_status="PAID", status="PAID", report_stage="Ready",
        email_status="NOT_ATTEMPTED", email_error=None, email_last_attempt_at=None,
        email_sent_at=None, pdf_url=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class SubjectTests(unittest.TestCase):
    def test_subject_has_report_once(self):
        cases = {
            "career_report": "Your Career Report",
            "financial_stability_report": "Your Financial Stability Report",
            "government_job_report": "Your Government Job Report",
            "relationship_future_report": "Your Love & Marriage Life Report",
            "money_growth_timing": "Your Money Growth Timing Report",
            None: "Your Astrology Report",
            "report": "Your Astrology Report",
        }
        with env({}):
            for product, expected in cases.items():
                with self.subTest(product=product):
                    subject, _ = delivery_message(order(product=product))
                    self.assertEqual(subject, expected)
                    self.assertNotIn("Report Report", subject)

    def test_attachment_filenames_are_neutral(self):
        self.assertEqual(attachment_filename(order()), "Jyotishasha-Career-Report.pdf")
        self.assertEqual(attachment_filename(order(product="relationship_future_report")), "Jyotishasha-Love-Marriage-Life-Report.pdf")
        for product in ("career_report", "relationship_future_report", None):
            name = attachment_filename(order(product=product, name="Ravi Kumar", id=987))
            self.assertNotIn("Ravi", name)
            self.assertNotIn("987", name)
        self.assertEqual(report_display_name(order(product="sadhesati_report")), "Sadhesati Report")


class DeliveryIntegrationTests(_Base):
    """deliver_generated_report -> real send_email -> mocked SMTP, both transports."""

    def _deliver(self, values, report_order, smtp_side_effect=None):
        fake_order_model = SimpleNamespace(query=SimpleNamespace(get=MagicMock(return_value=report_order)))
        with env(values), patch("email_utils.smtplib.SMTP") as smtp, \
             patch("modules.payments.report_delivery_service.Order", fake_order_model), \
             patch("modules.payments.report_delivery_service.db", MagicMock()), \
             contextlib.redirect_stdout(io.StringIO()):
            if smtp_side_effect:
                smtp.return_value.send_message.side_effect = smtp_side_effect
            try:
                deliver_generated_report(report_order.id, report_order.pdf_url, send_email_fn=email_utils.send_email)
            finally:
                self.smtp = smtp

    def test_success_on_both_transports_records_sent(self):
        for values, host in ((GMAIL_ENV, "smtp.gmail.com"), (BREVO_ENV, "smtp-relay.brevo.com")):
            with self.subTest(host=host):
                self.setUp()
                report_order = order(pdf_url=self.path)
                self._deliver(values, report_order)
                msg = self.smtp.return_value.send_message.call_args.args[0]
                self.assertEqual(self.smtp.call_args.args[0], host)
                self.assertEqual(msg["Subject"], "Your Career Report")
                self.assertEqual(msg.get_payload()[1].get_filename(), "Jyotishasha-Career-Report.pdf")
                self.assertEqual(report_order.email_status, "SENT")
                self.assertIsNone(report_order.pdf_url)
                self.assertFalse(os.path.exists(self.path))
                self.assertEqual(report_order.payment_status, "PAID")

    def test_relay_failure_records_failed_and_keeps_pdf_for_retry(self):
        report_order = order(pdf_url=self.path)
        with self.assertRaises(RuntimeError):
            self._deliver(BREVO_ENV, report_order, smtp_side_effect=RuntimeError("421 try later"))
        self.assertEqual(report_order.email_status, "FAILED")
        self.assertIn("421 try later", report_order.email_error)
        for secret in SECRETS:
            self.assertNotIn(secret, report_order.email_error)
        self.assertEqual(report_order.pdf_url, self.path)
        self.assertTrue(os.path.exists(self.path))


class BackwardCompatibilityTests(_Base):
    def test_legacy_four_positional_argument_call(self):
        # report_writer.py calls send_email(email, subject, body, pdf_path)
        smtp, server, msg, _ = self.send(GMAIL_ENV)
        server.send_message.assert_called_once()

    def test_send_email_fn_fakes_with_four_args_and_kwargs_still_work(self):
        calls = []
        report_order = order(pdf_url=self.path)
        fake_order_model = SimpleNamespace(query=SimpleNamespace(get=MagicMock(return_value=report_order)))
        with env({}), patch("modules.payments.report_delivery_service.Order", fake_order_model), \
             patch("modules.payments.report_delivery_service.db", MagicMock()):
            deliver_generated_report(42, self.path, send_email_fn=lambda *a, **k: calls.append((a, k)))
        (args, kwargs), = calls
        self.assertEqual(args, ("buyer@example.com", "Your Career Report", args[2], self.path))
        self.assertEqual(kwargs, {"attachment_filename": "Jyotishasha-Career-Report.pdf"})


if __name__ == "__main__":
    unittest.main()
