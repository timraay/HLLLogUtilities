import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, Interaction
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse as dt_parse

from lib.session import SESSIONS, HLLCaptureSession
from lib.credentials import Credentials, credentials_in_guild_tll
from lib.storage import cursor
from cogs._events import CustomException
from discord_utils import CallableButton
from utils import get_config

MAX_SESSION_DURATION = timedelta(minutes=get_config().getint('Session', 'MaxDurationInMinutes'))

class sessions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize all sessions"""
        cursor.execute("SELECT ROWID FROM sessions WHERE deleted = 0")
        for (id_,) in cursor.fetchall():
            HLLCaptureSession.load_from_db(id_)

    @tasks.loop(minutes=5)
    async def session_manager(self):
        """Clean up expired sessions"""
        for sess in tuple(SESSIONS.values()):
            if sess.should_delete():
                sess.delete()
    
    async def autocomplete_credentials(self, interaction: Interaction, current: str):
        choices = [app_commands.Choice(name=f"{credentials.address}:{credentials.port} - {credentials.name}", value=credentials.id)
            for credentials in await credentials_in_guild_tll(interaction.guild_id)]
        choices.append(app_commands.Choice(name="Custom", value=0))
        return choices

    @app_commands.command(name="record", description="Start recording server logs at specified time")
    @app_commands.default_permissions(administrator=True)
    @app_commands.autocomplete(
        server=autocomplete_credentials
    )
    async def create_new_session(self, interaction: Interaction, start_time: str, end_time: str, server: int):
        try:
            if start_time.lower() == 'now':
                start_time = datetime.now(tz=timezone.utc)
            else:
                start_time = dt_parse(start_time, fuzzy=True, dayfirst=True)
        except:
            raise CustomException("Couldn't interpret start time!", "A few examples of what works:\n• `1/10/42 18:30`\n• `January 10 2042 6:30pm`\n• `6:30pm, 10th day of Jan, 2042`\n• `Now`")
        
        try:
            end_time = dt_parse(end_time, fuzzy=True, dayfirst=True)
        except:
            raise CustomException("Couldn't interpret end time!", "A few examples of what works:\n• `1/10/42 20:30`\n• `January 10 2042 8:30pm`\n• `8:30pm, 10th day of Jan, 2042`\n• `Now`")

        start_time = start_time.replace(tzinfo=start_time.tzinfo or timezone.utc)
        end_time = end_time.replace(tzinfo=end_time.tzinfo or timezone.utc)
        
        if server:
            credentials = Credentials.load_from_db(server)
        else:
            credentials = None

        if end_time > datetime.now(tz=timezone.utc):
            raise CustomException("Invalid end time!", "It can't be past the end time yet.")
        if start_time > end_time:
            raise CustomException("Invalid dates provided!", "The start time can't be later than the end time.")
        
        diff = end_time - start_time
        minutes = int(MAX_SESSION_DURATION.total_seconds() / 60 + 0.5)
        if diff.total_seconds() > MAX_SESSION_DURATION.total_seconds():
            raise CustomException("Invalid dates provided!", f"The duration of the session exceeds the upper limit of {minutes} minutes.")

        embed = discord.Embed(
            title="Scheduling a new session...",
            description="Please verify that all the information is correct. This can not be changed later.",
            colour=discord.Colour(16746296)
        ).set_author(
            name=f"{credentials.name} - {credentials.address}:{credentials.port}" if credentials else "Custom server",
            icon_url=interaction.guild.icon.url
        ).add_field(
            name="From",
            value=f"<t:{int(start_time.timestamp())}:f>\n:watch: <t:{int(start_time.timestamp())}:R>"
        ).add_field(
            name="To",
            value=f"<t:{int(end_time.timestamp())}:f>\n:calling: **{minutes} minutes later**"
        )

        # TODO: Make sure button can't be spammed
        async def on_confirm(_interaction: Interaction):
            if not credentials:
                modal = ui.Modal(title="Server credentials")


        view = ui.View(timeout=300)
        view.add_item(CallableButton(on_confirm, label="Confirm", style=discord.ButtonStyle.green))
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        