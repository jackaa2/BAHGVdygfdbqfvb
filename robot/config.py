"""Settings you can change without touching the rest of the code."""

# Google Sheet (set as a GitHub secret named SHEET_ID; this is only the fallback)
SHEET_ID_FALLBACK = ""

PANEL_TAB = "Control Panel"
STREAMERS_TAB = "Streamers + Links"
HEADER_ROWS = 3

# What counts as worth grabbing
GAME_NAMES = ["Grand Theft Auto VI"]   # Twitch category to pull top clips from
LOOKBACK_HOURS = 12                     # only clips made in the last N hours
MIN_VIEWS_CATEGORY = 300               # GTA 6 category clips (any streamer)
MIN_VIEWS_TRACKED = 25                # clips from streamers on our list
MIN_SECONDS, MAX_SECONDS = 6, 180    # grab clips up to 3 min
PREFERRED_SECONDS = 180        # no length preference: any clip up to 3 min ranks on views alone
LANGUAGES = {"en"}                      # skip non-English clips
MAX_NEW_CLIPS_PER_RUN = 60              # every 30 min -> ~75 clips an hour

# Drive folders (fixed IDs, so renaming folders never breaks anything).
# Names are applied automatically on every run.
ROOT_FOLDER = ("1lZN5Lh0Vp0Y6gFd9tZ-sDyqCyQneaUWc", "GTA6 Clip Hub - VIDEOS")
FOLDERS = {
    "brand":    ("1arUg_7htt2yuWDGNckSwkbjhB7Exc9LF", "0 - Brand Kit (logos + watermarks)"),
    "new":      ("1jlABYCermfUiZy3h3J-kfgoXI_0ONAVB", "1 - New Clips (robot drops here)"),
    "hold":     ("1z-PtRgIk5FZ9Wtn_kjSaM5NjmX6sz9W4", "2 - On Hold"),
    "approved": ("1U8tdARMO6ecABiM7AAr4B4x0GH5XNhId", "3 - Approved (waiting for edits)"),
    "ready":    ("1tbW_vEMgs6rx7UlxW_miH8HeakZ4unfC", "4 - Ready to Post (YouTube)"),
    "posted":   ("1YhAGL4AzGWA9rQKCk-5FOacOTmGMKMwA", "5 - Posted"),
    "rejected": ("1JScjCRfpeeUjXpM8jJuX47Hd_AXSCs2G", "6 - Rejected"),
}
# Empty duplicate made by running setup twice; trashed only if it holds no files.
DUPLICATE_ROOTS = ["1WWHteRmD_-S30F2qby53gq9qeRN8riL5"]

CATEGORY_PAGES = 5                     # read up to 500 category clips (big non-English streams crowd the first 100)

ACCOUNT_FOLDERS = {
    1: "1h7qwmKXlMQE0n0Cgh1faCnSHphWWZjMc",
    2: "1tnJQG3-Wujd9ABEKyZNq3rmmJMojvJZS",
    3: "1ZegHScdAhG-jlwsLtF3lfugtSbsw_XkE",
    4: "1PSBXU5RPMsayYdvkyRFT0wqOYFZQveif",
    5: "15Ug4UVXgwH1-Ox3UjKduIoD6Vx8KxQwe",
    6: "1luy_PwOSYeAVpoGURHyBormFrMb8CK5S",
}
STYLES_TAB = "Account Styles"
EDIT_MAX_PER_RUN = 25         # approved clips turned into 6 versions per run
WHISPER_MODEL = "small.en"    # speech-to-text for captions (free, runs on GitHub)

SHOW_HOOK = True              # static caption above the clip (Hook column, or the clip's title if empty)
SHOW_WATERMARK = False        # turn on once the 6 channel watermarks are in

