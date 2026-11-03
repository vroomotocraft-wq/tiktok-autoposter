# TikTok Shop Auto-Poster (all free)

Drive image -> Gemini copy -> edge-tts voice -> FFmpeg video -> TikTok -> image moves to `Done`.
Runs 3x/day on GitHub Actions. One product per run.

## How you use it day to day
1. Rename the image `Product Name - Motorcycle Type.jpg`  (e.g. `LED Headlight H4 - Honda Click 125.jpg`). The ` - ` (space-dash-space) is the separator.
2. Drop it in the Drive folder **All Product**.
3. In the Google Sheet tab **links**, add a row: column A = the filename WITHOUT extension, column B = your TikTok Shop affiliate link.
   Images with no row are skipped (never stalls). Add links in bulk whenever you like.

## One-time setup
### 1. Google (free)
- console.cloud.google.com -> new project -> enable **Google Drive API** and **Google Sheets API**.
- IAM -> Service Accounts -> create one -> Keys -> Add key -> JSON. This file's full text = secret `GOOGLE_SA_JSON`.
- Create Drive folders **All Product** and **Done**. Share BOTH with the service account's email (Editor). Folder ID = last part of the folder URL.
- Create a Google Sheet with 3 tabs named exactly: `links`, `posted`, `state`. Share it with the service account (Editor). Sheet ID = the part of the URL between `/d/` and `/edit`.
  - `links` row 1: `name | link`
  - `posted` row 1: `time | file | product | motorcycle | link | publish_id`
  - `state`: leave empty (the script stores your rotating TikTok token in A1)

### 2. Gemini (free)
- aistudio.google.com -> Get API key = `GEMINI_API_KEY`. If the default model name stops working, set env `GEMINI_MODEL` to a current Flash model.

### 3. TikTok developer app (free)
- developers.tiktok.com -> create app -> add **Login Kit** and **Content Posting API**.
- Register a redirect URI you control (e.g. your GitHub Pages URL `https://<you>.github.io/<repo>/`).
- Run `python get_token.py` on your PC, follow the prompts, save the printed refresh token as `TIKTOK_REFRESH_TOKEN`.
- Until TikTok approves your app, posts can only be private/drafts. The workflow starts in `draft` mode. After approval set `TIKTOK_MODE: direct` and `TIKTOK_PRIVACY: PUBLIC_TO_EVERYONE` in `.github/workflows/post.yml`.

### 4. GitHub
- Push this folder to a new repo (public = unlimited free Actions minutes).
- Settings -> Secrets and variables -> Actions -> add: `GOOGLE_SA_JSON`, `DRIVE_ALL_FOLDER_ID`, `DRIVE_DONE_FOLDER_ID`, `SHEET_ID`, `GEMINI_API_KEY`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.
- Settings -> Pages -> deploy from branch `main`, folder `/docs`. Put that URL in your TikTok bio. It lists every posted product with its affiliate link, updated after each post.
- Actions tab -> autopost -> **Run workflow** to test once.

## Optional
- Drop royalty-free `.mp3` files in `music/` for quiet background music (use only music you have the rights to).
- Voice: set `TTS_VOICE` to `fil-PH-BlessicaNeural` for a female voice, or any `edge-tts --list-voices` voice.

## Safety behavior
- Image moves to `Done` only after TikTok confirms success.
- The post is logged to `posted` before the move, so a failed move can never cause a repost.
- Any failure leaves the image in `All Product`; the next run retries.
