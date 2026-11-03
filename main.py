"""TikTok auto-poster: Drive image -> ad video -> TikTok -> move to Done.

Run once per schedule tick. Posts at most ONE product per run.
"""
import asyncio
import datetime as dt
import html
import io
import json
import os
import random
import re
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path

import edge_tts
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

E = os.environ
ALL_FOLDER = E["DRIVE_ALL_FOLDER_ID"]
DONE_FOLDER = E["DRIVE_DONE_FOLDER_ID"]
SHEET_ID = E["SHEET_ID"]
GEMINI_KEY = E["GEMINI_API_KEY"]
GEMINI_MODEL = E.get("GEMINI_MODEL", "gemini-2.5-flash")
VOICE = E.get("TTS_VOICE", "fil-PH-AngeloNeural")  # or fil-PH-BlessicaNeural
TIKTOK_MODE = E.get("TIKTOK_MODE", "direct")  # direct | draft
TIKTOK_PRIVACY = E.get("TIKTOK_PRIVACY", "SELF_ONLY")  # PUBLIC_TO_EVERYONE after TikTok audit
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

creds = service_account.Credentials.from_service_account_info(
    json.loads(E["GOOGLE_SA_JSON"]),
    scopes=[
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
)
drive = build("drive", "v3", credentials=creds, cache_discovery=False)
sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------------------------------------------------------------- Sheets
def sheet_get(rng):
    r = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=rng).execute()
    return r.get("values", [])


def sheet_set(rng, values):
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range=rng, valueInputOption="RAW", body={"values": values}
    ).execute()


def sheet_append(rng, row):
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID, range=rng, valueInputOption="RAW",
        insertDataOption="INSERT_ROWS", body={"values": [row]},
    ).execute()


# ---------------------------------------------------------------- Drive
def list_images():
    q = f"'{ALL_FOLDER}' in parents and trashed=false and mimeType contains 'image/'"
    r = drive.files().list(
        q=q, orderBy="createdTime", fields="files(id,name)", pageSize=200,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    return r.get("files", [])


def download(file_id, dest):
    req = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    Path(dest).write_bytes(buf.getvalue())


def move_to_done(file_id):
    drive.files().update(
        fileId=file_id, addParents=DONE_FOLDER, removeParents=ALL_FOLDER,
        fields="id", supportsAllDrives=True,
    ).execute()


# ---------------------------------------------------------------- Gemini
def parse_name(stem):
    if " - " in stem:
        product, moto = stem.rsplit(" - ", 1)
    else:
        product, moto = stem, "motorcycle"
    return product.strip(), moto.strip()


def gemini_copy(product, moto):
    prompt = f"""You write short TikTok Shop ad copy for a Philippine motorcycle-parts seller.
Product: {product}
Fits: {moto}

Rules:
- Use ONLY the product name and motorcycle type above. Do NOT invent specs, prices, discounts,
  materials, warranties, or performance claims.
- Taglish (casual Filipino + English), friendly, motorcycle-rider tone.
- "hook": max 6 words, shown on screen, plain text, NO emojis.
- "script": 38-45 words voiceover, ends by telling viewers to check the link in bio.
- "caption": 1-2 short sentences with 1-2 emojis, mentions the product and the motorcycle.
- "hashtags": 6-8 hashtags (include #TikTokShop and #motorcycle), no spaces inside tags.

Return JSON: {{"hook": str, "script": str, "caption": str, "hashtags": [str]}}"""
    for attempt in range(3):
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=90,
        )
        if r.ok:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Gemini failed: {r.status_code} {r.text[:300]}")


# ---------------------------------------------------------------- Video
def probe_len(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)]
    )
    return float(out.strip())


def make_tts(text, dest):
    async def run():
        await edge_tts.Communicate(text, VOICE).save(str(dest))
    asyncio.run(run())


def wrap(text, width):
    return "\n".join(textwrap.wrap(text, width))


def make_video(img, voice, hook, product, moto, out_path, tmp):
    dur = max(15.0, min(20.0, probe_len(voice) + 1.5))
    frames = int(dur * 30)
    (tmp / "hook.txt").write_text(wrap(hook.upper(), 16))
    (tmp / "badge.txt").write_text(wrap(f"{product}\nFits: {moto}", 28))
    (tmp / "cta.txt").write_text("LINK IN BIO")

    def dt_(name, size, y, extra=""):
        return (f"drawtext=fontfile={FONT}:textfile={tmp / name}:fontsize={size}:"
                f"fontcolor=white:borderw=5:bordercolor=black:line_spacing=12:"
                f"x=(w-text_w)/2:y={y}{extra}")

    fc = (
        "[0:v]split=2[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=40[bg];"
        "[b]scale=1000:1000:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,scale=2160:3840,"
        f"zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s=1080x1920:fps=30,format=yuv420p,"
        + dt_("hook.txt", 78, "h*0.10", ":enable='between(t,0,4)'") + ","
        + dt_("badge.txt", 46, "h*0.74",
              ":box=1:boxcolor=black@0.55:boxborderw=18") + ","
        + dt_("cta.txt", 70, "h*0.88", f":enable='gte(t,{dur - 6:.1f})'")
        + "[v];"
    )
    music = sorted(Path("music").glob("*.mp3"))
    cmd = ["ffmpeg", "-y", "-i", str(img), "-i", str(voice)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(random.choice(music))]
        fc += ("[1:a]adelay=500|500,apad[va];[2:a]volume=0.12[ma];"
               "[va][ma]amix=inputs=2:duration=first:dropout_transition=0[aud]")
    else:
        fc += "[1:a]adelay=500|500,apad[aud]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[aud]", "-t", f"{dur:.2f}",
            "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------- TikTok
