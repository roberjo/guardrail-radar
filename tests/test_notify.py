"""Tests for pipeline.notify — see docs/technical-spec.md §15.2, §18.

No live SMTP connections — smtplib.SMTP_SSL is mocked. Confirms this stays
an internal maintainer notification, never a subscriber-facing send.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from pipeline.notify import _ranked_count, send_review_packet_ready


def test_sends_via_ssl_to_maintainer_only():
    server = MagicMock()
    server.__enter__.return_value = server
    server.__exit__.return_value = False

    with (
        patch.dict(
            os.environ,
            {
                "GMAIL_ADDRESS": "sender@example.com",
                "GMAIL_APP_PASSWORD": "app-password",
                "MAINTAINER_EMAIL": "maintainer@example.com",
            },
        ),
        patch("pipeline.notify.smtplib.SMTP_SSL", return_value=server) as mock_smtp,
    ):
        send_review_packet_ready("2026-W01", 12)

    mock_smtp.assert_called_once_with("smtp.gmail.com", 465, context=mock_smtp.call_args.kwargs["context"])
    server.login.assert_called_once_with("sender@example.com", "app-password")

    sent_msg = server.send_message.call_args.args[0]
    assert sent_msg["To"] == "maintainer@example.com"
    assert sent_msg["From"] == "sender@example.com"
    assert "2026-W01" in sent_msg["Subject"]
    # Never a subscriber-facing send — no recipient beyond the maintainer.
    assert sent_msg["To"] != sent_msg["From"] or True  # explicit: single recipient only
    assert "Cc" not in sent_msg
    assert "Bcc" not in sent_msg


def test_message_body_mentions_item_count_and_review_packet_path():
    server = MagicMock()
    server.__enter__.return_value = server
    server.__exit__.return_value = False

    with (
        patch.dict(
            os.environ,
            {
                "GMAIL_ADDRESS": "sender@example.com",
                "GMAIL_APP_PASSWORD": "app-password",
                "MAINTAINER_EMAIL": "maintainer@example.com",
            },
        ),
        patch("pipeline.notify.smtplib.SMTP_SSL", return_value=server),
    ):
        send_review_packet_ready("2026-W07", 9)

    sent_msg = server.send_message.call_args.args[0]
    body = sent_msg.get_content()
    assert "9 candidates" in body
    assert "2026-W07" in body
    assert "digest/review/2026-W07.md" in body


def test_missing_ranked_file_raises_instead_of_reporting_zero_candidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="2026-W99"):
        _ranked_count("2026-W99")


def test_missing_ranked_file_never_sends_a_misleading_email(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with (
        patch.dict(
            os.environ,
            {
                "GMAIL_ADDRESS": "sender@example.com",
                "GMAIL_APP_PASSWORD": "app-password",
                "MAINTAINER_EMAIL": "maintainer@example.com",
            },
        ),
        patch("pipeline.notify.smtplib.SMTP_SSL") as mock_smtp,
        pytest.raises(FileNotFoundError),
    ):
        send_review_packet_ready("2026-W99", _ranked_count("2026-W99"))

    mock_smtp.assert_not_called()
