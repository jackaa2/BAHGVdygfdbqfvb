"""Lists the Upload-Post profiles and which YouTube channel each one has connected (no uploads)."""
import json
import os
import requests

key = os.environ.get("UPLOAD_POST_KEY")
if not key:
    print("NO UPLOAD_POST_KEY SECRET FOUND"); raise SystemExit(1)
r = requests.get("https://api.upload-post.com/api/uploadposts/users", headers={"Authorization": f"Apikey {key}"}, timeout=60)
print("status", r.status_code)
try:
    j = r.json()
except ValueError:
    print(r.text[:500]); raise SystemExit(1)
profiles = j.get("profiles") or j.get("users") or j.get("data") or j
if isinstance(profiles, dict):
    profiles = list(profiles.values())
for p in profiles if isinstance(profiles, list) else []:
    if not isinstance(p, dict):
        continue
    name = p.get("username") or p.get("name") or p.get("profile_username")
    yt = (p.get("social_accounts") or {}).get("youtube") if isinstance(p.get("social_accounts"), dict) else None
    shown = (yt.get("display_name") or yt.get("username") or yt.get("handle")) if isinstance(yt, dict) else yt
    print(f"PROFILE {name!r}: youtube = {shown!r}")
print("RAW:", json.dumps(j)[:1500])
