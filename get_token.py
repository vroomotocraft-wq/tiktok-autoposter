"""Run ONCE on your PC to get your TikTok refresh token.  python get_token.py"""
import secrets
import urllib.parse

import requests

key = input("TikTok client key: ").strip()
secret = input("TikTok client secret: ").strip()
redirect = input("Redirect URI (must match the one registered in your TikTok app): ").strip()

url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
    "client_key": key,
    "scope": "user.info.basic,video.publish,video.upload",
    "response_type": "code",
    "redirect_uri": redirect,
    "state": secrets.token_urlsafe(8),
})
print("\n1) Open this URL, log in as your TikTok account, and approve:\n", url)
cb = input("\n2) Paste the full URL you were redirected to: ").strip()
code = urllib.parse.parse_qs(urllib.parse.urlparse(cb).query)["code"][0]

r = requests.post(
    "https://open.tiktokapis.com/v2/oauth/token/",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={"client_key": key, "client_secret": secret, "code": code,
          "grant_type": "authorization_code", "redirect_uri": redirect},
)
j = r.json()
print("\nRefresh token (save as GitHub secret TIKTOK_REFRESH_TOKEN):\n", j.get("refresh_token"))
if "refresh_token" not in j:
    print("Full response:", j)