def tiktok_access_token():
    rows = sheet_get("state!A1")
    refresh = rows[0][0] if rows and rows[0] else E["TIKTOK_REFRESH_TOKEN"]
    r = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": E["TIKTOK_CLIENT_KEY"],
            "client_secret": E["TIKTOK_CLIENT_SECRET"],
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
        timeout=30,
    )
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"TikTok token refresh failed: {j}")
    if j.get("refresh_token"):
        sheet_set("state!A1", [[j["refresh_token"]]])  # keep rotated token
    return j["access_token"]


def tiktok_post(video, caption):
    token = tiktok_access_token()
    size = os.path.getsize(video)
    draft = TIKTOK_MODE == "draft"
    base = "https://open.tiktokapis.com/v2/post/publish/"
    url = base + ("inbox/video/init/" if draft else "video/init/")
    body = {"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": size, "total_chunk_count": 1}}
    if not draft:
        body["post_info"] = {"title": caption[:2200], "privacy_level": TIKTOK_PRIVACY,
                             "disable_comment": False, "disable_duet": False,
                             "disable_stitch": False}
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    j = requests.post(url, headers=hdr, json=body, timeout=60).json()
    if j.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok init failed: {j}")
    publish_id, upload_url = j["data"]["publish_id"], j["data"]["upload_url"]

    with open(video, "rb") as f:
        data = f.read()
    r = requests.put(
        upload_url, data=data, timeout=300,
        headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                 "Content-Range": f"bytes 0-{size - 1}/{size}"},
    )
    if r.status_code not in (200, 201, 206):
        raise RuntimeError(f"TikTok upload failed: {r.status_code} {r.text[:300]}")

    ok_state = "SEND_TO_USER_INBOX" if draft else "PUBLISH_COMPLETE"
    for _ in range(40):  # ~5 min
        time.sleep(8)
        s = requests.post(base + "status/fetch/", headers=hdr,
                          json={"publish_id": publish_id}, timeout=30).json()
        status = s.get("data", {}).get("status")
        print("TikTok status:", status)
        if status == ok_state:
            return publish_id
        if status == "FAILED":
            raise RuntimeError(f"TikTok publish failed: {s}")
    raise RuntimeError("TikTok publish timed out (file NOT moved)")


# ---------------------------------------------------------------- Link page
def build_link_page():
    rows = sheet_get("posted!A2:F")
    items = []
    for r in reversed(rows):
        if len(r) >= 5:
            items.append(
                f'<li><a href="{html.escape(r[4])}" rel="noopener">{html.escape(r[2])}</a>'
                f' <small>({html.escape(r[3])})</small></li>'
            )
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product Links</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem}}
li{{margin:.7rem 0;font-size:1.1rem}}small{{color:#666}}</style></head>
<body><h1>Product Links</h1><ul>{''.join(items)}</ul></body></html>"""
    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- Main
def main():
    links = {}
    for r in sheet_get("links!A2:B"):
        if len(r) >= 2 and r[0].strip() and r[1].strip():
            links[norm(r[0])] = r[1].strip()
    posted = {norm(r[1]) for r in sheet_get("posted!A2:F") if len(r) > 1}

    chosen = None
    for f in list_images():
        stem = Path(f["name"]).stem
        key = norm(stem)
        if key in posted:  # posted earlier but move failed -> just tidy up
            move_to_done(f["id"])
            continue
        if key in links:
            chosen = (f, stem, links[key])
            break
    if not chosen:
        print("Nothing to post (no image in All Product has a link in the Sheet).")
        build_link_page()
        return

    f, stem, link = chosen
    product, moto = parse_name(stem)
    print(f"Posting: {product} | {moto}")

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        img = tmp / ("image" + Path(f["name"]).suffix.lower())
        download(f["id"], img)

        copy = gemini_copy(product, moto)
        voice = tmp / "voice.mp3"
        make_tts(copy["script"], voice)
        video = tmp / "ad.mp4"
        make_video(img, voice, copy["hook"], product, moto, video, tmp)

        tags = " ".join(h if h.startswith("#") else "#" + h for h in copy["hashtags"])
        caption = f"{copy['caption']}\n\nLink in bio \U0001F446\n\n{tags}"
        publish_id = tiktok_post(video, caption)

    # Log FIRST, then move: if the move fails, next run will not repost.
    sheet_append("posted!A:F", [dt.datetime.utcnow().isoformat(timespec="seconds"),
                                stem, product, moto, link, publish_id])
    move_to_done(f["id"])
    build_link_page()
    print("Done.")


if __name__ == "__main__":
    main()
