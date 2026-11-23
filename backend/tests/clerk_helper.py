import os, json, urllib.request, urllib.parse
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
SK = os.environ["CLERK_SECRET_KEY"]

def bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": "Bearer " + SK, "Content-Type": "application/json", "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))

def user_and_token(email):
    found = bapi(f"/users?email_address={urllib.parse.quote(email)}", method="GET")
    user = found[0] if found else bapi("/users", {"email_address": [email], "password": "Gokboss-Test-2026!", "skip_password_checks": True})
    session = bapi("/sessions", {"user_id": user["id"]})
    token = bapi(f"/sessions/{session['id']}/tokens", {"expires_in_seconds": 3600})["jwt"]
    return user, token

if __name__ == "__main__":
    import sys
    u, t = user_and_token(sys.argv[1])
    print(u["id"], t)
