"""Post the next queued video for an Instagram account as a Reel, with a library sound.

Each account is a folder under accounts/<name>/ holding config.json, videos/ and posted.json.

Runs in GitHub Actions (see .github/workflows/autopost.yml) or locally:

    IG_ACCESS_TOKEN=... reel-autopost test myaccount
    IG_ACCESS_TOKEN=... reel-autopost post myaccount

Modes
  test  Check the token and list today's trending sounds. Posts nothing.
  post  Upload the next unposted video, attach a sound, publish.

Each video can have an optional sidecar file with the same stem:
  my-reel.txt   caption text
  my-reel.json  {"caption": "...", "audio_query": "...", "audio_id": "...",
                 "audio_volume": 60, "video_volume": 100, "no_audio": false}
Without a sidecar the caption is built from the file name.

Uses only the Python standard library.
"""

from __future__ import annotations

import calendar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = os.environ.get("GRAPH_VERSION", "v25.0")
GRAPH = "https://graph.facebook.com/" + VERSION
RUPLOAD = "https://rupload.facebook.com/ig-api-upload/" + VERSION
VIDEO_EXT = {".mp4", ".mov"}
RECENT_SOUNDS = 10  # a sound is not reused within this many posts


def accounts_dir() -> Path:
    """Folder holding one sub-folder per account (env ACCOUNTS_DIR, else ./accounts)."""
    return Path(os.environ.get("ACCOUNTS_DIR") or Path.cwd() / "accounts").resolve()


# ---------- helpers ----------

def clean_token(value: str) -> str:
    """Forgive copy-paste mess: whitespace, quotes, or a leading 'access_token='."""
    value = "".join((value or "").split()).strip("'\"")
    for prefix in ("access_token=", "AccessToken:", "Token:"):
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix):]
    return value


def env(name: str) -> str:
    value = clean_token(os.environ.get(name, ""))
    if not value:
        sys.exit(f"Missing {name}. Add it under GitHub repo Settings > Secrets and variables > "
                 "Actions.")
    return value


def request(method, url, params=None, data=None, headers=None, timeout=120):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        body = err.read().decode(errors="replace")
        try:
            detail = json.loads(body).get("error", body)
        except ValueError:
            detail = body
        hint = ""
        if isinstance(detail, dict) and detail.get("code") == 190:
            hint = ("\nThe IG_ACCESS_TOKEN secret is not a working token (expired, or not copied fully). "
                    "Copy it again from Meta's Access Token Tool or Graph API Explorer and update the secret.")
        raise RuntimeError(f"{method} {url.split('?')[0]} failed ({err.code}): {detail}{hint}") from None


def graph_get(path, token, **params):
    return request("GET", f"{GRAPH}/{path}", {**params, "access_token": token})


def graph_post(path, token, **params):
    body = urllib.parse.urlencode({**params, "access_token": token}).encode()
    return request("POST", f"{GRAPH}/{path}", data=body,
                   headers={"Content-Type": "application/x-www-form-urlencoded"})


# ---------- token ----------

def page_token_for(ig_user_id, token):
    """Swap a Facebook *user* token for the Page token linked to ig_user_id.

    A Page token derived from a long-lived user token does not expire, and it is what Meta
    expects for publishing. If the token is already a Page token it is returned unchanged.
    """
    try:
        pages = graph_get("me/accounts", token, fields="name,access_token,instagram_business_account",
                          limit=100).get("data", [])
    except RuntimeError:
        return token  # already a Page token (me/accounts only works for users)
    for page in pages:
        if (page.get("instagram_business_account") or {}).get("id") == ig_user_id:
            print(f"Using the Page token for Facebook Page '{page.get('name')}'")
            return page["access_token"]
    linked = [f"{p.get('name')} -> {(p.get('instagram_business_account') or {}).get('id', 'no Instagram')}"
              for p in pages]
    sys.exit("This Facebook login has no Page linked to Instagram account "
             f"{ig_user_id}. Pages found: {linked or 'none'}. Link the Instagram account to a "
             "Facebook Page (Instagram app > Edit profile > Page) and tick that Page when "
             "generating the token.")


# ---------- sounds ----------

def search_audio(ig_user_id, token, query=None, audio_type="music"):
    params = {"audio_type": audio_type, "user_id": ig_user_id}
    if query:
        params["search_query"] = query  # no query = trending list
    res = graph_get("ig_audio", token, **params)
    items = res.get("audio") or res.get("data") or []
    if isinstance(items, dict):
        items = items.get("data", [])
    return items


def describe(item):
    title = item.get("title") or item.get("name") or "?"
    artist = item.get("display_artist") or item.get("ig_username") or item.get("artist") or ""
    secs = round((item.get("duration_in_ms") or 0) / 1000)
    return f"{title} - {artist} ({secs}s) id={item.get('audio_id') or item.get('id')}"


def is_skipped(item, config):
    words = [w.lower() for w in config.get("skip_sound_words", [])]
    text = f"{item.get('title', '')} {item.get('display_artist', '')}".lower()
    return any(w in text for w in words)


