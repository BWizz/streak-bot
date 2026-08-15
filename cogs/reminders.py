from zoneinfo import available_timezones

import discord
from discord import app_commands
from discord.ext import commands

import db

TIME_FORMAT_HELP = "Use 24-hour HH:MM, e.g. 09:00 or 19:30."
DEFAULT_TIMEZONE = "America/New_York"
ACCESS_EMOJI = "🔓"

# Common abbreviations map to a real IANA zone so daylight saving is handled automatically
# (a bare "EST" would otherwise be wrong for half the year).
TIMEZONE_ALIASES = {
    "ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York",
    "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago",
    "MT": "America/Denver", "MST": "America/Denver", "MDT": "America/Denver",
    "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "AT": "America/Halifax", "AST": "America/Halifax", "ADT": "America/Halifax",
    "AKT": "America/Anchorage", "AKST": "America/Anchorage", "AKDT": "America/Anchorage",
    "HT": "Pacific/Honolulu", "HST": "Pacific/Honolulu",
    "UTC": "UTC", "GMT": "UTC",
}

TIMEZONE_HELP = "Common abbreviation (ET, CT, MT, PT, ...) or IANA name (e.g. America/New_York). Defaults to Eastern."


def resolve_timezone(raw):
    """Returns the IANA zone name for an abbreviation or IANA name, or None if unrecognized."""
    raw = raw.strip()
    alias = TIMEZONE_ALIASES.get(raw.upper())
    if alias:
        return alias
    if raw in available_timezones():
        return raw
    return None


