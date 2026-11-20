"""Claude hook writer: for every new clip without hooks, Claude looks at 4 frames + reads what's said and
writes 5 hooks (Hook 1-5, one per YouTube channel). The 🎯 TOP TEXT cell gets a dropdown of those 3 (+ "(no top text)");
you pick one before you can approve."""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback

import requests

import config as C
from google_api import Google

API = "https://api.anthropic.com/v1/messages"
# Haiku: about 1/20th the cost of Sonnet (~$1-2 a month). Sonnet only steps in if Haiku errors out.
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]
MAX_PER_RUN = 25
AUTO_TAG = "🤖 AUTO"
LEARNED = ""
# $ per million tokens (input, output) - for the credit counter on the Analytics tab
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}
SPENT = {"usd": 0.0}
CREDIT_OUT = {"hit": False}     # Notes start with this on clips the robot picked by itself

PROMPT = """You screen clips for a group of faceless GTA 6 streamer-clips YouTube Shorts channels.
The best posts are funny, shocking or hype streamer moments, ideally about GTA 6, that hook in the first second.

Clip info:
- Streamer: {streamer} ({platform})
- Clip title: {title}
- Views so far: {views}
- Length: {seconds}s
- What's said (auto transcript with [start-end] times, may be messy): {transcript}

The images are 6 frames spread evenly through the clip, in order.

Reply with ONLY this JSON, nothing else:
{{"postable": true, "reason": "<max 12 words>", "moment": "<the funniest moment, max 15 words>",
  "cut": {{"start": <seconds>, "end": <seconds>}},
  "hooks": ["<best>", "<2>", "<3>", "<4>", "<5>"]}}

"postable": false if the clip is not worth posting: it is not GTA 6 (another game, or just talking with
no GTA 6 on screen or being discussed), nothing happens (loading screens, menus, dead air, AFK),
it isn't a streamer moment, it's mostly non-English, it's unwatchable, it's hateful, OR it shows real nudity or
sexual content: exposed breasts/nipples, bare butts, genitals, sex scenes, lap dances, strippers / strip clubs,
explicit sexual poses - in the game or on the streamer's camera. NOT nudity (these are fine): shirtless guys,
swimsuits at a beach, gym clothes, crude jokes with nothing shown. Nudity gets channels taken down, so when in
doubt about nudity or sexual content, it's FALSE.
Otherwise true. "reason": why, in a few words.

"cut" = how a pro Shorts editor would trim it (use the transcript times + loudest moments):
- start just before the setup of THE moment (~0.5 s before the first line that matters). Cut loading screens,
  menus, dead air and unrelated chatter at the beginning. Never start mid-sentence.
- end about 1-1.5 s after the reaction / laugh dies down. Never cut the payoff or the reaction. Never end
  mid-sentence. Cut anything after that (talking to chat, menus, silence).
- SHORT WINS: aim for 12-30 s (people must watch to the end and replay). Only go past 40 s if the whole
  thing is the joke. If the whole clip is already tight, use start 0 and end = its full length.

Hooks = the caption on top of the Short AND its YouTube title. They decide if someone stops scrolling.
First, find THE moment: the single funniest / most shocking thing that happens or is said (use the transcript
and frames). Every hook must be about that exact moment, with a concrete detail from it (what he hit, what he
said, who cooked who) - never a generic line that could fit any clip.

What makes a hook work:
- Tease, don't spoil: set up the moment so they HAVE to watch the payoff ("he had one job" > "he crashed").
- 3 to 8 words, max 45 characters. Front-load it: the first 2-3 words must grab.
- Sound like a real clip-page admin texting a friend, not a brand or an AI.
- Name the streamer the way fans say it (Kai, Speed, xQc, Lacy, Adin, Jason, ohnePixel) in at least 2 hooks.
- Lowercase is fine. Slang is fine (bro, nah, cooked, fumbled, pov:, lowkey, ts, ain't no way).

Write 5 DIFFERENT angles, one each (each goes on a different channel, so no near-copies), BEST ONE FIRST:
  1. roast: clown the streamer for what he did ("kai's driving should be illegal")
  2. pov / relatable: ("pov: you let adin drive")
  3. setup that teases the payoff ("speed had ONE job in gta 6")
  4. deadpan / ironic understatement ("speed is a responsible driver btw") - or his funniest exact line,
     but ONLY if that line is funny on its own with no context
  5. reaction / stakes ("the NPC cooked him 😭")
Brainstorm at least 10 in your head and keep only the 5 funniest. No two hooks may start with the same word,
use "pov:" and "nah" at most once each, and a hook must make sense to someone who has never seen this streamer.
Good energy (don't copy): "bro thought he was in fast and furious 💀" · "lacy fumbled the easiest heist ever" ·
  "nah this man is NOT okay" · "the NPC said no 😭" · "speed has 0 brain cells today"

Never: "pure chaos", "is everything", "absolutely", "unhinged", "wild ride", "you won't believe", "insane moment",
"wait for it", "chat, did you", "the way he...", "when you...", "Why is X ...?" questions, "X: Y" colons,
em dashes, hashtags, timestamps, quotes around the whole line, another game's name, spoiling the ending.
At most TWO hooks end with ONE emoji (💀 😭 😂 🫠 🤦); the rest no emoji.
Keep them clean: nothing hateful or sexual.{learned}"""


