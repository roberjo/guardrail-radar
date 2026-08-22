"""pipeline.notify — see docs/technical-spec.md §15.2.

Notifies the maintainer that a review packet is ready by opening a GitHub
Issue via the REST API, using the workflow's own GITHUB_TOKEN — no external
notification service or long-lived credential required. Never sends
anything to subscribers — see docs/technical-spec.md §1, §20. Not one of
the modules enumerated in the original §4 sketch; added during
implementation so this step has a concrete home. See CHANGELOG.md.
"""

from __future__ import annotations

import argparse
import os

import requests

from pipeline.io_utils import iso_week_str, read_json

API_ROOT = "https://api.github.com"
REQUEST_TIMEOUT = 10
ISSUE_LABEL = "review-packet"


def _ranked_count(iso_week: str) -> int:
    path = os.path.join("data", "ranked", f"{iso_week}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} does not exist — pipeline.filter has not produced a ranked file for "
            f"{iso_week} yet; refusing to send a review-packet-ready notification"
        )
    return len(read_json(path))


def send_review_packet_ready(iso_week: str, item_count: int) -> None:
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]

    payload: dict[str, object] = {
        "title": f"Review packet ready for {iso_week}",
        "body": (
            f"{item_count} candidates ranked for {iso_week}.\n\n"
            f"Review packet: `digest/review/{iso_week}.md`\n\n"
            "Next: run the draft-digest skill, then verify-and-ship-digest."
        ),
        "labels": [ISSUE_LABEL],
    }
    assignee = os.environ.get("MAINTAINER_GITHUB_USERNAME")
    if assignee:
        payload["assignees"] = [assignee]

    resp = requests.post(
        f"{API_ROOT}/repos/{repo}/issues",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


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
