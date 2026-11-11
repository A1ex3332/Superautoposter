# reel-autopost

**A free, serverless Instagram Reels scheduler that runs entirely on GitHub Actions.**

Drop videos into a folder, commit, and a cron workflow posts them one per slot with a sound from
Instagram's music library. No server, no hosting, no paid scheduler, no machine that has to be on.
Pure Python standard library.

[![CI](https://github.com/A1ex3332/reel-autopost/actions/workflows/ci.yml/badge.svg)](https://github.com/A1ex3332/reel-autopost/actions/workflows/ci.yml)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Why this exists

Most posting tools either charge a monthly fee, need a public URL for every video, or need a box
that is switched on at posting time. Meta's own API makes two things awkward that this tool
handles for you:

- **Uploading from the repo.** The poster uses Meta's resumable upload, so a video committed to the
  repo can be published without any hosting. If the repo is public it switches to a `video_url`
  fetch, which keeps the sound attached more reliably.
- **Library sounds by API.** The Meta Audio API (`ig_audio` + `audio_configuration`) lets a Reel
  carry a sound from Instagram's library. The poster lists today's trending sounds, skips ones
  you have banned by keyword, avoids repeating a sound within ten posts, and lets a single video
  pin an exact sound or search for one. This needs a Facebook-login (Page) token, which the
  setup below walks through.

What it is not: a growth hack, a scraper, or anything that touches accounts you do not own.
It calls the official Instagram Graph API with your own token and stays well inside Meta's
publishing limits.

## How it works

```
accounts/<name>/videos/001-first.mp4   -->  cron slot  -->  Instagram Reel (+ library sound)
accounts/<name>/videos/001-first.txt        (GitHub        posted.json committed back
accounts/<name>/config.json                  Actions)       optional Buffer cross-post
```

- Each account is a folder under `accounts/`. Videos post in name order, one per slot.
- The workflow runs four slots a day (09:23, 13:23, 17:23 and 20:23 UTC). Each account picks
  which slots it uses with `post_hours_utc`.
- A slot can own its own queue (`"slot_queues": {"20": "asmr"}`), so one account can run two
  content series at different times of day.
- Each slot posts at most once a day. GitHub's timer is often late and an outside timer may fire
  on time, so the poster never double-posts.
- After each post the workflow commits `posted.json` with the link and the sound used.
- Cost: about one minute of GitHub Actions per post. The free tier gives 2,000 minutes a month.

## Setup (about 10 minutes)

### 0. Requirements
- An Instagram **Creator or Business** account, **linked to a Facebook Page**.
- A Meta developer app (free) at https://developers.facebook.com with the Instagram product added.

### 1. Get a token from Meta
Use a **Facebook-login (Page) token**. The "API setup with Instagram login" page also offers
tokens, but those start with `IG` and cannot attach sounds, so the poster would post silently.

1. Open https://developers.facebook.com/tools/explorer/ and pick your app.
2. Under **Permissions** add `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement` (and `business_management` if listed).
3. Click **Generate Access Token**, log in with Facebook and tick **every Page** whose Instagram
   you want to post to. One token covers all of them.
4. Make it long-lived: click the blue **i** next to the token, **Open in Access Token Tool**,
   then **Extend Access Token**. Copy the extended token.

An extended user token lasts about 60 days. The test run tells you when it has expired; repeat
the steps and update the secret.

### 2. Add the secret to GitHub
Repo **Settings > Secrets and variables > Actions > New repository secret**:
`IG_ACCESS_TOKEN` = the extended token. Never commit it and never paste it into an issue.

### 3. Create an account folder
Copy `accounts/example/` to `accounts/<name>/`, set `ig_user_id` (the Instagram professional
account ID shown on your app's Instagram setup page), set `enabled` to `true`, and pick
`post_hours_utc`. See [accounts/README.md](accounts/README.md) for every key.

### 4. Test it
**Actions > Autopost reel > Run workflow**, mode `test`. The log shows the username, today's
publishing quota and the trending sounds. Nothing is posted. Mode `post` publishes the next
reel immediately.

## Adding reels

Drop `.mp4` or `.mov` files into `accounts/<name>/videos/`, named in the order you want them
posted (`003-...`, `004-...`). Optional sidecars with the same stem:

- `003-clip.txt`: the caption.
- `003-clip.json`: `{"caption": "...", "audio_query": "lofi", "audio_id": "...", "audio_volume": 50, "video_volume": 100, "no_audio": false}`

`audio_query` searches the library instead of using trending. `audio_id` pins an exact sound
(IDs appear in the test log). `no_audio` posts without a library sound. Use videos without
baked-in music so the library sound is not fighting another track, and do not bake in
copyrighted songs.

## Running locally

```bash
pip install -e ".[dev]"
IG_ACCESS_TOKEN=... reel-autopost test myaccount
IG_ACCESS_TOKEN=... reel-autopost post myaccount
pytest
```

`ACCOUNTS_DIR` overrides the accounts folder. `VIDEO_URL_BASE` makes the poster hand Meta a
public URL instead of uploading bytes.

## On-time posting with an outside timer (optional)

GitHub's cron can run hours late. Any free HTTP cron service can start the workflow on time:

- `POST https://api.github.com/repos/<owner>/<repo>/actions/workflows/autopost.yml/dispatches`
- Headers: `Authorization: Bearer <fine-grained token with Actions read and write on this repo>`,
  `Accept: application/vnd.github+json`
- Body: `{"ref":"main","inputs":{"mode":"post","account":"all","slot":"17"}}`

The `slot` input marks which slot the run belongs to. When GitHub's late run arrives afterwards
it sees the slot is already done and skips.

## Cross-posting to TikTok and YouTube Shorts (optional)

Set `buffer_crosspost: true` in an account's config and add a `BUFFER_API_KEY` secret. After
each Instagram post, `reel_autopost.crosspost` sends the same video and caption to every
TikTok and YouTube channel connected in Buffer. The repo must be public, because Buffer fetches
the video by URL. Contributions that add other targets (direct TikTok or YouTube APIs) are
welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Limits and good practice

- Meta allows 100 published posts per 24 hours per account. One to three a day is sensible, at
  least three hours apart.
- Only sounds Meta has licensed for third-party apps appear in the library list, and there is
  no preview. Some songs you see in the app will not be available.
- `posted.json` records every post with its permalink and sound, so the repo is also a log.
- The poster treats a Meta error 190 as a bad or expired token and tells you how to fix it.

## Troubleshooting

| Message | Meaning |
|---|---|
| `Missing IG_ACCESS_TOKEN` | The secret is not set, or the workflow cannot read it (forks cannot read secrets). |
| `Cannot parse access token` (190) | Bad paste or expired token. Copy it again from the Access Token Tool. |
| `No Page linked to Instagram account` | The Instagram account is not linked to a Facebook Page, or the Page was not ticked when the token was generated. |
| `Instagram-login token ... WITHOUT a sound` | You used an `IG...` token. Generate a Facebook-login token instead. |
| Sound missing on the published Reel | Make the repo public so Meta fetches the video by URL, or pin a sound with `audio_id`. |

## Roadmap

- Direct TikTok and YouTube Shorts publishing without Buffer.
- A dry-run report of the next seven days of posts.
- Carousel and single-image posts.

## License

MIT. See [LICENSE](LICENSE). This project is not affiliated with Meta or Instagram.