def redo_note(notes):
    """We 👎'd this clip's hook: steer away from it."""
    m = re.search(r"\| old: (.+)$", notes or "")
    return (f"\n\nWe rejected this hook for this clip, write something in a totally different direction: "
            f"\"{m.group(1).strip()}\"") if m else ""


def learned_feedback(g, sheet):
    """What you've 👎'd lately -> Claude avoids picking / writing that again."""
    rows = (g.get_values(sheet, f"'{C.FEEDBACK_TAB}'!A2:F") or [])[-25:]
    if not rows:
        return ""
    lines = []
    for f in rows:
        f = f + [""] * (6 - len(f))
        lines.append(f"- {f[5]}: {f[3]} clip, hook \"{f[4]}\"")
    return ("\n\nThe team REJECTED these recent videos (reason: streamer, hook). Be stricter about the same "
            "problems: skip clips like these (set postable false) and never write hooks like the rejected ones:\n"
            + "\n".join(lines))


def learned_style(g, sheet):
    """What's worked on OUR channels so far (📒 Posts: hook + views) -> fed back into the prompt so Claude
    leans toward the hook styles that get views. Needs at least 10 posts with views."""
    try:
        rows = g.get_values(sheet, f"'{C.POSTS_TAB}'!G2:J") or []
    except Exception:
        return ""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    now = _dt.datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    scored = []
    for r in rows:     # only Shorts that have been live 24 h+ (fresh ones always show 0 and would mislead)
        if len(r) >= 4 and str(r[0]).strip():
            try:
                live = _dt.datetime.strptime(str(r[1]).strip(), "%Y-%m-%d %H:%M")
                if now - live < _dt.timedelta(hours=24):
                    continue
                scored.append((float(str(r[3]).replace(",", "")), str(r[0]).strip()))
            except ValueError:
                pass
    scored.sort(reverse=True)
    best = [f"{h} ({v:.0f} views)" for v, h in scored[:8] if v > 0]
    worst = [f"{h} ({v:.0f})" for v, h in scored[-5:]]
    if not best:
        return ""
    return ("\n\nWHAT WORKS ON OUR CHANNELS (real view counts) - write more like the top ones, avoid the bottom ones' style:\n"
            "Top hooks: " + " | ".join(best) + "\nWorst hooks: " + " | ".join(worst))


