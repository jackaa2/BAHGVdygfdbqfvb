# gta6-clip-robot

Hourly robot for **Leonida Reels | GTA 6**.

1. Pulls the most-viewed new **GTA 6** clips from Twitch (whole category + streamers in the sheet's *Streamers + Links* tab) and Kick (best effort).
2. Downloads the raw MP4 (no captions, no watermark) into Drive `01_Raw/<date>/`, named by Clip ID.
3. Adds a row to the sheet's **Control Panel** (status `Raw`) and writes a health line in `O1:R1`.

Claude screens the rows; you approve in the sheet; the sheet add-on (ClipHub.gs) moves approved files.
Next phase (`process.py`): captions + per-account watermark/hook versions into `04_Accounts/Account 1-6`.

## Secrets (Settings → Secrets and variables → Actions)
| Name | Where it comes from |
|---|---|
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | dev.twitch.tv/console → app → Manage |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google Cloud → APIs & Services → Credentials → OAuth client |
| `GOOGLE_REFRESH_TOKEN` | One-time sign-in at developers.google.com/oauthplayground (scopes: Drive + Sheets) |
| `SHEET_ID` | The long ID in the sheet's URL |

Tune what gets grabbed in `robot/config.py`. Run by hand: **Actions → Grab GTA 6 clips → Run workflow**.
