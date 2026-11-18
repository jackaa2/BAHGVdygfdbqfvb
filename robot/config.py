"""Settings you can change without touching the rest of the code."""

# Google Sheet (set as a GitHub secret named SHEET_ID; this is only the fallback)
SHEET_ID_FALLBACK = ""

PANEL_TAB = "Control Panel"
STREAMERS_TAB = "Streamers + Links"
HEADER_ROWS = 3

# What counts as worth grabbing
GAME_NAMES = ["Grand Theft Auto VI"]   # Twitch category to pull top clips from
LOOKBACK_HOURS = 6                      # only clips made in the last N hours
MIN_VIEWS_CATEGORY = 300               # GTA 6 category clips (any streamer)
MIN_VIEWS_TRACKED = 100                # clips from streamers on our list
MIN_SECONDS, MAX_SECONDS = 6, 60
PREFERRED_SECONDS = 25         # clips up to this length are preferred; longer ones need ~40% more views
LANGUAGES = {"en"}                      # skip non-English clips
MAX_NEW_CLIPS_PER_RUN = 15              # every 30 min -> ~30 clips an hour

# Drive folders (fixed IDs, so renaming folders never breaks anything).
# Names are applied automatically on every run.
ROOT_FOLDER = ("1lZN5Lh0Vp0Y6gFd9tZ-sDyqCyQneaUWc", "GTA6 Clip Hub - VIDEOS")
FOLDERS = {
    "brand":    ("1arUg_7htt2yuWDGNckSwkbjhB7Exc9LF", "0 - Brand Kit (logos + watermarks)"),
    "new":      ("1jlABYCermfUiZy3h3J-kfgoXI_0ONAVB", "1 - New Clips (robot drops here)"),
    "hold":     ("1z-PtRgIk5FZ9Wtn_kjSaM5NjmX6sz9W4", "2 - On Hold"),
    "approved": ("1U8tdARMO6ecABiM7AAr4B4x0GH5XNhId", "3 - Approved (waiting for edits)"),
    "ready":    ("1tbW_vEMgs6rx7UlxW_miH8HeakZ4unfC", "4 - Ready to Post (by account)"),
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
    "hold": 7,          # "2 - On Hold" (a week)
    "approved": 1,      # raw clips in "3 - Approved": kept 1 day after their 6 versions were made
    "ready": 3,         # finished versions in "4 - Ready to Post/Account N"
}
DELETE_RAW_AFTER_EDIT = False # raw is kept 1 day after editing (see CLEANUP_DAYS['approved'])
STREAMER_ONLY_CAPTIONS = True  # skip game dialogue / donation voices / background chatter
MAX_CLIP_SECONDS = 60.0       # hard cap; longer clips are cut to the 60 s with the most talking
TRACKED_BOOST = 1.5           # clips from streamers on the Streamers + Links tab rank higher
