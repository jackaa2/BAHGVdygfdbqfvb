"""Tiny Google Drive + Sheets client using a personal-account refresh token (plain REST, no SDK)."""
import json
import os
import re
import time

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"


class Google:
    def __init__(self):
        self.client_id = os.environ["GOOGLE_CLIENT_ID"]
        self.client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
        self.refresh_token = os.environ["GOOGLE_REFRESH_TOKEN"]
        self._token, self._exp = None, 0

    # ---- auth -------------------------------------------------------------
    def token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        r = requests.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Google sign-in failed ({r.status_code}): {r.text[:300]}")
        d = r.json()
        self._token, self._exp = d["access_token"], time.time() + d.get("expires_in", 3600)
        return self._token

    def _h(self, extra=None):
        h = {"Authorization": f"Bearer {self.token()}"}
        h.update(extra or {})
        return h

    def _req(self, method, url, **kw):
        for attempt in range(4):
            r = requests.request(method, url, headers=self._h(kw.pop("headers", None)), timeout=120, **kw)
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {url.split('?')[0]} -> {r.status_code}: {r.text[:300]}")
            return r
        raise RuntimeError(f"{method} {url} kept failing")

    # ---- Sheets -----------------------------------------------------------
    def get_values(self, sheet_id, rng, formulas=False):
        params = {"valueRenderOption": "FORMULA"} if formulas else {}
        r = self._req("GET", f"{SHEETS}/{sheet_id}/values/{requests.utils.quote(rng)}", params=params)
        return r.json().get("values", [])

    def update_values(self, sheet_id, rng, values):
        self._req("PUT", f"{SHEETS}/{sheet_id}/values/{requests.utils.quote(rng)}",
                  params={"valueInputOption": "USER_ENTERED"}, json={"values": values})

    def batch_update(self, sheet_id, requests_):
        self._req("POST", f"{SHEETS}/{sheet_id}:batchUpdate", json={"requests": requests_})

    def sheet_gid(self, sheet_id, title):
        meta = self._req("GET", f"{SHEETS}/{sheet_id}", params={"fields": "sheets(properties(sheetId,title))"}).json()
        return next(x["properties"]["sheetId"] for x in meta["sheets"] if x["properties"]["title"] == title)

    def append_rows(self, sheet_id, rng, rows):
        self._req("POST", f"{SHEETS}/{sheet_id}/values/{requests.utils.quote(rng)}:append",
                  params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                  json={"values": rows})

    def ensure_rows(self, sheet_id, tab, min_rows):
        """Grow the tab (copying the formatting of the rows above) so writes never hit the grid edge."""
        meta = self._req("GET", f"{SHEETS}/{sheet_id}", params={
            "fields": "sheets(properties(sheetId,title,gridProperties(rowCount)))"}).json()
        sh = next(x["properties"] for x in meta["sheets"] if x["properties"]["title"] == tab)
        have = sh["gridProperties"]["rowCount"]
        if have >= min_rows:
            return
        add = max(min_rows - have, 500)
        self._req("POST", f"{SHEETS}/{sheet_id}:batchUpdate", json={"requests": [{"insertDimension": {
            "range": {"sheetId": sh["sheetId"], "dimension": "ROWS", "startIndex": have - 1, "endIndex": have - 1 + add},
            "inheritFromBefore": True}}]})

    # ---- Drive ------------------------------------------------------------
    def storage(self):
        q = self._req("GET", f"{DRIVE}/about", params={"fields": "storageQuota"}).json()["storageQuota"]
        return int(q.get("usage", 0)), int(q.get("limit", 0) or 0)

    def find_child(self, parent_id, name, folder=True):
        q = f"'{parent_id}' in parents and name = '{name}' and trashed = false"
        if folder:
            q += " and mimeType = 'application/vnd.google-apps.folder'"
        r = self._req("GET", f"{DRIVE}/files", params={"q": q, "fields": "files(id,name)", "pageSize": 1})
        files = r.json().get("files", [])
        return files[0]["id"] if files else None

    def ensure_folder(self, parent_id, name):
        fid = self.find_child(parent_id, name)
        if fid:
            return fid
        r = self._req("POST", f"{DRIVE}/files", json={
            "name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]})
        return r.json()["id"]

    def rename(self, file_id, name):
        r = self._req("GET", f"{DRIVE}/files/{file_id}", params={"fields": "name,trashed"})
        if r.json().get("name") != name:
            self._req("PATCH", f"{DRIVE}/files/{file_id}", json={"name": name})

    def trash_if_no_files(self, folder_id):
        """Trash a folder only if nothing but (empty) subfolders live under it. Returns True if trashed."""
        r = self._req("GET", f"{DRIVE}/files/{folder_id}", params={"fields": "trashed"})
        if r.json().get("trashed"):
            return False
        stack = [folder_id]
        while stack:
            fid = stack.pop()
            kids = self._req("GET", f"{DRIVE}/files", params={
                "q": f"'{fid}' in parents and trashed = false",
                "fields": "files(id,mimeType)", "pageSize": 200}).json().get("files", [])
            for k in kids:
                if k["mimeType"] != "application/vnd.google-apps.folder":
                    return False
                stack.append(k["id"])
        self._req("PATCH", f"{DRIVE}/files/{folder_id}", json={"trashed": True})
        return True

    def download(self, file_id, path):
        r = requests.get(f"{DRIVE}/files/{file_id}", params={"alt": "media"},
                         headers=self._h(), stream=True, timeout=600)
        if r.status_code != 200:
            raise RuntimeError(f"Download failed ({r.status_code}): {r.text[:200]}")
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        return path

    def touch(self, file_id):
        """Mark a file as 'just used' so the clean-up clock starts now."""
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self._req("PATCH", f"{DRIVE}/files/{file_id}", json={"modifiedTime": now})

    def trash(self, file_id):
        self._req("PATCH", f"{DRIVE}/files/{file_id}", json={"trashed": True})

    def delete(self, file_id):
        """Permanent delete (frees Drive space right away)."""
        self._req("DELETE", f"{DRIVE}/files/{file_id}")

    def list_trashed_videos(self):
        out, token = [], None
        while True:
            params = {"q": "trashed = true and mimeType = 'video/mp4' and 'me' in owners",
                      "fields": "nextPageToken,files(id,name)", "pageSize": 1000}
            if token:
                params["pageToken"] = token
            j = self._req("GET", f"{DRIVE}/files", params=params).json()
            out += j.get("files", [])
            token = j.get("nextPageToken")
            if not token:
                return out

    def list_children(self, parent_id):
        out, token = [], None
        while True:
            params = {"q": f"'{parent_id}' in parents and trashed = false",
                      "fields": "nextPageToken,files(id,name,mimeType,createdTime,modifiedTime)", "pageSize": 1000}
            if token:
                params["pageToken"] = token
            j = self._req("GET", f"{DRIVE}/files", params=params).json()
            out += j.get("files", [])
            token = j.get("nextPageToken")
            if not token:
                return out

    def upload(self, path, name, parent_id, mime="video/mp4"):
        """Resumable upload (works for big files)."""
        meta = {"name": name, "parents": [parent_id]}
        r = self._req("POST", f"{UPLOAD}?uploadType=resumable",
                      headers={"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": mime},
                      data=json.dumps(meta))
        session = r.headers["Location"]
        with open(path, "rb") as f:
            r2 = requests.put(session, data=f, headers={"Content-Type": mime}, timeout=600)
        if r2.status_code not in (200, 201):
            raise RuntimeError(f"Upload failed ({r2.status_code}): {r2.text[:300]}")
        return r2.json()["id"]


def folder_ids_from_panel(row2_formulas):
    """Read the folder links that the sheet add-on (ClipHub.gs) writes into Control Panel row 2."""
    ids = {}
    for cell in row2_formulas:
        m = re.search(r'folders/([-\w]+)"\s*,\s*"([^"]+)"', str(cell))
        if m:
            ids[m.group(2)] = m.group(1)
    return ids  # e.g. {"01 Raw": "...", "03 Approved": "...", "📂 All": "..."}
