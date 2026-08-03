# Publishing checklist

The prepared source tree is designed to become a new public GitHub repository
without carrying over local build output or credential history.

1. Revoke any credential that has previously been pasted into a chat, issue,
   screenshot, log, or commit.
2. Run `python scripts/check_secrets.py .` and confirm it passes.
3. Review `git status --short` and ensure there are no papers, settings, logs,
   screenshots, local models, release binaries, or `.env` files.
4. Confirm that you have redistribution rights for custom icons, screenshots,
   sample papers, and other assets you add later.
5. Create an empty GitHub repository without an auto-generated README, then run:

```powershell
git commit -m "Initial open-source release"
git remote add origin https://github.com/<owner>/<repository>.git
git push -u origin main
```

After publishing, enable **Private vulnerability reporting** and GitHub secret
scanning in the repository Security settings.
