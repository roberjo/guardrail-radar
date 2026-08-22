"""pipeline.notify — see docs/technical-spec.md §15.2.

Sends the internal "review packet ready" email to the maintainer via Gmail
SMTP. Never sends to subscribers — see docs/technical-spec.md §1, §20. Not
one of the modules enumerated in the original §4 sketch; added during
implementation so the repurposed SMTP step has a concrete home. See
CHANGELOG.md.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
from email.message import EmailMessage

from pipeline.io_utils import iso_week_str, read_json


def _ranked_count(iso_week: str) -> int:
    path = os.path.join("data", "ranked", f"{iso_week}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} does not exist — pipeline.filter has not produced a ranked file for "
            f"{iso_week} yet; refusing to send a review-packet-ready notification"
        )
    return len(read_json(path))


def send_review_packet_ready(iso_week: str, item_count: int) -> None:
    address = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["MAINTAINER_EMAIL"]

    msg = EmailMessage()
    msg["Subject"] = f"Guardrail Radar: review packet ready for {iso_week}"
    msg["From"] = address
    msg["To"] = recipient
    msg.set_content(
        f"{item_count} candidates ranked for {iso_week}.\n\n"
        f"Review packet: digest/review/{iso_week}.md\n\n"
        "Next: run the draft-digest skill, then verify-and-ship-digest."
    )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(address, app_password)
        server.send_message(msg)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["review-packet-ready"], required=True)
    parser.add_argument("--iso-week", default=None)
    args = parser.parse_args()

    iso_week = args.iso_week or iso_week_str()

    if args.kind == "review-packet-ready":
        send_review_packet_ready(iso_week, _ranked_count(iso_week))
        print(f"[notify] sent review-packet-ready for {iso_week}")


if __name__ == "__main__":
    main()
