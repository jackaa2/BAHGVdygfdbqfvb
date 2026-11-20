"""Take Shorts off YouTube for good (no repost). TAKEDOWN_IDS = comma-separated clip IDs.
Marks them on 📒 Posts so nothing re-queues them."""
import os

import requests

import config as C
from google_api import Google

key, sheet = os.environ["UPLOAD_POST_KEY"], os.environ["SHEET_ID"]
ids = [x.strip() for x in os.environ.get("TAKEDOWN_IDS", "").split(",") if x.strip()]
H = {"Authorization": f"Apikey {key}"}
g = Google()
posts = g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:M") or []
data = {}
for cid in ids:
    for i, p in enumerate(posts):
        p = p + [""] * 13
        if str(p[3]).strip() != cid:
            continue
        a, rid = int(p[1]), str(p[12]).strip()
        st = requests.get(f"https://api.upload-post.com/api/uploadposts/status?request_id={rid}", headers=H, timeout=60).json()
        res = (st.get("results") or [{}])[0]
        r = requests.post("https://api.upload-post.com/api/uploadposts/posts/unpublish", headers=H, timeout=60,
                          json={"platform": "youtube", "user": res.get("profile_username") or C.UPLOAD_POST_USERS[a],
                                "post_id": res.get("platform_post_id")})
        print(f"{cid} ch{a} {res.get('platform_post_id')}: take down -> {r.status_code} {r.text[:200]}")
        if r.ok:
            data[f"'{C.POSTS_TAB}'!I{i + 2}"] = [[f"🚫 taken down (nudity) - was {res.get('post_url') or ''}"]]
            data[f"'{C.POSTS_TAB}'!M{i + 2}"] = [["BLOCKED"]]
g.update_many(sheet, data)
