# notifications/notification_fcm.py

import json
import requests
import os
import time
from google.oauth2 import service_account
from google.auth.transport.requests import Request

"""
FCM HTTP v1 NOTIFICATION SENDER
--------------------------------
- Uses Service Account JSON from environment variable
- Generates OAuth2 access token on runtime
- Calls v1 API endpoint:
  https://fcm.googleapis.com/v1/projects/<project-id>/messages:send
"""

# Load service account JSON
SA_JSON = os.getenv("FCM_SERVICE_ACCOUNT_JSON")

if not SA_JSON:
    raise Exception("❌ FCM_SERVICE_ACCOUNT_JSON missing in environment!")

try:
    service_account_info = json.loads(SA_JSON)
    PROJECT_ID = service_account_info["project_id"]
except Exception as e:
    raise Exception(f"❌ Invalid FCM_SERVICE_ACCOUNT_JSON: {str(e)}")


# ---------------------------------------------------------
# Create credentials object for v1 FCM
# ---------------------------------------------------------
def _get_access_token():
    """Generate short-lived OAuth2 token for FCM v1."""
    try:
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        creds.refresh(Request())
        return creds.token
    except Exception as e:
        print("❌ Failed generating FCM access token:", e)
        return None


# ---------------------------------------------------------
# MAIN SEND FUNCTION (used everywhere in backend)
# ---------------------------------------------------------
def send_fcm(token: str, title: str, body: str, data: dict = None):
    """
    Sends push notification using FCM HTTP v1 API.
    Returns True / False
    """

    access_token = _get_access_token()
    if not access_token:
        return False

    url = f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"

    payload = {
        "message": {
            "token": token,
            "notification": {
                "title": title,
                "body": body
            },
            "data": data or {}
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; UTF-8",
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))

        if response.status_code == 200:
            return True

        print(f"⚠️ FCM v1 error ({response.status_code}): {response.text}")
        return False

    except Exception as e:
        print("❌ FCM v1 Exception:", str(e))
        return False