def frames(path, tmp, n=4):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=nw=1:nk=1", path], capture_output=True, text=True).stdout or 0)
    out = []
    for i in range(n):
        t = max(dur * (i + 0.5) / n, 0)
        f = os.path.join(tmp, f"f{i}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                        "-vf", "scale=512:-2", "-q:v", "5", f], capture_output=True)
        if os.path.exists(f):
            out.append(base64.b64encode(open(f, "rb").read()).decode())
    return out


def transcript(path):
    try:
        from faster_whisper import WhisperModel
        import numpy as np
        global _wm
        if "_wm" not in globals():
            _wm = WhisperModel("base.en", device="cpu", compute_type="int8")
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f",
                              "f32le", "-"], capture_output=True)
        if pcm.returncode != 0:
            return "(no audio)"
        audio = np.frombuffer(pcm.stdout, dtype=np.float32)
        segs, _ = _wm.transcribe(audio, vad_filter=True, language="en")
        text = " ".join(f"[{s.start:.1f}-{s.end:.1f}s] {s.text.strip()}" for s in segs)[:2200] or "(no speech)"
        # loudest moments (yelling / laughing = usually the payoff), per half second
        if len(audio) > 8000:
            hop = 8000
            rms = [(float(np.sqrt(np.mean(audio[i:i + hop] ** 2))), i / 16000) for i in range(0, len(audio) - hop, hop)]
            top = sorted(rms, reverse=True)[:6]
            text += "\n- Loudest moments (reactions): " + ", ".join(f"{t:.1f}s" for _, t in sorted(top, key=lambda x: x[1]))
        return text
    except Exception as e:
        return f"(transcript unavailable: {e})"


def smart_cut(cut, secs):
    """Claude's trim -> 'start-end' for the ✂️ CUT column, only if it's sane and actually removes something."""
    try:
        a, b = float(cut["start"]), float(cut["end"])
        dur = float(str(secs).replace(",", "") or 0)
    except (TypeError, ValueError, KeyError):
        return ""
    if dur <= 0:
        return ""
    a, b = max(0.0, a), min(dur, b)
    if b - a < 6 or (a + (dur - b)) < 1.5:      # too short to be right, or barely trims anything
        return ""
    return f"{a:.1f}-{b:.1f}"


NUDITY_PROMPT = """These are frames spread across a YouTube Short (GTA 6 streamer clip). Look at EVERY frame,
including small details and the streamer's own camera. Is there ANY nudity or sexual content: exposed breasts or
nipples, bare butts, genitals, sex acts, strippers / strip club / lap dance, sexual poses? Partial or brief counts.
Shirtless men and normal swimwear are fine. Answer ONLY JSON: {"nudity": true/false, "why": "<max 10 words>"}"""


def nudity_check(key, path, n=12):
    """Second, stricter look at the FINISHED video right before it uploads: many frames, nudity only.
    Returns a reason string if it should be blocked, '' if clean. Fails safe (blocks) if it can't check."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        imgs = frames(path, tmp, n=n)
    if not imgs:
        return "couldn't check the video"
    try:
        res = ask_claude(key, NUDITY_PROMPT, imgs)
    except Exception as e:
        return f"couldn't check ({str(e)[:40]})"
    if res.get("nudity") is True or str(res.get("nudity")).lower() == "true":
        return str(res.get("why") or "nudity")[:60]
    if "nudity" not in res:
        return "unclear check"
    return ""


def ask_claude(key, prompt, imgs):
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
               for b in imgs] + [{"type": "text", "text": prompt}]
    last = None
    for model in MODELS:
        r = requests.post(API, timeout=120, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 2000, "messages": [{"role": "user", "content": content}]})
        if r.status_code == 200:
            body = r.json()
            u = body.get("usage") or {}
            tin = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            pin, pout = PRICES.get(model, PRICES["claude-sonnet-5-5"])
            if model.startswith("claude-haiku") and tin > 100_000:
                pin, pout = 0.50, 2.50
            SPENT["usd"] += tin * pin / 1e6 + int(u.get("output_tokens") or 0) * pout / 1e6
            text = "".join(b.get("text", "") for b in body.get("content", []))
            stop = body.get("stop_reason")
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            # no JSON: pull hook-looking lines out of the text instead
            lines = [re.sub(r'^[\s\-\*\d\.\)"]+|"$', "", l).strip() for l in text.splitlines()]
            lines = [l for l in lines if 6 <= len(l) <= 60 and not l.lower().startswith(("here", "hook", "{", "}"))]
            if len(lines) >= 2:
                return {"hooks": lines[:3]}
            last = f"{model}: no hooks in reply (stop={stop}): {text[:200]!r}"
            continue
        last = f"{model}: {r.status_code} {r.text[:200]}"
        if "credit balance" in r.text.lower():
            CREDIT_OUT["hit"] = True
            break
        if r.status_code in (401, 403):
            break  # bad key: no point trying another model
    raise RuntimeError(last)


def track_credit(g, sheet, screened=0):
    """Logs this run's Claude cost on the 💸 Expenses tab (Analytics adds it all up).
    Analytics J14 = your balance when you last topped up; when it changes the robot notes the date (Q4:Q5)
    so 'credit left' only counts what was spent since."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M")
    if SPENT["usd"] > 0:
        g.append_rows(sheet, f"'{C.EXPENSE_TAB}'!A:D",
                      [[now, "Claude AI", round(SPENT["usd"], 4), f"{screened} clip(s) screened"]])
    vals = g.get_values(sheet, f"'{C.ANALYTICS_TAB}'!J14") or [[""]]
    topped = str(vals[0][0] if vals and vals[0] else "").strip()
    seen = g.get_values(sheet, f"'{C.ANALYTICS_TAB}'!Q4") or [[""]]
    seen = str(seen[0][0] if seen and seen[0] else "").strip()
    if topped and topped != seen:     # new balance typed in: count from now
        g.update_values(sheet, f"'{C.ANALYTICS_TAB}'!Q4:Q5", [[topped], [now]])
    if CREDIT_OUT["hit"]:
        g.update_values(sheet, f"'{C.PANEL_TAB}'!G1",
                        [["🤖 Robot · ❌ FAILED: Claude credit ran out - top up at console.anthropic.com"]])
    print(f"Claude cost this run ${SPENT['usd']:.4f}")


