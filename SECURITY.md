# Security

## Where secrets live

The only secret this project needs is `IG_ACCESS_TOKEN` (and `BUFFER_API_KEY` if you use
cross-posting). They are stored as GitHub Actions repository secrets, read from the environment at
run time, and never written to disk, to `posted.json`, or to the step summary. Workflow logs mask
them.

The repository itself contains no credentials. `accounts/<name>/config.json` holds an
`ig_user_id`, which identifies an account but grants no access.

## Forks and pull requests

GitHub does not expose secrets to workflows triggered from forks, so a malicious pull request
cannot post to your account. CI runs without any token.

## Reporting a vulnerability

Open a GitHub issue with the title prefixed `[security]`, or use GitHub's private vulnerability
reporting on the repository if it is enabled. Please do not include your token in the report.
