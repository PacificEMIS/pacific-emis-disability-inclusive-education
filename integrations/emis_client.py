import time
import requests
from django.conf import settings

class EmisClient:
    """Tiny helper for EMIS Core API (password-grant)."""

    def __init__(self):
        self.cfg = settings.EMIS
        self._token = None
        self._token_time = 0

    def _ensure_token(self):
        # refresh every 30 min
        if self._token and (time.time() - self._token_time) < 1800:
            return
        data = {
            "grant_type": "password",
            "username": self.cfg["USERNAME"],
            "password": self.cfg["PASSWORD"],
        }
        r = requests.post(self.cfg["LOGIN_URL"], data=data,
                          timeout=self.cfg["TIMEOUT_SECONDS"],
                          verify=self.cfg["VERIFY_SSL"])
        r.raise_for_status()
        payload = r.json()
        self._token = payload.get("access_token") or payload.get("accessToken")
        self._token_time = time.time()

    def _headers(self):
        self._ensure_token()
        return {"Authorization": f"Bearer {self._token}"}

    def get_core_lookups(self):
        r = requests.get(
            self.cfg["LOOKUPS_URL"],
            headers=self._headers(),
            timeout=self.cfg["TIMEOUT_SECONDS"],
            verify=self.cfg["VERIFY_SSL"],
        )
        r.raise_for_status()
        return r.json()
