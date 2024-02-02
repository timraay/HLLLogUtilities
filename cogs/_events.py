import discord
from discord import Interaction
from discord.ext import commands, tasks

from discord_utils import handle_error, get_command_mention
from lib.session import SESSIONS
from lib.credentials import Credentials
from lib.hss.api_key import HSSApiKey

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

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        if guild.public_updates_channel and guild.public_updates_channel.permissions_for(guild.me).send_messages:
            channel = guild.public_updates_channel
        elif guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            channel = guild.system_channel
        else:
            return

        embed = discord.Embed(
            title="Thank you for adding me 👋",
            description=(
                "Let me quickly introduce myself, I am **HLL Log Utilities**, but you may call me **HLU** in short."
                " I can help you manage your Hell Let Loose events, by capturing and exporting logs, providing detailed"
                " statistics, and enforcing the rules if needed."
                "\n"
                "\nBefore you can let me loose, you need to set a couple of things up first. Don't worry, this will only take a few minutes!"
                "\n"
                f"\n1) **Add your server details** → {await get_command_mention(self.bot.tree, 'credentials', 'add')}"
                f"\n2) **Configure bot permissions** → [Click here](https://github.com/timraay/HLLLogUtilities/blob/main/FAQ.md#how-can-i-give-users-permission-to-use-the-bots-commands) (Optional)"
                f"\n3) **Enable automatic session creation** → {await get_command_mention(self.bot.tree, 'autosession')} (Optional)"
                "\n"
                "\nNow we're ready! Let's manually create a capture session."
                "\n"
                f"\n4) **Schedule a capture session** → {await get_command_mention(self.bot.tree, 'session', 'new')}"
                "\n"
                "\nAnd lastly, we can extract the logs and scores."
                "\n"
                f"\n5) **Export logs from a session** → {await get_command_mention(self.bot.tree, 'export', 'logs')}"
                f"\n6) **Export statistics of a session** → {await get_command_mention(self.bot.tree, 'export', 'logs')}"
                "\n"
                "\nThat's all there is to it! Some more useful links can be found below. Thanks for using HLU!"
                "\n"
                "\n⚙️ [Setting up automatic session scheduling](https://github.com/timraay/HLLLogUtilities#automatic-session-scheduling)"
                "\n⚙️ [Setting up custom rule enforcement](https://github.com/timraay/HLLLogUtilities#automatic-session-scheduling)"
                "\n⚙️ [Submitting logs to HeLO](https://helo-system.de/statistics/matches/report)"
                "\n"
                "\n🐛 [Support & bug reports](https://github.com/timraay/HLLLogUtilities/issues)"
                "\n📰 [Patch notes](https://github.com/timraay/HLLLogUtilities/releases)"
                "\n❓ [Frequently Asked Questions](https://github.com/timraay/HLLLogUtilities/blob/main/FAQ.md)"
                "\n☕ [Support me on Ko-fi](https://ko-fi.com/abusify)"
            ),
            color=discord.Colour(7722980)
        ).set_image(
            url="https://github.com/timraay/HLLLogUtilities/blob/main/assets/banner.png?raw=true"
        )

        await channel.send(embed=embed)
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        all_credentials = Credentials.in_guild(guild.id)
        for credentials in all_credentials:
            if credentials.autosession.enabled:
                credentials.autosession.logger.info("Disabling AutoSession since its credentials are being deleted")
                credentials.autosession.disable()
            
            for session in credentials.get_sessions():
                if session.active_in() is True:
                    session.logger.info("Stopping ongoing session since its credentials are being deleted")
                    await session.stop()
                
                session.logger.info("Deleting session since it's being removed from a guild")
                await session.delete()
            
            credentials.delete()
        
        all_api_keys = HSSApiKey.in_guild(guild.id)
        for api_key in all_api_keys:
            api_key.delete()

async def setup(bot):
    await bot.add_cog(_events(bot))