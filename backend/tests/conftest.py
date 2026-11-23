# Shared auth for all backend tests: every request to the app's /api gets the admin Clerk Bearer token
# (all /api routes are admin-guarded since iteration 14). Send header "X-No-Auth: 1" to skip it.
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
from clerk_helper import user_and_token  # noqa: E402

ADMIN_EMAIL = "gokboss-admin+clerk_test@example.com"
MEMBER_EMAIL = "gokboss-member+clerk_test@example.com"

_tokens = {}


def get_token(email):
    if email not in _tokens:
        user, token = user_and_token(email)
        _tokens[email] = (user["id"], token)
    return _tokens[email]


_orig_request = requests.Session.request


def _authed_request(self, method, url, **kwargs):
    headers = dict(kwargs.pop("headers", None) or {})
    if headers.pop("X-No-Auth", None):
        self.headers.pop("Authorization", None)
    elif "/api/" in str(url) and "Authorization" not in headers and "Authorization" not in self.headers:
        headers["Authorization"] = f"Bearer {get_token(ADMIN_EMAIL)[1]}"
    return _orig_request(self, method, url, headers=headers, **kwargs)


requests.Session.request = _authed_request


@pytest.fixture(scope="session")
def admin_auth():
    return get_token(ADMIN_EMAIL)


@pytest.fixture(scope="session")
def member_auth():
    return get_token(MEMBER_EMAIL)
