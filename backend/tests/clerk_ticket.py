# Prints a Clerk sign-in ticket for UI tests: python3 tests/clerk_ticket.py <email>
import sys, urllib.parse
from clerk_helper import bapi
u = bapi(f"/users?email_address={urllib.parse.quote(sys.argv[1])}", method="GET")[0]
print(bapi("/sign_in_tokens", {"user_id": u["id"], "expires_in_seconds": 3600})["token"])
