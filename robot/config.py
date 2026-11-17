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
LANGUAGES = {"en"}                      # skip non-English clips
MAX_NEW_CLIPS_PER_RUN = 15              # keeps Drive + your queue under control
