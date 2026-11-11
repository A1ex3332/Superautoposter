# accounts/

One folder per Instagram account. Copy `example/` to `<name>/` and edit `config.json`.

```
accounts/
  <name>/
    config.json      account settings (see below)
    posted.json      written by the poster after each post; commit it
    videos/          the queue: 001-first.mp4, 002-second.mp4, ...
      001-first.txt  optional caption
      001-first.json optional overrides: caption, audio_query, audio_id, audio_volume, video_volume, no_audio
```

| Key | Meaning |
|---|---|
| `ig_user_id` | The Instagram professional account ID (a long number from the Meta app's Instagram setup page). Not a secret, but it identifies your account, so keep it out of public forks if you prefer. |
| `enabled` | `false` pauses the account. |
| `post_hours_utc` | Which workflow slots this account posts in. Default slots are 09, 13, 17 and 20 UTC. |
| `default_hashtags` | Appended when a video has no caption file. |
| `audio_volume` / `video_volume` | Mix between the library sound and the video's own audio, 0 to 100. |
| `skip_sound_words` | Trending sounds whose title or artist contains any of these are skipped. |
| `slot_queues` | Give a slot its own queue, e.g. `{"20": "asmr"}`: the 20:xx slot only posts files with `asmr` in the name and other slots skip them. |
| `buffer_crosspost` | Also send new posts to TikTok and YouTube Shorts through Buffer (needs `BUFFER_API_KEY`). |
| `ai_generated` | Flag cross-posts as AI-generated on TikTok and YouTube. |
