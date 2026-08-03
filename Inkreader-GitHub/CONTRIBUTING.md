# Contributing to InkRead

Thank you for helping improve InkRead.

## Development setup

1. Install Python 3.11+ and Node.js 20+ on Windows.
2. Run `python -m pip install -r requirements.txt`.
3. Run `npm ci`.
4. Run `npm run build`, then `python app.py`.

For frontend development, start the Python app/server first and run
`npm run dev` in another terminal. Vite proxies `/api` to the local InkRead
server.

## Before opening a pull request

```powershell
python scripts/check_secrets.py .
npm run check
npm run build
python -m unittest discover -s tests -v
```

Never commit API keys, `.env` files, user papers, screenshots, downloaded
models, local settings, logs, build directories, or release binaries. Use
synthetic fixtures in tests. Security reports belong in GitHub private
vulnerability reporting rather than public issues.
