import logging
import os
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands
from dotenv import load_dotenv

import db
from cogs.leaderboard import build_leaderboard_embed

load_dotenv()
TOKEN = os.environ["DISCORD_TOKEN"]
CHECK_EMOJI = "✅"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("streakbot")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler()


NUDGE_MINUTES_BEFORE_END = 30


async def process_reminders():
    now_utc = datetime.now(dt_timezone.utc)
    for reminder in db.get_all_reminders():
        try:
            local_now = now_utc.astimezone(ZoneInfo(reminder["timezone"]))
        except Exception:
            log.warning("Bad timezone %s for user %s", reminder["timezone"], reminder["user_id"])
            continue

        now_minute_of_day = local_now.hour * 60 + local_now.minute
        today_str = local_now.date().isoformat()
        start_minute_of_day = reminder["start_hour"] * 60 + reminder["start_minute"]
        end_minute_of_day = reminder["end_hour"] * 60 + reminder["end_minute"]
        nudge_minute_of_day = max(start_minute_of_day, end_minute_of_day - NUDGE_MINUTES_BEFORE_END)

        channel_id = db.get_guild_channel(reminder["guild_id"])
        channel = bot.get_channel(channel_id) if channel_id is not None else None

        # Catch-up: resolve a prior day's window that never got closed out (e.g. bot was offline at end time).
        if (
            reminder["last_start_date"] is not None
            and reminder["last_start_date"] != today_str
            and reminder["last_start_date"] != reminder["last_result_date"]
        ):
            streak = db.get_streak(reminder["id"])
            if streak is None or streak["last_checkin_date"] != reminder["last_start_date"]:
                db.reset_streak(reminder["id"])
                if channel is not None:
                    await channel.send(
                        f"💔 <@{reminder['user_id']}> missed the window for **{reminder['activity']}** "
                        f"({reminder['label']}) — streak reset."
                    )
            db.mark_reminder_resolved(reminder["id"], reminder["last_start_date"])

        if channel is None:
            continue

        if now_minute_of_day == start_minute_of_day and reminder["last_start_date"] != today_str:
            db.mark_reminder_started(reminder["id"], today_str)
            message = await channel.send(
                f"⏰ <@{reminder['user_id']}> time to **{reminder['activity']}** ({reminder['label']})! "
                f"React {CHECK_EMOJI} by **{reminder['end_hour']:02d}:{reminder['end_minute']:02d}** "
                f"or your streak resets."
            )
            await message.add_reaction(CHECK_EMOJI)
            db.add_pending_checkin(message.id, reminder["id"], today_str)
            continue

        if (
            now_minute_of_day == nudge_minute_of_day
            and reminder["last_start_date"] == today_str
            and reminder["last_nudge_date"] != today_str
        ):
            streak = db.get_streak(reminder["id"])
            if streak is None or streak["last_checkin_date"] != today_str:
                db.mark_reminder_nudged(reminder["id"], today_str)
                minutes_left = end_minute_of_day - now_minute_of_day
                message = await channel.send(
                    f"⚠️ <@{reminder['user_id']}> {minutes_left} minutes left to **{reminder['activity']}** "
                    f"({reminder['label']})! React {CHECK_EMOJI} once you've done it."
                )
                await message.add_reaction(CHECK_EMOJI)
                db.add_pending_checkin(message.id, reminder["id"], today_str)
            continue

        if (
            now_minute_of_day == end_minute_of_day
            and reminder["last_start_date"] == today_str
            and reminder["last_result_date"] != today_str
        ):
            streak = db.get_streak(reminder["id"])
            db.mark_reminder_resolved(reminder["id"], today_str)
            if streak is None or streak["last_checkin_date"] != today_str:
                db.reset_streak(reminder["id"])
                await channel.send(
                    f"💔 <@{reminder['user_id']}> missed the window for **{reminder['activity']}** "
                    f"({reminder['label']}) — streak reset."
                )


async def process_leaderboards():
    now_utc = datetime.now(dt_timezone.utc)
    for cfg in db.get_guilds_with_leaderboard_enabled():
        try:
            local_now = now_utc.astimezone(ZoneInfo(cfg["leaderboard_timezone"]))
        except Exception:
            log.warning("Bad leaderboard timezone %s for guild %s", cfg["leaderboard_timezone"], cfg["guild_id"])
            continue

        if local_now.hour != cfg["leaderboard_hour"] or local_now.minute != cfg["leaderboard_minute"]:
            continue

        today_str = local_now.date().isoformat()
        if cfg["leaderboard_last_posted_date"] == today_str:
            continue
        db.mark_leaderboard_posted(cfg["guild_id"], today_str)

        channel = bot.get_channel(cfg["channel_id"])
        if channel is None:
            continue
        rows = db.get_leaderboard(cfg["guild_id"])
        if not rows:
            continue

        guild = bot.get_guild(cfg["guild_id"])
        embed = await build_leaderboard_embed(guild, rows)
        message = await channel.send(embed=embed)
        try:
            await message.add_reaction("🎉")
            await message.add_reaction("👏")
        except discord.HTTPException:
            pass


async def scheduler_tick():
    await process_reminders()
    await process_leaderboards()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    if str(payload.emoji) != CHECK_EMOJI:
        return

    pending = db.get_pending_checkin(payload.message_id)
    if pending is None or payload.user_id != pending["user_id"]:
        return

    new_streak = db.record_checkin(pending["reminder_id"], pending["date"])
    if new_streak is None:
        return

    channel = bot.get_channel(payload.channel_id)
    if channel is not None:
        await channel.send(
            f"✅ <@{payload.user_id}> checked in on **{pending['label']}**! Streak: **{new_streak}** 🔥"
        )


@bot.event
async def on_ready():
    log.info("Logged in as %s", bot.user)
    if not scheduler.running:
        scheduler.add_job(scheduler_tick, "interval", seconds=60)
        scheduler.start()
    try:
        # Guild-scoped sync is instant (global sync can take up to an hour to reach clients).
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        # Wipe any stale global registrations from earlier runs (an old version of this bot did a
        # global sync) — without this, commands show up twice: once global, once guild-scoped.
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        log.info("Synced slash commands instantly to %d guild(s)", len(bot.guilds))
    except Exception:
        log.exception("Failed to sync slash commands")


@bot.event
async def on_guild_join(guild):
    try:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        log.info("Synced slash commands to newly joined guild %s", guild.id)
    except Exception:
        log.exception("Failed to sync slash commands to new guild %s", guild.id)


async def main():
    db.init_db()
    async with bot:
        await bot.load_extension("cogs.reminders")
        await bot.load_extension("cogs.leaderboard")
        await bot.load_extension("cogs.help")
        await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
