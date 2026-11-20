"""🔞 Re-check every Short already uploaded (live or scheduled) with the strict nudity check.
Report only: flagged ones are marked on 📒 Posts (column N) and printed. Nothing is taken down here."""
import os
import tempfile

import config as C
from google_api import Google
from screen import nudity_check

ak, sheet = os.environ["ANTHROPIC_API_KEY"], os.environ["SHEET_ID"]
g = Google()
posts = g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:P") or []
data, hits = {}, 0
for i, p in enumerate(posts):
    p = p + [""] * (16 - len(p))
    a, cid, link, fid = int(p[1] or 0), str(p[3]).strip(), str(p[8]), str(p[15]).strip()
    if "youtube.com" not in link or not a:
        continue
    if not fid:
        fid = g.find_child(C.ACCOUNT_FOLDERS[a], f"{cid}_A{a}.mp4", folder=False) or ""
    if not fid:
        print(f"{cid}: video file not found, can't re-check")
        continue
    with tempfile.TemporaryDirectory() as tmp:
        path = g.download(fid, os.path.join(tmp, f"{cid}.mp4"))
        why = nudity_check(ak, path, n=20)
    if not why or why.startswith(("couldn't", "unclear")):
        print(f"{cid} ch{a}: clean" + (f" ({why})" if why else ""))
        continue
    hits += 1
    print(f"🚫 FLAGGED {cid} ch{a}: {why} | {link[-43:]}")
    data[f"'{C.POSTS_TAB}'!N{i + 2}"] = [[f"🔞 flagged: {why}"]]
g.update_many(sheet, data)
print(f"Audit done: {hits} flagged")
