import discord
from discord import Interaction
from discord.ext import commands, tasks

from discord_utils import handle_error
from lib.session import SESSIONS

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

    @tasks.loop(minutes=5.0)
    async def update_status(self):
        await self.bot.change_presence(activity=discord.Activity(name=f"over {len(SESSIONS)} sessions", type=discord.ActivityType.watching))
    @update_status.before_loop
    async def before_status(self):
        await self.bot.wait_until_ready()



async def setup(bot):
    await bot.add_cog(_events(bot))