def parse_time(time_str):
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    setup_group = app_commands.Group(name="setup", description="Admin setup for StreakBot")
    setup_leaderboard_group = app_commands.Group(
        name="leaderboard", description="Configure the daily automatic leaderboard post", parent=setup_group
    )
    remind_group = app_commands.Group(name="remind", description="Manage your accountability reminders")

    @setup_group.command(name="channel", description="Set the channel where reminders and check-ins are posted")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.set_guild_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"Reminders and check-ins will now be posted in {channel.mention}.", ephemeral=True
        )

    @setup_group.command(name="access", description="Post a banner that grants access to the reminders channel on reaction")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel to post the access banner in",
        message="Optional custom banner text (defaults to a message naming the reminders channel)",
    )
    async def setup_access(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str = None):
        reminder_channel_id = db.get_guild_channel(interaction.guild_id)
        if reminder_channel_id is None:
            await interaction.response.send_message(
                "Run /setup channel first so I know which channel to grant access to.", ephemeral=True
            )
            return

        reminder_channel = interaction.guild.get_channel(reminder_channel_id)
        banner_text = message or (
            f"React {ACCESS_EMOJI} below to get access to {reminder_channel.mention}. "
            f"Remove your reaction to leave it."
        )
        try:
            sent = await channel.send(banner_text)
            await sent.add_reaction(ACCESS_EMOJI)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"I don't have permission to post and react in {channel.mention}. "
                "Check that I have View Channel, Send Messages, and Add Reactions there.",
                ephemeral=True,
            )
            return
        db.set_access_banner(interaction.guild_id, sent.id)
        await interaction.response.send_message(
            f"Access banner posted in {channel.mention}. Any previous banner has stopped working.",
            ephemeral=True,
        )

    @setup_leaderboard_group.command(name="time", description="Turn on the daily leaderboard post and set when it fires")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        time=f"Time of day to post the leaderboard. {TIME_FORMAT_HELP}",
        timezone=f"{TIMEZONE_HELP}",
    )
    async def setup_leaderboard_time(self, interaction: discord.Interaction, time: str, timezone: str = None):
        if db.get_guild_channel(interaction.guild_id) is None:
            await interaction.response.send_message(
                "Run /setup channel first so I know where to post it.", ephemeral=True
            )
            return

        parsed = parse_time(time)
        if parsed is None:
            await interaction.response.send_message(
                f"Couldn't parse that time. {TIME_FORMAT_HELP}", ephemeral=True
            )
            return

        if timezone is None:
            timezone = DEFAULT_TIMEZONE
        else:
            resolved = resolve_timezone(timezone)
            if resolved is None:
                await interaction.response.send_message(
                    f"'{timezone}' isn't a recognized timezone. {TIMEZONE_HELP}", ephemeral=True
                )
                return
            timezone = resolved

        hour, minute = parsed
        db.set_leaderboard_schedule(interaction.guild_id, hour, minute, timezone)
        await interaction.response.send_message(
            f"Daily leaderboard will post at **{time} {timezone}**. Run /setup leaderboard off to disable it.",
            ephemeral=True,
        )

    @setup_leaderboard_group.command(name="off", description="Turn off the daily automatic leaderboard post")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_leaderboard_off(self, interaction: discord.Interaction):
        db.disable_leaderboard(interaction.guild_id)
        await interaction.response.send_message(
            "Daily leaderboard post turned off. /leaderboard still works anytime you run it manually.",
            ephemeral=True,
        )

    async def label_autocomplete(self, interaction: discord.Interaction, current: str):
        reminders = db.get_user_reminders(interaction.user.id, interaction.guild_id)
        return [
            app_commands.Choice(name=f"{r['label']} ({r['activity']})", value=r["label"])
            for r in reminders
            if current.lower() in r["label"].lower()
        ][:25]

    async def timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        current_upper = current.upper()
        seen_zones = set()
        choices = []
        for alias, zone in TIMEZONE_ALIASES.items():
            if zone in seen_zones or current_upper not in alias:
                continue
            seen_zones.add(zone)
            choices.append(app_commands.Choice(name=f"{alias} ({zone})", value=alias))
        return choices[:25]

    @remind_group.command(name="set", description="Sign up for (or update) a daily reminder")
    @app_commands.describe(
        label="Short name for this reminder, e.g. 'walk'. Reusing an existing label updates that reminder.",
        activity="What you want to be reminded to do, e.g. 'walk 10k steps'",
        start=f"When the reminder first posts, in your own timezone. {TIME_FORMAT_HELP}",
        end=f"Deadline to react ✅ by, same day as start. {TIME_FORMAT_HELP} You'll get a nudge 30 min before this.",
        timezone=f"{TIMEZONE_HELP} Only needed the first time — I'll remember it after that.",
    )
    @app_commands.autocomplete(label=label_autocomplete, timezone=timezone_autocomplete)
    async def remind_set(
        self,
        interaction: discord.Interaction,
        label: str,
        activity: str,
        start: str,
        end: str,
        timezone: str = None,
    ):
        if db.get_guild_channel(interaction.guild_id) is None:
            await interaction.response.send_message(
                "This server hasn't set a reminders channel yet. Ask an admin to run /setup channel first.",
                ephemeral=True,
            )
            return

        parsed_start = parse_time(start)
        parsed_end = parse_time(end)
        if parsed_start is None or parsed_end is None:
            await interaction.response.send_message(
                f"Couldn't parse start/end time. {TIME_FORMAT_HELP}", ephemeral=True
            )
            return

        start_hour, start_minute = parsed_start
        end_hour, end_minute = parsed_end
        if end_hour * 60 + end_minute <= start_hour * 60 + start_minute:
            await interaction.response.send_message(
                "End time must be later than start time, on the same day (overnight windows aren't supported yet).",
                ephemeral=True,
            )
            return

        if timezone is None:
            timezone = db.get_user_timezone(interaction.user.id) or DEFAULT_TIMEZONE
            db.set_user_timezone(interaction.user.id, timezone)
        else:
            resolved = resolve_timezone(timezone)
            if resolved is None:
                await interaction.response.send_message(
                    f"'{timezone}' isn't a recognized timezone. {TIMEZONE_HELP}",
                    ephemeral=True,
                )
                return
            timezone = resolved
            db.set_user_timezone(interaction.user.id, timezone)

        db.upsert_reminder(
            interaction.user.id, interaction.guild_id, label, activity,
            start_hour, start_minute, end_hour, end_minute, timezone,
        )
        await interaction.response.send_message(
            f"Got it — **{label}**: I'll remind you to **{activity}** starting at **{start} {timezone}**, "
            f"and your streak resets if you haven't reacted ✅ by **{end} {timezone}**.",
            ephemeral=True,
        )

    @remind_group.command(name="timezone", description="Update your saved default timezone for future reminders")
    @app_commands.describe(timezone=TIMEZONE_HELP)
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def remind_timezone(self, interaction: discord.Interaction, timezone: str):
        resolved = resolve_timezone(timezone)
        if resolved is None:
            await interaction.response.send_message(
                f"'{timezone}' isn't a recognized timezone. {TIMEZONE_HELP}",
                ephemeral=True,
            )
            return
        timezone = resolved

        db.set_user_timezone(interaction.user.id, timezone)
        await interaction.response.send_message(
            f"Default timezone saved as **{timezone}**. This is used whenever `/remind set` doesn't include one — "
            "existing reminders keep their own timezone unless you re-run /remind set for them.",
            ephemeral=True,
        )

    @remind_group.command(name="stop", description="Permanently delete one of your daily reminders")
    @app_commands.describe(label="Which reminder to delete")
    @app_commands.autocomplete(label=label_autocomplete)
    async def remind_stop(self, interaction: discord.Interaction, label: str):
        found = db.delete_reminder(interaction.user.id, interaction.guild_id, label)
        if not found:
            await interaction.response.send_message(
                f"You don't have a reminder called '{label}'. Check /remind status for your list.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"**{label}** deleted, including its streak. Run /remind set with that label anytime to start fresh.",
            ephemeral=True,
        )

    @remind_group.command(name="status", description="See all of your reminders and streaks")
    async def remind_status(self, interaction: discord.Interaction):
        reminders = db.get_user_reminders_with_streaks(interaction.user.id, interaction.guild_id)
        if not reminders:
            await interaction.response.send_message(
                "You don't have any reminders yet. Set one with /remind set.", ephemeral=True
            )
            return

        lines = []
        for r in reminders:
            lines.append(
                f"**{r['label']}** — {r['activity']} — "
                f"{r['start_hour']:02d}:{r['start_minute']:02d} to {r['end_hour']:02d}:{r['end_minute']:02d} {r['timezone']}\n"
                f"  Current streak: **{r['current_streak']}** 🔥  |  Longest: **{r['longest_streak']}**"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Reminders(bot))
