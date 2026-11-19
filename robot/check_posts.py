"""Diagnose: what Upload-Post says about each booked Short (status, YouTube privacy / errors)."""
import json
import os

import requests

import config as C
from google_api import Google

key, sheet = os.environ["UPLOAD_POST_KEY"], os.environ["SHEET_ID"]
H = {"Authorization": f"Apikey {key}"}
g = Google()
for p in (g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:O") or [])[:30]:
    p = p + [""] * (15 - len(p))
    rid = str(p[12]).strip()
    print(f"\n== ch{p[1]} {p[3]} live {p[7]} rid {rid}")
    for path in (f"/api/uploadposts/status?request_id={rid}", f"/api/uploadposts/status?job_id={rid}"):
        try:
            r = requests.get("https://api.upload-post.com" + path, headers=H, timeout=60)
            txt = r.text
            print(f"  {path.split('?')[1][:10]} -> {r.status_code}: {txt[:900]}")
            if r.ok:
                break
        except Exception as e:
            print(f"  error {e}")
