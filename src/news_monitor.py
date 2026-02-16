#!/usr/bin/env python3
"""Monitor investor relations pages and send Gmail alerts on changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

REQUEST_TIMEOUT_SECONDS = 20
MAX_LINKS_PER_COMPANY = 50
USER_AGENT = (
    "Mozilla/5.0 (compatible; portfolio-news-monitor/1.0; "
    "+https://github.com/your-username/portfolio-news-monitor)"
)


@dataclass
class Company:
    name: str
    ticker: str
    ir_url: str
    include_keywords: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="portfolio.yaml", help="Path to YAML watchlist config")
    parser.add_argument("--state", default="state.json", help="Path to local state file")
    parser.add_argument(
        "--notify-on-first-run",
        action="store_true",
        help="Send alert even when no previous state exists",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print alert instead of sending email")
    parser.add_argument("--verbose", action="store_true", help="Print additional debug logs")
    return parser.parse_args()


def load_companies(config_path: Path) -> list[Company]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    companies = []
    for entry in raw.get("companies", []):
        companies.append(
            Company(
                name=str(entry["name"]),
                ticker=str(entry["ticker"]).upper(),
                ir_url=str(entry["ir_url"]),
                include_keywords=[str(x).lower() for x in entry.get("include_keywords", [])],
            )
        )

    if not companies:
        raise ValueError("No companies configured. Add at least one company in portfolio.yaml")

    return companies


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: Path, state: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def fetch_links(company: Company, verbose: bool = False) -> list[dict[str, str]]:
    response = requests.get(
        company.ir_url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    links: list[dict[str, str]] = []

    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        href = anchor["href"].strip()
        if not href:
            continue

        absolute = urljoin(company.ir_url, href)
        lower_text = text.lower()
        lower_url = absolute.lower()

        if company.include_keywords:
            if not any(k in lower_text or k in lower_url for k in company.include_keywords):
                continue

        links.append({"title": text or absolute, "url": absolute})

    deduped = {(item["title"], item["url"]): item for item in links}
    normalized = list(deduped.values())
    normalized.sort(key=lambda x: (x["title"].lower(), x["url"].lower()))

    if verbose:
        print(f"[{company.ticker}] collected {len(normalized)} candidate links from {company.ir_url}")

    return normalized[:MAX_LINKS_PER_COMPANY]


def digest_links(links: list[dict[str, str]]) -> str:
    payload = json.dumps(links, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_change_report(previous: list[dict[str, str]], current: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    previous_set = {(item["title"], item["url"]) for item in previous}
    current_set = {(item["title"], item["url"]) for item in current}

    added = [
        {"title": title, "url": url}
        for title, url in sorted(current_set - previous_set, key=lambda x: (x[0].lower(), x[1].lower()))
    ]
    removed = [
        {"title": title, "url": url}
        for title, url in sorted(previous_set - current_set, key=lambda x: (x[0].lower(), x[1].lower()))
    ]
    return added, removed


def build_email(changes: list[dict[str, Any]]) -> EmailMessage:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"Portfolio news monitor detected updates at {now}.", ""]

    for change in changes:
        lines.append(f"{change['name']} ({change['ticker']})")
        lines.append(f"Investor page: {change['ir_url']}")

        if change["added"]:
            lines.append("  New links:")
            for item in change["added"]:
                lines.append(f"    + {item['title']} -> {item['url']}")

        if change["removed"]:
            lines.append("  Removed links:")
            for item in change["removed"]:
                lines.append(f"    - {item['title']} -> {item['url']}")

        lines.append("")

    body = "\n".join(lines).strip() + "\n"

    msg = EmailMessage()
    msg["Subject"] = f"Portfolio IR updates ({len(changes)} company{'ies' if len(changes) != 1 else ''})"
    msg["From"] = required_env("GMAIL_USERNAME")
    msg["To"] = os.getenv("NOTIFY_TO", msg["From"])
    msg.set_content(body)
    return msg


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def send_email(msg: EmailMessage) -> None:
    username = required_env("GMAIL_USERNAME")
    app_password = required_env("GMAIL_APP_PASSWORD")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(username, app_password)
        smtp.send_message(msg)


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    state_path = Path(args.state)

    companies = load_companies(config_path)
    prior_state = load_state(state_path)

    next_state: dict[str, Any] = {"companies": {}, "updated_at": datetime.now(timezone.utc).isoformat()}
    changes: list[dict[str, Any]] = []

    for company in companies:
        links = fetch_links(company, verbose=args.verbose)
        digest = digest_links(links)

        previous = prior_state.get("companies", {}).get(company.ticker)
        previous_digest = previous.get("digest") if previous else None
        previous_links = previous.get("links", []) if previous else []

        next_state["companies"][company.ticker] = {
            "name": company.name,
            "ir_url": company.ir_url,
            "digest": digest,
            "links": links,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        is_first_run = previous is None
        changed = previous_digest is not None and previous_digest != digest

        if changed or (is_first_run and args.notify_on_first_run):
            added, removed = build_change_report(previous_links, links)
            changes.append(
                {
                    "name": company.name,
                    "ticker": company.ticker,
                    "ir_url": company.ir_url,
                    "added": added,
                    "removed": removed,
                }
            )

    save_state(state_path, next_state)

    if not changes:
        print("No changes detected.")
        return 0

    msg = build_email(changes)
    if args.dry_run:
        print("Dry run mode: would send this email:\n")
        print(msg)
        return 0

    send_email(msg)
    print(f"Sent email for {len(changes)} company update(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.RequestException as exc:
        print(f"Network error while checking pages: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
