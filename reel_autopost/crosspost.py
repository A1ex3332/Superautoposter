"""Optional: send reels that were just posted to Instagram on to TikTok and YouTube Shorts via Buffer.

Runs after the poster in the autopost workflow. For each account it reads posted.json, picks reels
posted in the last LOOKBACK_HOURS that have not been cross-posted yet, and asks Buffer to publish
them now on every connected TikTok / YouTube channel. Done reels are recorded in
accounts/<name>/buffer_posted.json so nothing posts twice.

Needs
  BUFFER_API_KEY   GitHub secret (Buffer > Settings > API)
  VIDEO_URL_BASE   a public base URL the video files can be fetched from
                   (Buffer downloads the video by URL; it has no upload API)

Usage
  python -m reel_autopost.crosspost test             list Buffer channels, post nothing
  python -m reel_autopost.crosspost post <account>   cross-post new reels for one account
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .poster import accounts_dir, load_meta

API = "https://api.buffer.com"
SERVICES = {"tiktok", "youtube"}
LOOKBACK_HOURS = float(os.environ.get("LOOKBACK_HOURS", "20"))
USER_AGENT = "reel-autopost"


def key():
    value = "".join(os.environ.get("BUFFER_API_KEY", "").split()).strip("'\"")
    if not value:
        sys.exit("Missing BUFFER_API_KEY. Add it under GitHub repo Settings > Secrets and variables > Actions.")
    return value


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": "Bearer " + key(),
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Buffer API HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"])[:800])
    return data["data"]


def channels():
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    found = []
    for org in orgs:
        res = gql("query($o: OrganizationId!) { channels(input: {organizationId: $o}) "
                  "{ id service name isDisconnected } }", {"o": org["id"]})
        found += res["channels"]
    return found


def title_for(video: Path, caption: str) -> str:
    """Short title for TikTok/YouTube: first caption line without hashtags, max 100 chars."""
    first = caption.strip().splitlines()[0] if caption.strip() else video.stem
    words = [w for w in first.split() if not w.startswith("#")]
    title = " ".join(words) or video.stem.replace("-", " ")
    return title[:100]


CREATE = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status } }
    ... on NotFoundError { message }
    ... on UnauthorizedError { message }
    ... on UnexpectedError { message }
    ... on RestProxyError { message }
    ... on LimitReachedError { message }
    ... on InvalidInputError { message }
  }
}
"""


def create_post(channel, video_url, caption, title, ai_generated=True):
    meta = {}
    if channel["service"] == "tiktok":
        meta["tiktok"] = {"title": title, "isAiGenerated": ai_generated}
    else:
        meta["youtube"] = {"title": title, "privacy": "public", "madeForKids": False,
                           "categoryId": "27", "notifySubscribers": True, "isAiGenerated": ai_generated}
    payload = {
        "channelId": channel["id"],
        "text": caption,
        "mode": "shareNow",
        "schedulingType": "automatic",
        "needsApproval": False,
        "assets": [{"video": {"url": video_url}}],
        "metadata": meta,
        "source": USER_AGENT,
    }
    return gql(CREATE, {"input": payload})["createPost"]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else "test"
    if not os.environ.get("BUFFER_API_KEY", "").strip():
        print("No BUFFER_API_KEY secret; skipping Buffer cross-posting.")
        return
    chans = [c for c in channels() if c["service"] in SERVICES and not c.get("isDisconnected")]
    print("Buffer TikTok/YouTube channels:", ", ".join(f"{c['service']}:{c['name']}" for c in chans) or "none")
    if mode == "test":
        return
    if not chans:
        print("No TikTok or YouTube channel is connected in Buffer; nothing to do.")
        return

    account = argv[1]
    accounts = accounts_dir()
    folder = accounts / account
    config = json.loads((folder / "config.json").read_text())
    if not config.get("buffer_crosspost", False):
        print(f"{account}: buffer_crosspost is off in config.json; skipping.")
        return
    base = os.environ.get("VIDEO_URL_BASE", "").rstrip("/")
    if not base:
        print("No public VIDEO_URL_BASE, so Buffer cannot fetch the video; skipping.")
        return

    posted = json.loads((folder / "posted.json").read_text()).get("posted", [])
    log_path = folder / "buffer_posted.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else {"posted": []}
    done = {(p["file"], p["channel_id"]) for p in log["posted"]}
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - LOOKBACK_HOURS * 3600))
    ai_generated = bool(config.get("ai_generated", True))

    status = 0
    for item in posted:
        if item.get("posted_at", "") < cutoff:
            continue
        video = folder / "videos" / item["file"]
        if not video.exists():
            continue
        rel = video.resolve().relative_to(accounts.parent).as_posix()
        url = f"{base}/{urllib.parse.quote(rel)}"
        caption = load_meta(video, config)["caption"]
        title = title_for(video, caption)
        for ch in chans:
            if (item["file"], ch["id"]) in done:
                continue
            try:
                res = create_post(ch, url, caption, title, ai_generated)
            except Exception as e:  # keep going for the other channel
                print(f"FAILED {item['file']} -> {ch['service']}:{ch['name']}: {e}")
                status = 1
                continue
            ok = res.get("__typename") == "PostActionSuccess"
            print(("Sent" if ok else "FAILED"), item["file"], "->", f"{ch['service']}:{ch['name']}", res)
            if ok:
                log["posted"].append({"file": item["file"], "channel_id": ch["id"], "service": ch["service"],
                                      "buffer_post_id": (res.get("post") or {}).get("id"),
                                      "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            else:
                status = 1
    log_path.write_text(json.dumps(log, indent=2) + "\n")
    sys.exit(status)


if __name__ == "__main__":
    main()
