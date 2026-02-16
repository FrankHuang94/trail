# Portfolio Investor News Monitor

A lightweight Python monitor that watches investor-relations pages for your portfolio companies and sends a Gmail notification when links on those pages change.

Initial watchlist includes **AVGO (Broadcom)** and can be expanded in `portfolio.yaml`.

## How it works

1. Loads companies from `portfolio.yaml`.
2. Scrapes each IR page and collects matching links.
3. Compares against the previous run stored in `state.json`.
4. Sends an email if any monitored company changes.

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set Gmail credentials (use a Gmail **App Password**, not your normal password):

```bash
export GMAIL_USERNAME="you@gmail.com"
export GMAIL_APP_PASSWORD="your-16-char-app-password"
export NOTIFY_TO="you@gmail.com"   # optional; defaults to GMAIL_USERNAME
```

Run once in dry-run mode (prints email instead of sending):

```bash
python src/news_monitor.py --config portfolio.yaml --state state.json --dry-run --verbose
```

Run for real:

```bash
python src/news_monitor.py --config portfolio.yaml --state state.json
```

## Add more portfolio companies

Edit `portfolio.yaml`:

```yaml
companies:
  - name: Broadcom
    ticker: AVGO
    ir_url: https://investors.broadcom.com/
    include_keywords: [press, release, news, investor]

  - name: Example Inc
    ticker: EXM
    ir_url: https://investors.example.com/
    include_keywords: [press, release, news]
```

## Automate with GitHub Actions

This repo includes `.github/workflows/monitor.yml` scheduled every 30 minutes.

In your GitHub repo settings, add these secrets:

- `GMAIL_USERNAME`
- `GMAIL_APP_PASSWORD`
- `NOTIFY_TO` (optional)

Then enable Actions. The workflow will run on schedule and send alerts.

## Create a new GitHub repository and push

You asked for a new repo. Run these commands from this project folder after creating an empty repo in GitHub:

```bash
git remote add origin git@github.com:<your-username>/<your-new-repo>.git
git push -u origin work
```

If you prefer HTTPS:

```bash
git remote add origin https://github.com/<your-username>/<your-new-repo>.git
git push -u origin work
```

## Notes

- The first run creates baseline state and does not alert by default.
- Use `--notify-on-first-run` if you want an initial email summary immediately.
- Some IR websites are JS-heavy; if needed, extend this project with a headless browser later.
