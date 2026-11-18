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


def add_review_rows(g, sheet, rows):
    """Finished videos go to the Review tab; nothing posts until someone ticks POST IT there."""
    where = g.append_rows(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW}:L", rows)
    m = re.search(r"![A-Z]+(\d+):[A-Z]+(\d+)", where or "")
    if m:   # checkboxes only on the new rows
        gid = g.sheet_gid(sheet, C.REVIEW_TAB)
        g.batch_update(sheet, [{"setDataValidation": {
            "range": {"sheetId": gid, "startRowIndex": int(m.group(1)) - 1, "endRowIndex": int(m.group(2)),
                      "startColumnIndex": 6, "endColumnIndex": 9},
            "rule": {"condition": {"type": "BOOLEAN"}}}}])
