#!/usr/bin/env python3
"""Update the Homebrew cask version from the latest Mouser GitHub release."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

REPO = "TomBadash/Mouser"
API_LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"
API_RELEASE_BY_TAG = f"https://api.github.com/repos/{REPO}/releases/tags/{{tag}}"
ARM_ASSET = "Mouser-macOS.zip"
INTEL_ASSET = "Mouser-macOS-intel.zip"
CASK_PATH = Path("Casks/mouser.rb")


def request_json(url: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mouser-homebrew-cask-updater",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def load_release(path: str | None) -> dict:
    if path:
        with open(path, encoding="utf-8") as file:
            event = json.load(file)
        release = event.get("release") if isinstance(event, dict) else None
        if isinstance(release, dict) and release.get("tag_name"):
            return release
        if isinstance(event, dict) and event.get("tag_name"):
            if event.get("assets"):
                return event
            return request_json(API_RELEASE_BY_TAG.format(tag=event["tag_name"]))
    return request_json(API_LATEST_RELEASE)


def normalize_version(tag: str) -> str:
    return tag.removeprefix("v")


def find_asset(release: dict, name: str) -> str:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            url = asset.get("browser_download_url")
            if url:
                return url
    available = ", ".join(sorted(a.get("name", "<unnamed>") for a in release.get("assets", [])))
    raise SystemExit(f"Release {release.get('tag_name')} is missing {name}. Available assets: {available}")


def replace_once(pattern: str, replacement: str, text: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Expected exactly one match for pattern: {pattern}")
    return updated


def render_updated_cask(text: str, version: str) -> str:
    return replace_once(r'  version "[^"]+"', f'  version "{version}"', text)


def update_cask(version: str) -> bool:
    text = CASK_PATH.read_text(encoding="utf-8")
    updated = render_updated_cask(text, version)
    if updated == text:
        return False
    CASK_PATH.write_text(updated, encoding="utf-8")
    return True


def validate_cask_text() -> None:
    text = CASK_PATH.read_text(encoding="utf-8")
    required_patterns = [
        r'cask "mouser" do',
        r'arch arm: "", intel: "-intel"',
        r'version "[^"]+"',
        r'releases/download/v#\{version\}/Mouser-macOS#\{arch\}\.zip',
        r'sha256 :no_check',
        r'auto_updates true',
        r'depends_on macos: :monterey',
        r'app "Mouser\.app"',
    ]
    for pattern in required_patterns:
        if not re.search(pattern, text):
            raise SystemExit(f"Cask is missing expected pattern: {pattern}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event-path",
        default=os.environ.get("GITHUB_EVENT_PATH"),
        help="Path to a GitHub release event payload. Falls back to the latest release API.",
    )
    parser.add_argument("--check", action="store_true", help="Only report whether the cask is current.")
    args = parser.parse_args()

    validate_cask_text()
    try:
        release = load_release(args.event_path)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SystemExit(
                "GitHub API rate limit exceeded while fetching release metadata. "
                "Set GITHUB_TOKEN or pass --event-path with a saved release payload."
            ) from exc
        raise
    tag = release.get("tag_name")
    if not tag:
        raise SystemExit("Release payload does not include tag_name")

    find_asset(release, ARM_ASSET)
    find_asset(release, INTEL_ASSET)

    version = normalize_version(tag)
    current = CASK_PATH.read_text(encoding="utf-8")
    updated = render_updated_cask(current, version)
    changed = updated != current

    if args.check:
        if changed:
            print(f"{CASK_PATH} is not current for {tag}")
            return 1
        print(f"{CASK_PATH} is current for {tag}")
        return 0

    if changed:
        CASK_PATH.write_text(updated, encoding="utf-8")
        print(f"Updated {CASK_PATH} to {tag}")
    else:
        print(f"{CASK_PATH} is already current for {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
