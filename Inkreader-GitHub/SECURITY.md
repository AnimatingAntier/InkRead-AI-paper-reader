# Security Policy

## Reporting a vulnerability

Please use GitHub's **Private vulnerability reporting** feature in the
repository Security tab. Do not include credentials, private papers, local
paths, screenshots containing personal data, or exploit details in a public
issue.

## Credential handling

- InkRead does not ship with API keys.
- User settings are stored locally and `data/`, `.env*`, credential files, and
  build output are excluded by `.gitignore`.
- API keys returned to the interface are masked and are never included in
  exported source packages.
- The local HTTP API listens on `127.0.0.1` and rejects requests from foreign
  browser origins.
- Questions and selected paper context are sent only to the AI provider chosen
  by the user. Baidu translation receives selected English text only when that
  integration is enabled.

Before publishing a fork, run:

```powershell
python scripts/check_secrets.py .
```

If a credential was ever committed, deleting it from the latest revision is
not sufficient. Revoke it first, then rewrite the Git history before making
the repository public.
