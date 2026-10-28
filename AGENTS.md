# Project guardrails

This repository is for Udit's single-account Telegram-to-Dhan trading bot.

- Keep one operator, one Telegram account, one Dhan account, and one deployment.
- Keep one shared `TEST`/`LIVE` switch, defaulting to `TEST`; equity and F&O each
  have a separate active/inactive setting.
- `TEST` validates and reports. It never submits orders and never creates fake
  orders, fills, holdings, or positions. Do not add paper trading.
- Do not submit a live order or deploy to production without Udit's explicit
  approval for that specific step.
- Do not commit credentials, `.env` files, Telegram sessions, access tokens,
  TOTP seeds, PINs, or runtime databases.
- Do not add multi-user architecture or integrations with Notion, Google Sheets,
  Kite, Railway, or other brokers.
- Treat `darvas_script-main.zip` only as a reference. Review and document any
  candidate rule before reuse; preserve approved rules exactly.
- Do not invent Dhan behavior. Link verified official documentation in
  `DHAN_API.md` and keep unresolved broker behavior blocked.
- Keep `README.md`, `REQUIREMENTS.md`, `PROJECT_STATUS.md`, `PROGRESS.md`,
  `DHAN_API.md`, and `DEPLOYMENT.md` current with each material change.
