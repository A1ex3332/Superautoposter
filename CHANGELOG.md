# Changelog

## 1.0.0 (2026-11-11)

First public release, extracted from a private automation that has posted daily since
2 November 2026.

- Multi-account queues under `accounts/<name>/`, posted in file-name order.
- Resumable upload straight from the repo; `video_url` fetch when the repo is public.
- Library sounds through the Meta Audio API: trending list, keyword skip list, no repeats
  within ten posts, per-video `audio_query` and `audio_id`.
- Per-slot queues (`slot_queues`) so one account can run two series.
- One post per slot per day, so a late GitHub cron and an on-time outside timer never
  double-post.
- Optional Buffer cross-post to TikTok and YouTube Shorts.
- `reel-autopost` console script, `python -m reel_autopost`, offline test suite, CI on
  Python 3.10 to 3.13.