def choose_sound(items, config, recent_ids, meta):
    """Pure selection: honour no_audio / audio_id, skip banned words, avoid recent sounds."""
    if meta.get("no_audio"):
        return None
    if meta.get("audio_id"):
        return {"audio_id": str(meta["audio_id"]), "title": "chosen by id"}
    if not items:
        raise RuntimeError("Meta returned no sounds. Run the workflow in test mode to see why.")
    allowed = [i for i in items if not is_skipped(i, config)] or list(items)
    fresh = [i for i in allowed if str(i.get("audio_id") or i.get("id")) not in recent_ids]
    choice = dict((fresh or allowed)[0])
    choice["audio_id"] = str(choice.get("audio_id") or choice.get("id"))
    return choice


def pick_audio(ig_user_id, token, meta, recent_ids, config):
    if meta.get("no_audio") or meta.get("audio_id"):
        return choose_sound([], config, recent_ids, meta)
    return choose_sound(search_audio(ig_user_id, token, meta.get("audio_query")), config, recent_ids, meta)


# ---------- queue ----------

def load_state(state_path: Path):
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {"posted": []}


def save_state(state_path: Path, state):
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def in_slot_queue(name, hour, config):
    """config "slot_queues" gives a slot its own queue, e.g. {"20": "asmr"}: the 20:xx slot only
    posts files whose name contains "asmr", and every other slot skips those files.
    Manual runs (hour None) take whatever is next."""
    queues = {str(k): v for k, v in config.get("slot_queues", {}).items()}
    if hour is None or not queues:
        return True
    mine = queues.get(str(hour))
    if mine:
        return mine in name
    return not any(word in name for word in queues.values())


def next_video(videos_dir: Path, state, config, hour=None):
    done = {p["file"] for p in state["posted"]}
    for f in sorted(videos_dir.iterdir()) if videos_dir.exists() else []:
        if f.suffix.lower() in VIDEO_EXT and f.name not in done and in_slot_queue(f.name, hour, config):
            return f
    return None


def caption_from_name(video: Path, config):
    name = video.stem.split("(")[0].strip().replace("-", " ").replace("_", " ")
    tags = config.get("default_hashtags", "#reels")
    return f"{name}\n\n{tags}".strip()


def load_meta(video: Path, config):
    meta = {}
    sidecar_json = video.with_suffix(".json")
    sidecar_txt = video.with_suffix(".txt")
    if sidecar_json.exists():
        meta = json.loads(sidecar_json.read_text(encoding="utf-8"))
    if "caption" not in meta:
        if sidecar_txt.exists():
            meta["caption"] = sidecar_txt.read_text(encoding="utf-8").replace("\r", "").strip()
        else:
            meta["caption"] = caption_from_name(video, config)
    return meta


# ---------- posting ----------

def publish(video: Path, meta, audio, ig_user_id, token, config, root: Path):
    params = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": meta["caption"],
        "share_to_feed": "true",
    }
    if audio:
        params["audio_configuration"] = json.dumps({
            "audio_id": audio["audio_id"],
            "audio_volume": int(meta.get("audio_volume", config.get("audio_volume", 60))),
            "video_volume": int(meta.get("video_volume", config.get("video_volume", 100))),
        })
    # Meta attaches the sound more reliably when it fetches the video from a public URL
    # (video_url). With a direct resumable upload the sound has been observed to be dropped,
    # so the public URL is used whenever the workflow provides one.
    base = os.environ.get("VIDEO_URL_BASE", "").strip()
    cid = None
    if base:
        rel = video.resolve().relative_to(root).as_posix()
        url = base.rstrip("/") + "/" + urllib.parse.quote(rel)
        try:
            url_params = {k: v for k, v in params.items() if k != "upload_type"}
            cid = graph_post(f"{ig_user_id}/media", token, video_url=url, **url_params)["id"]
            print(f"Container {cid} created from public URL {url}")
        except Exception as err:  # fall back to a direct upload
            print(f"Public URL route failed ({err}); uploading directly instead.")
    if cid is None:
        if audio:
            print("WARNING: direct upload; Instagram may drop the sound. Make the repo public "
                  "so the video can be fetched by URL (see README).")
        container = graph_post(f"{ig_user_id}/media", token, **params)
        cid = container["id"]
        print(f"Container {cid} created, uploading {video.stat().st_size / 1e6:.1f} MB")
        data = video.read_bytes()
        request("POST", f"{RUPLOAD}/{cid}", data=data, timeout=600, headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(len(data)),
        })

    for _ in range(60):  # up to about 10 minutes
        status = graph_get(cid, token, fields="status_code,status")
        code = status.get("status_code")
        print(f"  processing: {code}")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the video: {status.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Timed out waiting for Instagram to process the video.")

    result = graph_post(f"{ig_user_id}/media_publish", token, creation_id=cid)
    media_id = result["id"]
    link = graph_get(media_id, token, fields="permalink").get("permalink", "")
    return media_id, link


def scheduled_hour(schedule: str | None = None):
    """UTC hour of the cron slot that started this run, or None for a manual run."""
    sched = (schedule if schedule is not None else os.environ.get("SCHEDULE", "")).split()
    if len(sched) >= 2 and sched[1].isdigit():
        return int(sched[1])
    return None


def already_posted_for_slot(state, hour, config, now=None):
    """True if something was posted since this slot's start time.

    GitHub's own timer often fires hours late and an outside timer may fire the same slot on
    time, so each slot is allowed one post. A late run that crosses midnight belongs to
    yesterday's slot."""
    now = time.gmtime(now) if now is not None else time.gmtime()
    start = calendar.timegm((now.tm_year, now.tm_mon, now.tm_mday, hour, 0, 0))
    if now.tm_hour < hour:
        start -= 86400
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start))
    return any(p.get("posted_at", "") >= stamp and in_slot_queue(p.get("file", ""), hour, config)
               for p in state.get("posted", []))


