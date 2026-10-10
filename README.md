# Insta Autopilot

Makes and posts one Instagram Reel a day, on its own, from your Windows laptop.
One account, two topics that alternate: **personal finance** one day, **history** the next.

Each day it:
1. picks a topic (avoiding recent ones; Reddit's daily top posts are used only as loose inspiration),
2. has Claude write an original script, then has Claude fact-check it in a separate pass,
3. speaks it with a free text-to-speech voice,
4. adds free Pexels stock footage and big captions into a 1080x1920 video,
5. uploads the video to your bucket, publishes it through Instagram's official API, and removes the upload.

If a script fails the checks three times, **nothing is posted that day** (the log says why).

---

## Setup (about 45 minutes, once)

### 1. Install Python
Download Python 3.11 or newer from python.org. On the first installer screen, tick **"Add python.exe to PATH"**.

### 2. Install the project
Open PowerShell in this folder (in File Explorer: click the address bar, type `powershell`, press Enter):

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then open `.env` in Notepad and fill in the values below as you collect them.

### 3. Get your keys

**Claude:** create an API key at console.anthropic.com and paste it as `ANTHROPIC_API_KEY`.
Daily use is small, but the API is billed separately from a Claude chat subscription.

**Pexels (free footage):** sign up at pexels.com/api and paste the key as `PEXELS_API_KEY`.
Pexels footage is free to use without attribution under Pexels' own license. Read it once yourself.

**Video hosting (Cloudflare R2 works well and is cheap):**
Instagram only accepts a public web link to the video, so each video is uploaded here for a few minutes.
1. Create a Cloudflare account, open R2, create a bucket.
2. In the bucket's settings, turn on public access (the `r2.dev` address is fine) and copy that address into `S3_PUBLIC_BASE_URL`.
3. Create an R2 API token with read and write access to that bucket. Put the access key ID and secret in `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`.
4. `S3_ENDPOINT_URL` looks like `https://<your-account-id>.r2.cloudflarestorage.com`, and `S3_BUCKET` is the bucket name.

**Instagram (the fiddly part):** Meta's screens change often, so use Meta's current "Instagram Platform: Content Publishing" guide alongside these steps.
1. In the Instagram app, switch the account to a **Creator** or **Business** account and link it to a Facebook Page.
2. At developers.facebook.com, create an app and add the Instagram product that supports publishing Reels.
3. Request the permissions `instagram_basic`, `instagram_content_publish`, `pages_show_list` and `pages_read_engagement`. For your own account while the app is in development mode, Meta generally does not require app review. Check the guide.
4. In the Graph API Explorer, generate a user token with those permissions. Exchange it for a long-lived token, then use it to get a **Page access token** from `me/accounts`. Page tokens made from a long-lived user token are documented as not expiring. Check that this still holds. Use that token as `IG_ACCESS_TOKEN`.
5. Find your Instagram account ID: call `<page-id>?fields=instagram_business_account` and put the returned id in `IG_USER_ID`.

If your token ever expires, the daily run fails and says so in the log. Generate a new one and replace it in `.env`.

### 4. Test the connections
```powershell
python main.py check
```
Every line should say `[ OK ]`. Fix any `[FAIL]` before going on.

### 5. Make a test video without posting
```powershell
python main.py run --dry-run
```
Open the new folder under `output\`. It has `video.mp4`, `caption.txt` and `script.json`. Watch the video and read the script.
Do this for a few days with different niches (`--niche finance`, `--niche history`) before you trust it.

### 6. Turn on the daily schedule
```powershell
.\schedule_windows.ps1 -Time "18:30"
```
If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.
If the laptop is off at that time, the post happens as soon as it is next on and online.
To stop: `.\schedule_windows.ps1 -Remove`, or set `auto_post: false` in `config.yaml`.

---

## Day to day

- **Logs:** `logs\autopilot.log`. Check it if a day was missed.
- **Already posted today?** The run skips itself, so a retry never double-posts. `--force` overrides that.
- **Change the style or topics:** edit the `style` and `rules` text under each niche in `config.yaml`.
- **Change the voice:** edit `voice` in `config.yaml`. Some English voices: `en-IN-NeerjaNeural`, `en-IN-PrabhatNeural`, `en-US-GuyNeural`, `en-US-AriaNeural`.
- **Post times:** Instagram does not need the schedule to match your audience's peak hours, but if you want that, change the `-Time` value and register the task again.

## Things you should know

- **The fact-check is a second pass by the same model, with no internet lookup.** It catches many errors but not all. Stick to well-known history and general finance concepts (that is what the prompts enforce) and spot-check the first couple of weeks. You are the publisher of everything posted.
- **Finance rules are strict on purpose.** The prompt forbids naming specific stocks, funds or products, promising returns, or quoting current rates or tax rules. In India, giving specific investment advice can require SEBI registration, so don't loosen those rules without checking.
- **Originality matters for growth and monetization.** Instagram stops recommending accounts that mostly post unoriginal content and may label AI-generated media. Scripts here are written from scratch, but a long run of near-identical videos can still look low-effort. Vary the style prompts over time, and consider adding your own voice or angle.
- **No background music** is added, on purpose, to avoid copyright claims. If you add music, use only tracks you have the rights to.
- **Fully automatic posting is on** (`auto_post: true`), as you chose. A safer first week is `auto_post: false`: videos are generated daily and you post the good ones by hand.
- **Never share `.env`.** It contains keys that can post to your account and spend your API credit.
