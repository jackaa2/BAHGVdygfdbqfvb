"""Swear-word bleeping: which words count, and how they look in captions."""
import re

# word stems (matched at the start of a word, so "fucking", "shitty", "bitches" are covered)
_STEMS = [
    "fuck", "fuk", "fck", "motherf", "shit", "bullshit", "bitch", "cunt", "pussy", "pussies",
    "asshole", "bastard", "slut", "whore", "twat", "wanker", "nigg", "retard", "jackass", "dumbass",
]
# whole words only (so "Dickens", "cocktail", "fagioli" are left alone)
_EXACT = ["dick", "dicks", "dickhead", "dickheads", "cock", "cocks", "cocksucker", "fag", "fags", "faggot", "faggots"]
_BAD = re.compile(r"^(?:(?:" + "|".join(_STEMS) + r")|(?:" + "|".join(_EXACT) + r")$)", re.I)
_LETTERS = re.compile(r"[A-Za-z']+")


def is_bad(word):
    core = "".join(_LETTERS.findall(word or ""))
    return bool(core) and bool(_BAD.match(core))


def censor(word):
    """'fucking!' -> 'f******!' (keeps the first letter and punctuation)."""
    if not is_bad(word):
        return word
    out, first = [], True
    for ch in word:
        if ch.isalpha():
            out.append(ch if first else "*")
            first = False
        else:
            out.append(ch)
    return "".join(out)


def bleep_windows(words, pad=0.04):
    """(start, end) times of every swear word, merged when they touch."""
    spans = sorted((max(0.0, w["start"] - pad), w["end"] + pad) for w in words if is_bad(w.get("word", "")))
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged
