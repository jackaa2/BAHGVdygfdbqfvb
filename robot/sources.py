"""Where clips come from: Twitch (official API) and Kick (public site API, best effort)."""
import datetime as dt
import os
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (gta6-clip-robot)"}


class Twitch:
    def __init__(self):
        self.cid = os.environ["TWITCH_CLIENT_ID"]
        r = requests.post("https://id.twitch.tv/oauth2/token", params={
            "client_id": self.cid, "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
            "grant_type": "client_credentials"}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Twitch sign-in failed ({r.status_code}): {r.text[:200]}")
        self.h = {"Client-Id": self.cid, "Authorization": f"Bearer {r.json()['access_token']}"}

    def _get(self, path, params, pages=1):
        out, cursor = [], None
        for _ in range(pages):
            p = list(params.items()) if isinstance(params, dict) else list(params)
            if cursor:
                p.append(("after", cursor))
            r = requests.get(f"https://api.twitch.tv/helix/{path}", headers=self.h, params=p, timeout=30)
            r.raise_for_status()
            j = r.json()
            out += j.get("data", [])
            cursor = (j.get("pagination") or {}).get("cursor")
            if not cursor:
                break
        return out

    def game_ids(self, names):
        return {g["id"]: g["name"] for g in self._get("games", [("name", n) for n in names])}

    def user_ids(self, logins):
        out = {}
        logins = [l for l in logins if l]
        for i in range(0, len(logins), 100):
            for u in self._get("users", [("login", l) for l in logins[i:i + 100]]):
                out[u["login"].lower()] = u["id"]
        return out

    def clips(self, since, game_id=None, broadcaster_id=None, first=50, pages=1):
        p = {"started_at": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "ended_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "first": first}
        if game_id:
            p["game_id"] = game_id
        if broadcaster_id:
            p["broadcaster_id"] = broadcaster_id
        return [{
            "platform": "Twitch",
            "url": c["url"],
            "streamer": c["broadcaster_name"],
            "title": c["title"],
            "views": c["view_count"],
            "seconds": round(c.get("duration") or 0),
            "language": c.get("language", ""),
            "game_id": c.get("game_id", ""),
            "created": c["created_at"],
        } for c in self._get("clips", p, pages=pages)]


def parse_time(value):
    """Kick sends times like 2026-11-17T20:07:57.624+00:00 or ...Z, with 0-6 decimals."""
    t = str(value or "").strip().replace("Z", "+00:00")
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?([+-]\d\d:?\d\d)?", t)
    if not m:
        return None
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    tz = m.group(3) or "+00:00"
    if ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    return dt.datetime.fromisoformat(f"{m.group(1)}.{frac}{tz}")


def kick_clips(slug, since):
    """Best effort: Kick has no official clips API. Returns [] (and the error text) if blocked."""
    try:
        r = requests.get(f"https://kick.com/api/v2/channels/{slug}/clips",
                         params={"sort": "view", "time": "day"}, headers=UA, timeout=30)
        if r.status_code != 200:
            return [], f"Kick {slug}: HTTP {r.status_code}"
        out = []
        for c in r.json().get("clips", []):
            created = parse_time(c.get("created_at"))
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            if created < since:
                continue
            out.append({
                "platform": "Kick",
                "url": f"https://kick.com/{slug}?clip={c.get('id')}",
                "streamer": (c.get("channel") or {}).get("username") or slug,
                "title": c.get("title", ""),
                "views": c.get("views") or c.get("view_count") or 0,
                "seconds": round(c.get("duration") or 0),
                "language": "en",
                "game_id": (c.get("category") or {}).get("name", ""),
                "created": created.isoformat(),
            })
        return out, None
    except Exception as e:  # never let Kick break the Twitch run
        return [], f"Kick {slug}: {e}"


def slug_from_link(link, host):
    m = re.search(host.replace(".", r"\.") + r"/([^/?#]+)", link or "")
    return m.group(1).lower() if m else None
