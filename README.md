# StreakBot

Personal accountability reminders with streaks and a leaderboard.

## Setup

1. Create a bot at https://discord.com/developers/applications, add a bot user, and copy its token.
2. Invite it to your server with the `bot` and `applications.commands` scopes, and the "Send Messages", "Add Reactions", "Embed Links", and "Read Message History" permissions.
3. `cp .env.example .env` and paste the token in as `DISCORD_TOKEN`.
4. `python3.11 -m venv venv && ./venv/bin/pip install -r requirements.txt`
5. `./venv/bin/python bot.py`

## Using it

- An admin runs `/setup channel #accountability` once, to pick where reminders and check-ins get posted.
- Each person runs `/remind set label:walk activity:"walk 10k steps" start:09:00 end:10:00 timezone:ET` to sign up. `label` is a short name for this specific reminder — you can sign up for as many as you want (e.g. a second one with `label:sober`), each with its own independent streak. Reusing a label updates that reminder instead of creating a duplicate. `timezone` is optional and defaults to Eastern if you never set one; after the first time the bot remembers your default and reuses it for any `/remind set` call that omits it. `start` and `end` must fall on the same day (overnight windows aren't supported).
- At `start`, the bot posts a reminder tagging them and naming the label. Reacting ✅ (on that message or the nudge below) logs the check-in and bumps that reminder's streak.
- If they haven't checked in by 30 minutes before `end`, the bot posts a nudge with the time remaining.
- If they still haven't checked in by `end`, the streak resets to 0 and the bot posts about it in the channel. This also self-heals if the bot was offline right at `end` — it catches up and resolves the missed day the next time it runs.
- `/remind status` lists all of your reminders with their streaks; `/remind stop label:walk` permanently deletes that reminder and its streak (autocomplete suggests your labels) — running `/remind set` with the same label afterward starts a brand new one at streak 0; `/remind timezone` updates your saved default timezone for future `/remind set` calls without touching existing reminders.
- `/leaderboard` posts every reminder's current and best streak across the server, sorted by display name (no pings), for people to cheer on with reactions.
- An admin can also run `/setup leaderboard time:20:00 timezone:ET` to have the leaderboard post itself automatically once a day (skips posting on a day with no streaks yet). `/setup leaderboard off` turns that back off; `/leaderboard` still works manually anytime either way.
- `/help` explains all of this in-app.

Discord doesn't expose a user's real timezone to bots, so it can't be auto-detected. `timezone` accepts common abbreviations — `ET`, `CT`, `MT`, `PT`, `AT`, `AKT`, `HT`, `UTC`/`GMT` — which map to a real IANA zone under the hood so daylight saving is handled automatically (a bare "EST" would otherwise be wrong for half the year). Full IANA names like `America/New_York` also work if you need one outside that list.
