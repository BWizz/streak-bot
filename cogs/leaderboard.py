import discord
from discord import app_commands
from discord.ext import commands

import db


def streak_emoji(streak):
    if streak >= 30:
        return "🏆"
    if streak >= 14:
        return "💪"
    if streak >= 7:
        return "🔥"
    if streak >= 1:
        return "✨"
    return "💤"


async def resolve_display_name(guild, user_id):
    """Non-pinging display name for the leaderboard — falls back to a plain label if the member can't be found."""
    if guild is None:
        return f"User {user_id}"
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            return f"User {user_id}"
    return member.display_name


async def build_leaderboard_embed(guild, rows):
    lines = []
    for i, row in enumerate(rows, start=1):
        name = await resolve_display_name(guild, row["user_id"])
        emoji = streak_emoji(row["current_streak"])
        lines.append(
            f"**{i}.** {name} — {row['activity']} — {emoji} **{row['current_streak']}** day streak "
            f"(best: {row['longest_streak']})"
        )
    return discord.Embed(
        title="🏅 Streak Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Show the streak leaderboard for this server")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = db.get_leaderboard(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("No one has an active streak yet. Be the first with /remind set!")
            return

        embed = await build_leaderboard_embed(interaction.guild, rows)
        await interaction.response.send_message(embed=embed)
        try:
            sent = await interaction.original_response()
            await sent.add_reaction("🎉")
            await sent.add_reaction("👏")
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
