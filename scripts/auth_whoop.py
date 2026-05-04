"""
One-command WHOOP re-authorization.

Usage:
    python scripts/auth_whoop.py

Opens your browser for WHOOP OAuth approval. After approving, paste the
URL you were redirected to, and the script handles the rest.
"""

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

CLIENT_ID = os.environ.get("WHOOP_CLIENT_ID", "55219562-12e8-42a9-8307-342e4b60c3e8")
CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "154213e7bf47a4e7ae75dc998ad869b52792a76b66cf493c1852cf923c25c8a0")
REDIRECT_URI = "https://example.com"
SCOPES = "offline read:recovery read:sleep read:cycles read:workout read:profile read:body_measurement"


def exchange_code(code: str) -> dict:
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.prod.whoop.com/oauth/oauth2/token",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    auth_url = (
        "https://api.prod.whoop.com/oauth/oauth2/auth?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": "reauth_daily_summary",
        })
    )

    print("Opening browser for WHOOP authorization...")
    webbrowser.open(auth_url)

    print("\nAfter approving, you'll be redirected to example.com.")
    print("Paste the full URL from your browser's address bar:\n")
    redirected_url = input("> ").strip()

    parsed = urllib.parse.urlparse(redirected_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = params.get("code", [None])[0]

    if not code:
        print("ERROR: No authorization code found in that URL.")
        sys.exit(1)

    print("Exchanging code for tokens...")
    tokens = exchange_code(code)
    refresh_token = tokens["refresh_token"]

    print(f"\nNew refresh token:\n{refresh_token}\n")

    result = subprocess.run(
        ["gh", "secret", "set", "WHOOP_REFRESH_TOKEN", "--body", refresh_token],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("GitHub secret updated successfully.")
    else:
        print(f"Failed to update secret via gh CLI: {result.stderr}")
        print("Set it manually:")
        print(f'  gh secret set WHOOP_REFRESH_TOKEN --body "{refresh_token}"')


if __name__ == "__main__":
    main()
