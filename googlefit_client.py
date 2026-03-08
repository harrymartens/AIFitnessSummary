"""Google Fit REST API client for fetching weight data.

Eufy smart scales sync weight to Google Fit, which exposes the data via
the Fitness REST API.  This client handles the OAuth 2.0 flow (interactive
on first run, then cached) and pulls weight data points for a date range.

Required environment variables:
    GOOGLE_CLIENT_ID      – OAuth 2.0 client ID (from Google Cloud Console)
    GOOGLE_CLIENT_SECRET  – OAuth 2.0 client secret

On first run the user is prompted to open a browser URL and paste the
authorisation code.  The resulting refresh token is saved to
~/.googlefit_token.json so subsequent runs are non-interactive.
"""

import datetime
import json
import os
from pathlib import Path

import requests

TOKEN_PATH = Path(os.path.expanduser("~/.googlefit_token.json"))

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# Read-only access to body measurements (weight)
SCOPES = "https://www.googleapis.com/auth/fitness.body.read"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

# Google Fit data source for weight
WEIGHT_DATASOURCE = "derived:com.google.weight:com.google.android.gms:merge_weight"


class GoogleFitClient:
    """Fetch weight data from Google Fit."""

    def __init__(self, client_id: str = None, client_secret: str = None):
        self._client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self._client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        if not self._client_id or not self._client_secret:
            raise RuntimeError(
                "Google Fit integration requires GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET environment variables."
            )
        self._access_token: str | None = None
        self._authenticate()

    # ------------------------------------------------------------------
    # OAuth 2.0
    # ------------------------------------------------------------------

    def _authenticate(self):
        """Load cached token or run the interactive OAuth flow."""
        if TOKEN_PATH.exists():
            data = json.loads(TOKEN_PATH.read_text())
            refresh_token = data.get("refresh_token")
            if refresh_token:
                self._access_token = self._refresh_access_token(refresh_token)
                return

        # First-run interactive flow
        self._run_auth_flow()

    def _run_auth_flow(self):
        """Prompt the user to authorise via browser and exchange the code."""
        params = {
            "client_id": self._client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = OAUTH_AUTH_URL + "?" + "&".join(
            f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()
        )
        print("\n=== Google Fit Authorisation ===")
        print("Open this URL in your browser and grant access:\n")
        print(auth_url)
        code = input("\nPaste the authorisation code here: ").strip()

        resp = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        resp.raise_for_status()
        tokens = resp.json()

        self._access_token = tokens["access_token"]

        # Persist refresh token for future runs
        TOKEN_PATH.write_text(json.dumps({
            "refresh_token": tokens["refresh_token"],
        }))
        TOKEN_PATH.chmod(0o600)
        print("Google Fit authorisation successful. Token saved.\n")

    def _refresh_access_token(self, refresh_token: str) -> str:
        """Exchange a refresh token for a new access token."""
        resp = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_weight(self, start: datetime.date, end: datetime.date) -> dict:
        """Fetch weight data points from Google Fit for the given period.

        Returns a dict matching the shape of GarminClient.fetch_body_composition()
        so the data can be merged seamlessly:
            {
                "entries": [{"date": "2026-03-01", "weight_kg": 82.5}, ...],
                "latest_weight_kg": 82.3,
                "avg_weight_kg": 82.4,
                "source": "google_fit",
            }
        """
        # Google Fit uses nanosecond timestamps
        start_ns = int(datetime.datetime.combine(
            start, datetime.time.min,
        ).timestamp()) * 1_000_000_000
        end_ns = int(datetime.datetime.combine(
            end + datetime.timedelta(days=1), datetime.time.min,
        ).timestamp()) * 1_000_000_000

        url = (
            f"https://www.googleapis.com/fitness/v1/users/me/dataSources/"
            f"{WEIGHT_DATASOURCE}/datasets/{start_ns}-{end_ns}"
        )
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        entries = []
        for point in data.get("point", []):
            value = point.get("value", [{}])[0].get("fpVal")
            if value is None:
                continue
            # Convert start time (nanoseconds) to date string
            ts_ns = int(point.get("startTimeNanos", 0))
            dt = datetime.datetime.fromtimestamp(ts_ns / 1_000_000_000)
            entries.append({
                "date": dt.strftime("%Y-%m-%d"),
                "weight_kg": round(value, 1),
            })

        # Deduplicate: keep latest entry per day
        by_date: dict[str, dict] = {}
        for e in entries:
            by_date[e["date"]] = e
        entries = sorted(by_date.values(), key=lambda e: e["date"])

        weights = [e["weight_kg"] for e in entries]
        return {
            "entries": entries,
            "latest_weight_kg": entries[-1]["weight_kg"] if entries else None,
            "avg_weight_kg": round(sum(weights) / len(weights), 1) if weights else None,
            "source": "google_fit",
        }


def get_googlefit_client() -> "GoogleFitClient | None":
    """Return a GoogleFitClient if credentials are configured, else None."""
    if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
        try:
            return GoogleFitClient()
        except Exception as e:
            print(f"Warning: Google Fit initialisation failed: {e}")
            return None
    return None
