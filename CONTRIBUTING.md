# Contributing

Thanks for looking. Small, focused pull requests are the easiest to review.

## Ground rules

- Keep the runtime dependency-free. The poster must run on a bare `python3` in GitHub Actions.
- Never commit a token, an `ig_user_id` that is not the example, or a real `posted.json`.
  CI will not have secrets, so anything that needs a token must be behind the `test` mode guard.
- Every pure function gets a test in `tests/`. Network calls stay in `publish`, `search_audio`,
  `page_token_for` and the Buffer module so the rest is testable offline.

## Dev setup

```bash
git clone https://github.com/A1ex3332/Superautoposter
cd reel-autopost
pip install -e ".[dev]"
pytest
ruff check .
```

## Good first issues

- Direct TikTok publishing through the Content Posting API.
- Direct YouTube Shorts publishing through the Data API.
- A `plan` mode that prints the next seven days of posts per account without touching Meta.
- Carousel and single-image support.

## Reporting a bug

Open an issue with the workflow log (redact the token if it ever appears; it should not),
the account `config.json`, and the Meta error code. Do not attach the token.
