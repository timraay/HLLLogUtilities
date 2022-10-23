import discord
from discord import Interaction, app_commands
from discord.ext import commands, tasks
import random
from datetime import datetime, timedelta

from discord_utils import handle_error

class _events(commands.Cog):
    """A class with most events in it"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_status.start()

        @bot.tree.error
        async def on_interaction_error(interaction: Interaction, error: Exception):
            await handle_error(interaction, error)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        await handle_error(ctx, error)

    @tasks.loop(minutes=15.0)
    async def update_status(self):

        statuses = [
            {"type": "listening", "message": "meta discussions"},
            {"type": "watching", "message": "the latest dev brief"},
            {"type": "listening", "message": "The Recapping"},
            {"type": "watching", "message": "the finals for the 7th time"},
            {"type": "watching", "message": "everyone getting blown up by arty"},
            {"type": "playing", "message": "in Seasonal"},
            {"type": "listening", "message": "the community"},
            {"type": "playing", "message": "mind games"},
            {"type": "playing", "message": "with Alty's wheel"},
            {"type": "watching", "message": "rockets fly across the map"},
            {"type": "listening", "message": "the endless complaints"},
        ]
        status = random.choice(statuses)
        message = status["message"]
        activity = status["type"]
        if activity == "playing": activity = discord.ActivityType.playing
        elif activity == "streaming": activity = discord.ActivityType.streaming
        elif activity == "listening": activity = discord.ActivityType.listening
        elif activity == "watching": activity = discord.ActivityType.watching
        else: activity = discord.ActivityType.playing

        await self.bot.change_presence(activity=discord.Activity(name=message, type=activity))
    @update_status.before_loop
    async def before_status(self):
        await self.bot.wait_until_ready()



async def setup(bot):
    await bot.add_cog(_events(bot))