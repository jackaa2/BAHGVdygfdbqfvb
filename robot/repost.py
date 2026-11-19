"""Take Shorts down on YouTube (via Upload-Post) and queue them to post again.
REPOST_IDS = comma-separated clip IDs. The video goes back on the Review tab ticked ✅ + ☑, so the poster
books it into the next free slot on the same channel."""
import os
import time

import requests

import config as C
from google_api import Google

key, sheet = os.environ["UPLOAD_POST_KEY"], os.environ["SHEET_ID"]
ids = [x.strip() for x in os.environ.get("REPOST_IDS", "").split(",") if x.strip()]
H = {"Authorization": f"Apikey {key}"}
g = Google()
posts = g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:O") or []
drop_posts = []
for cid in ids:
    hit = [i for i, p in enumerate(posts) if len(p) > 3 and str(p[3]).strip() == cid]
    if not hit:
        print(f"{cid}: not in 📒 Posts"); continue
    i = hit[-1]
    p = posts[i] + [""] * 15
    a, rid = int(p[1]), str(p[12]).strip()
    st = requests.get(f"https://api.upload-post.com/api/uploadposts/status?request_id={rid}", headers=H, timeout=60).json()
    res = (st.get("results") or [{}])[0]
    pid, user = res.get("platform_post_id"), res.get("profile_username") or C.UPLOAD_POST_USERS[a]
    r = requests.post("https://api.upload-post.com/api/uploadposts/posts/unpublish", headers=H, timeout=60,
                      json={"platform": "youtube", "user": user, "post_id": pid})
    print(f"{cid} ch{a} {pid}: unpublish -> {r.status_code} {r.text[:300]}")
    gone = r.ok or "not found" in r.text.lower() or "404" in r.text
    if not gone:
        continue
    drop_posts.append(i)
    # back on the Review tab, ticked -> the poster books it again on the same channel
    rev = g.get_values(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW + 1}:A") or []
    rows = [C.REVIEW_HEADER_ROW + 1 + j for j, x in enumerate(rev) if x and str(x[0]).strip() == cid]
    if rows:
        rn = rows[0]
        g.update_values(sheet, f"'{C.REVIEW_TAB}'!G{rn}:L{rn}",
                        [[True, True, "", False, "🔁 Reposting - goes out in the next free slot", ""]])
        g.update_values(sheet, f"'{C.REVIEW_TAB}'!N{rn}", [[""]])
        print(f"{cid}: queued again (Review row {rn})")
    time.sleep(1)
if drop_posts:   # remove the old 📒 Posts lines so the no-duplicates guard lets it post again
    gid = g.sheet_gid(sheet, C.POSTS_TAB)
    g.batch_update(sheet, [{"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS",
                                                          "startIndex": 1 + i, "endIndex": 2 + i}}}
                           for i in sorted(drop_posts, reverse=True)])
