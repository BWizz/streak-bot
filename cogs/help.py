import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Explain what StreakBot does and how to use it")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📌 StreakBot",
            description=(
                "Daily accountability reminders with streaks, built for keeping each other honest.\n\n"
                "Sign up for something you want to do every day, in a time window you choose. "
                "The bot reminds you when it opens, nudges you if you're cutting it close, and resets "
                "your streak if you miss the deadline — visible to the whole server."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Getting started",
            value=(
                "**Admin, once:** `/setup channel` — pick where reminders and check-ins get posted.\n"
                "**Everyone:** `/remind set` — sign up for a reminder."
            ),
            inline=False,
        )
        embed.add_field(
            name="/remind set",
            value=(
                "`label` — short name for this reminder, e.g. `walk`. Reusing a label edits that reminder "
                "instead of creating a new one — you can have as many labels as you want, each its own streak.\n"
                "`activity` — what you're being reminded to do, e.g. `walk 10k steps`.\n"
                "`start` / `end` — the window, same day, 24-hour `HH:MM`. The reminder posts at `start`; "
                "you have until `end` to react ✅ or the streak resets. A nudge goes out 30 min before `end` "
                "if you haven't checked in yet.\n"
                "`timezone` — optional, e.g. `ET`, `MT`, `America/Chicago`. Defaults to Eastern, and is "
                "remembered after the first time you set it.\n"
                "`days` — optional, e.g. `daily` (default), `weekdays`, `weekends`, or `Mon,Wed,Fri`. "
                "Skipped days don't post a reminder and don't touch your streak either way."
            ),
            inline=False,
        )
        embed.add_field(
            name="Other commands",
            value=(
                "`/remind status` — list all your reminders and streaks.\n"
                "`/remind stop label:<name>` — permanently delete one reminder, streak included.\n"
                "`/remind timezone` — update your saved default timezone.\n"
                "`/remind days label:<name> days:<...>` — change which days one reminder triggers on.\n"
                "`/leaderboard` — see everyone's current and best streaks (no pings).\n"
                "`/setup leaderboard time` *(admin)* — post the leaderboard automatically once a day.\n"
                "`/setup leaderboard off` *(admin)* — turn that automatic post back off."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