def col_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("No ANTHROPIC_API_KEY, screener skipped"); return
    sheet = os.environ["SHEET_ID"]
    g = Google()
    global LEARNED
    LEARNED = learned_style(g, sheet)
    try:
        LEARNED += learned_feedback(g, sheet)
    except Exception as e:
        print(f"feedback: {e}")
    if LEARNED:
        print("Using what worked so far:", LEARNED[:200])
    head = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]
    need = {"id": "Clip ID", "streamer": "Streamer", "title": "Clip Title", "top": "🎯 TOP TEXT",
            "decision": "✅ YOUR DECISION", "notes": "Notes",
            "views": "Views",
            "secs": "Length (s)", "platform": "Platform", "raw": "Raw File",
            "h1": "Hook 1", "h2": "Hook 2", "h3": "Hook 3", "h4": "Hook 4", "h5": "Hook 5",
            "status": "Status", "send": "🚀 SEND"}
    col = {k: head.index(v) for k, v in need.items() if v in head}
    if "✂️ CUT" in head:
        col["cut"] = head.index("✂️ CUT")
    missing = [need[k] for k in need if k not in col]
    if missing:
        raise RuntimeError(f"missing columns: {missing}")
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:{col_letter(len(head) - 1)}", formulas=True)

    def cell(r, k):
        return str(r[col[k]]).strip() if len(r) > col[k] else ""

    # hooks are only written for clips you APPROVED (no tokens spent on clips you don't want)
    todo = [r for r in rows if cell(r, "id") and cell(r, "decision") == "Approve"
            and not (cell(r, "h1") or cell(r, "h2") or cell(r, "h3")) and not cell(r, "top")][:MAX_PER_RUN]
    test = [x.strip() for x in (os.environ.get("HOOK_TEST") or "").split(",") if x.strip()]
    if test:   # try-out mode: write hooks for these clips and only PRINT them (changes nothing)
        todo = [r for r in rows if cell(r, "id") in test]
    gid = g.sheet_gid(sheet, C.PANEL_TAB)
    print(f"{len(todo)} clip(s) to screen")
    done = sent = 0
    with tempfile.TemporaryDirectory() as tmp:
        for r in todo:
            clip_id = cell(r, "id")
            try:
                m = re.search(r"(?:/d/|id=)([-\w]{20,})", cell(r, "raw"))
                if not m:
                    continue
                path = g.download(m.group(1), os.path.join(tmp, "clip.mp4"))
                imgs = frames(path, tmp, n=6)
                prompt = PROMPT.format(streamer=cell(r, "streamer"), platform=cell(r, "platform"),
                                       title=cell(r, "title").lstrip("'"), views=cell(r, "views"),
                                       seconds=cell(r, "secs"), transcript=transcript(path), learned=LEARNED)
                try:
                    res = ask_claude(key, prompt, imgs)
                except RuntimeError as e:
                    # usually the transcript (slurs / heavy profanity) makes the model stop early:
                    # try again with only the frames + title
                    print(f"{clip_id}: first try failed ({e}); retrying without the transcript")
                    prompt = PROMPT.format(streamer=cell(r, "streamer"), platform=cell(r, "platform"),
                                           title=cell(r, "title").lstrip("'"), views=cell(r, "views"),
                                           seconds=cell(r, "secs"),
                                           transcript="(left out - go by the frames and title; keep hooks clean)",
                                           learned=LEARNED)
                    res = ask_claude(key, prompt, imgs)
                hooks = [re.sub(r'["#]', "", str(h)).strip()[:60] for h in (res.get("hooks") or [])][:5]
                hooks = [h for h in hooks if h]
                auto = cell(r, "notes").startswith(AUTO_TAG)
                postable = res.get("postable", True) is not False
                if not hooks and postable:
                    raise RuntimeError("Claude returned no hooks")
                if test:
                    print(f"TEST {clip_id} ({cell(r, 'streamer')}, {cell(r, 'secs')}s) cut: {res.get('cut')} -> {smart_cut(res.get('cut'), cell(r, 'secs')) or 'keep all'} | moment: {res.get('moment')}")
                    for h in hooks:
                        print(f"TEST    {h}")
                    continue
                # find the row again right before writing (rows can move)
                ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")
                hit = [C.HEADER_ROWS + 1 + i for i, x in enumerate(ids) if x and str(x[0]).strip() == clip_id]
                if not hit:
                    continue
                rn = hit[0]
                put = lambda k, v: g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col[k])}{rn}", [[v]])
                if auto and not postable:
                    # Claude passed on this auto-pick: reject it (the next grab picks another one)
                    put("decision", "Reject")
                    put("notes", f"{AUTO_TAG} skipped: {str(res.get('reason') or '')[:80]}")
                    print(f"{clip_id}: auto-pick skipped ({res.get('reason')})")
                    done += 1
                    continue
                for i, h in enumerate(hooks + [""] * (5 - len(hooks))):
                    put(f"h{i + 1}", h)
                # dropdown in 🎯 TOP TEXT with these hooks (typing your own text is allowed too)
                g.batch_update(sheet, [{"setDataValidation": {
                    "range": {"sheetId": gid, "startRowIndex": rn - 1, "endRowIndex": rn,
                              "startColumnIndex": col["top"], "endColumnIndex": col["top"] + 1},
                    "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                        {"userEnteredValue": h} for h in hooks + ["(no top text)"]]},
                        "showCustomUi": True, "strict": False}}}])
                cut = smart_cut(res.get("cut"), cell(r, "secs"))
                if cut and "cut" in col and not cell(r, "cut"):
                    put("cut", cut)
                    print(f"{clip_id}: ✂️ trimmed to {cut}")
                if auto:  # no human step: channel 1 gets hook 1, the others get hooks 2-5; send to editing
                    put("top", hooks[0])
                    put("send", True)
                    put("status", "Pending")
                    sent += 1
                print(f"{clip_id}: {'AUTO ' if auto else ''}{hooks}")
                done += 1
                os.remove(path)
            except Exception as e:
                traceback.print_exc()
                print(f"{clip_id}: hooks failed: {e}")
                try:  # tell the user in the sheet so they can type their own
                    ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")
                    hit = [C.HEADER_ROWS + 1 + i for i, x in enumerate(ids) if x and str(x[0]).strip() == clip_id]
                    if hit and cell(r, "notes").startswith(AUTO_TAG):
                        # robot's own pick: drop it, the next grab picks a replacement
                        g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col['decision'])}{hit[0]}", [["Reject"]])
                        g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col['notes'])}{hit[0]}",
                                        [[f"{AUTO_TAG} skipped: Claude couldn't write hooks"]])
                    elif hit:
                        g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col['top'])}{hit[0]}",
                                        [[C.NO_HOOK_TEXT]])
                except Exception:
                    pass
    print(f"Wrote hooks for {done} clip(s)")
    try:
        track_credit(g, sheet, done)
    except Exception as e:
        print(f"credit counter: {e}")
    if sent and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"auto_sent={sent}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