def run(mode: str, account: str) -> None:
    global GRAPH
    accounts = accounts_dir()
    folder = accounts / account
    if not (folder / "config.json").exists():
        names = [p.name for p in accounts.iterdir()] if accounts.exists() else []
        sys.exit(f"No account folder {folder}. Accounts: {names}")
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    videos, state_path = folder / "videos", folder / "posted.json"
    root = accounts.parent
    print(f"== Account: {account}")

    if mode == "post":
        if not config.get("enabled", True):
            print("Account is disabled in config.json; skipping.")
            return
        hour = scheduled_hour()
        if hour is not None and hour not in config.get("post_hours_utc", [17]):
            print(f"Not a posting slot for this account (slot {hour}:xx UTC, "
                  f"posts at {config.get('post_hours_utc')}); skipping.")
            return
        if not next_video(videos, load_state(state_path), config, hour):
            print("Nothing queued for this account (or this slot); skipping.")
            return
        if hour is not None and already_posted_for_slot(load_state(state_path), hour, config):
            print(f"Already posted for the {hour}:xx UTC slot today; skipping.")
            return

    token = env("IG_ACCESS_TOKEN")
    ig_user_id = str(config.get("ig_user_id") or env("IG_USER_ID"))
    # Tokens from "API setup with Instagram login" start with IG and use graph.instagram.com.
    # Meta's sound library only works with Facebook-login tokens, so those post without a sound.
    instagram_login = token.startswith("IG")
    if instagram_login:
        GRAPH = "https://graph.instagram.com/" + VERSION
        print("WARNING: this is an Instagram-login token. Meta only allows library sounds with a "
              "Facebook-login (Page) token, so reels will post WITHOUT a sound. See README.")
    else:
        token = page_token_for(ig_user_id, token)

    me = graph_get(ig_user_id, token, fields="username")
    print(f"Token OK for @{me.get('username')}")

    if mode == "test":
        try:
            limit = graph_get(f"{ig_user_id}/content_publishing_limit", token, fields="quota_usage,config")
            print(f"Posts used in last 24h: {limit}")
        except RuntimeError as err:
            print(f"(could not read publishing limit: {err})")
        if not instagram_login:
            print("\nTrending sounds right now:")
            items = search_audio(ig_user_id, token)
            for item in items[:15]:
                print("  " + describe(item))
            if not items:
                print("  none returned")
        nxt = next_video(videos, load_state(state_path), config)
        print(f"\nNext video to post: {nxt.name if nxt else f'none - add files to {videos}'}")
        return

    if mode != "post":
        sys.exit("Mode must be 'test' or 'post'.")

    state = load_state(state_path)
    video = next_video(videos, state, config, scheduled_hour())
    if not video:
        print("Nothing to post: every queued video has been posted.")
        return
    meta = load_meta(video, config)
    recent = {str(p.get("audio_id")) for p in state["posted"][-RECENT_SOUNDS:]}
    audio = None if instagram_login else pick_audio(ig_user_id, token, meta, recent, config)
    print(f"Posting {video.name}")
    print(f"Sound: {describe(audio) if audio else 'none'}")

    media_id, link = publish(video, meta, audio, ig_user_id, token, config, root)
    state["posted"].append({
        "file": video.name,
        "media_id": media_id,
        "permalink": link,
        "audio_id": audio["audio_id"] if audio else None,
        "audio_title": (audio.get("title") if audio else None),
        "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    save_state(state_path, state)
    print(f"Posted: {link}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"**{account}**: posted **{video.name}** with sound "
                     f"*{audio.get('title') if audio else 'none'}*: {link}\n")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = (argv[0] if argv else "test").lower()
    account = argv[1] if len(argv) > 1 else "all"
    accounts = accounts_dir()
    if account != "all":
        names = [account]
    elif accounts.exists():
        names = sorted(p.name for p in accounts.iterdir() if (p / "config.json").exists())
    else:
        names = []
    if not names:
        sys.exit(f"No accounts found in {accounts}. Copy accounts/example/ to accounts/<name>/.")
    failed = 0
    for name in names:
        try:
            run(mode, name)
        except SystemExit as err:
            if err.code not in (None, 0):
                print(err.code, file=sys.stderr)
                failed += 1
        except Exception as err:  # keep going for the other accounts
            print(f"FAILED {name}: {err}", file=sys.stderr)
            failed += 1
        print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