CLEANUP_ENABLED = True        # Joe approved (Nov 17): delete old robot files for good
# Drive clean-up (robot-made files only, inside the clip folders). Free Drive is 15 GB and each
# approved clip makes ~6 x 20 MB, so old files are deleted for good after these many days.
CLEANUP_DAYS = {
    "rejected": 1,      # videos in "6 - Rejected" (the 🗑 button removes them right away)
    "new": 3,           # never-decided clips in "1 - New Clips"
    "hold": 7,          # "2 - On Hold" (no longer used; leftovers cleared after a week)
    "approved": 1,      # raw clips in "3 - Approved": kept 1 day after their 6 versions were made
    "ready": 7,         # finished versions in "4 - Ready to Post/Account N"
}
DELETE_RAW_AFTER_EDIT = False # raw is kept 1 day after editing (see CLEANUP_DAYS['approved'])
STREAMER_ONLY_CAPTIONS = True  # skip game dialogue / donation voices / background chatter
MAX_CLIP_SECONDS = 180.0      # hard cap (Shorts allow 3 min); longer clips are cut to the 3 min with the most talking
TRACKED_BOOST = 1.5           # clips from streamers on the Streamers + Links tab rank higher

# Channels (one per account folder). Account 6 is not used.
CHANNELS = {
    1: "Streamers in Leonida | GTA6",
    2: "Vice City Streamers | GTA 6",
    3: "GTA 6 Streamer Highlights",
    4: "GTA 6 TV",
    5: "Streamers In GTA 6",
}

# TikTok accounts: own "Ready to Post (TikTok)" folder, one sub-folder each (watermarks to come: assets/watermarks/T1..T5.png)
TIKTOK_ROOT_NAME = "4 - Ready to Post (TikTok)"
TIKTOK_CHANNELS = {   # same order as the TikTok account list
    1: "gta6.streamer.highlights",
    2: "gta6streamerworld",
    3: "gta6vcreels",
    4: "gta6streamertv",
    5: "gta6streamerhq",
}
TIKTOK_FOLDERS = {
    1: "1Whb5OPVRDuYFWRXH-aRj9joVHGpSVuRE",   # gta6.streamer.highlights  (girl with controller)
    2: "1BYqsUlSPN50V8qRsB2rq_6YF8GeajYxb",   # gta6streamerworld         (GTA 6 Streamer World)
    3: "1MUvekoULzP_R8S_jQ5G0ccKEkjLHl-Oz",   # gta6vcreels               (GTA VI TV)
    4: "15_a-aTe5PL124r1socoIrflVCEOLEqs4",   # gta6streamertv            (Leonida Reels phone)
    5: "16kKYqtXSA5wyqIgqVzDJiMvNlSeIbHjH",   # gta6streamerhq            (GTA 6 Streamer HQ)
}
# TikTok version N = same video as YouTube version N, only the watermark differs (assets/watermarks/T{N}.png).
# A TikTok account without a watermark file yet is skipped.

# written in 🎯 TOP TEXT when Claude can't come up with hooks (never used as the video's top text)
NO_HOOK_TEXT = "⚠️ Claude couldn't write a hook - type your own here"


# Only grab clips from these tiers on the Streamers + Links tab (T1, T2). Set to None to allow everyone again.
ONLY_TIERS = {1, 2, 3}
# ...except a GTA 6 clip from ANY streamer gets in once it's this popular (it still sorts after T1/T2)
POPULAR_ANY_VIEWS = 250   # any streamer's GTA 6 clip gets in at 250+ views (sorted after T1-T3); None = tiers only

# TikTok is off: only the 5 YouTube channels get videos (TikTok folders are left alone)
MAKE_TIKTOK = False

# 🤖 Auto-pick: every 6 hours the robot approves the 10 most-viewed new clips by itself; Claude screens them,
# writes 5 hooks (one per channel) and sends them to editing. You can still approve clips by hand too.
AUTO_PICK = True
AUTO_PICKS_PER_WINDOW = 10
AUTO_WINDOW_HOURS = 6
