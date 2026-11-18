"""Which hook goes on which YouTube channel, and adding finished videos to the Review tab."""
import re

import config as C


def channel_hooks(top, hooks):
    """Channel 1 gets the TOP TEXT you picked; channels 2-5 each get a different one of Claude's other hooks."""
    top = (top or "").strip()
    if not top or top == "(no top text)" or top.startswith("⚠️ Claude"):
        return {a: "" for a in range(1, 7)}
    rest = []
    for h in hooks:
        h = (h or "").strip()
        if h and not h.startswith("(") and not h.startswith("⚠️") and h != top and h not in rest:
            rest.append(h)
    out = {1: top}
    for a in range(2, 7):
        out[a] = rest[a - 2] if len(rest) >= a - 1 else top
    return out


def review_row(clip_id, a, hook, streamer, file_id):
    import datetime as dt
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    return [clip_id, a, f"Ch{a} · {C.CHANNELS.get(a, '')}", hook,
            f'=HYPERLINK("https://drive.google.com/file/d/{file_id}/view","▶ watch")', streamer,
            False, False, "", False, "👀 In the next batch reel", "", file_id, "", now.strftime("%Y-%m-%d %H:%M")]


def review_boxes(gid, r0, r1):
    """✅ + ☑ checkboxes and the 👎 'what's wrong' dropdown on rows r0..r1 (0-based, end exclusive)."""
    return [{"setDataValidation": {
                "range": {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": 6, "endColumnIndex": 8},
                "rule": {"condition": {"type": "BOOLEAN"}}}},
            {"setDataValidation": {
                "range": {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": 9, "endColumnIndex": 10},
                "rule": {"condition": {"type": "BOOLEAN"}}}},
            {"setDataValidation": {
                "range": {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": 8, "endColumnIndex": 9},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in
                                                                        C.BAD_REMAKE + C.BAD_SWAP]},
                         "showCustomUi": True, "strict": True}}}]


def add_review_rows(g, sheet, rows):
    """Finished videos go to the Review tab. A remade / swapped video replaces its own ⏳ row instead."""
    rows = [r for r in rows if not replace_review_row(g, sheet, r)]
    if not rows:
        return
    where = g.append_rows(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW}:O", rows)
    m = re.search(r"![A-Z]+(\d+):[A-Z]+(\d+)", where or "")
    if m:
        gid = g.sheet_gid(sheet, C.REVIEW_TAB)
        g.batch_update(sheet, review_boxes(gid, int(m.group(1)) - 1, int(m.group(2))))


def replace_review_row(g, sheet, row):
    """If this clip (or the clip it was swapped in for) has a ⏳ row waiting, put the new video there."""
    clip_id = str(row[0])
    vals = g.get_values(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW + 1}:O") or []
    for i, v in enumerate(vals):
        v = v + [""] * (15 - len(v))
        if str(v[10]).startswith("⏳") and (str(v[0]).strip() == clip_id or str(v[11]).strip() == f"swap:{clip_id}"):
            rn = C.REVIEW_HEADER_ROW + 1 + i
            new = list(row[:15])
            new[2] = v[2]                     # keep its "#n · ChX" label
            new[1] = v[1]                     # same channel
            new[14] = v[14]                   # same 'added' time
            new[10] = "👀 New version ready - watch it, then ✅ + ☑"
            new[11] = ""
            new[13] = v[13]                   # same batch
            g.update_values(sheet, f"'{C.REVIEW_TAB}'!A{rn}:O{rn}", [new])
            gid = g.sheet_gid(sheet, C.REVIEW_TAB)
            g.batch_update(sheet, review_boxes(gid, rn - 1, rn))
            print(f"Review: new version of {clip_id} placed in row {rn}")
            return True
    return False
