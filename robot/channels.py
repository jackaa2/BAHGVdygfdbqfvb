"""Which hook goes on which YouTube channel."""


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
