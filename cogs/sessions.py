import discord
from discord import app_commands, ui, Interaction
from discord.ext import commands, tasks
from discord.utils import escape_markdown as esc_md
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse as dt_parse
from enum import Enum
from io import StringIO

from lib.session import DELETE_SESSION_AFTER, SESSIONS, HLLCaptureSession, get_sessions
from lib.credentials import Credentials, credentials_in_guild_tll
from lib.converters import Converter, ExportFormats
from lib.storage import cursor
from cogs.credentials import RCONCredentialsModal, SECURITY_URL
from discord_utils import CallableButton, CustomException, get_success_embed, only_once, View
from utils import get_config

MAX_SESSION_DURATION = timedelta(minutes=get_config().getint('Session', 'MaxDurationInMinutes'))

class SessionFilters(Enum):
    all = "all"
    scheduled = "scheduled"
    ongoing = "ongoing"
    finished = "finished"

class sessions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    SessionGroup = app_commands.Group(name="session", description="Manage log records")

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
        choices = [app_commands.Choice(name=str(credentials), value=credentials.id)
            for credentials in await credentials_in_guild_tll(interaction.guild_id) if current.lower() in str(credentials).lower()]
        choices.append(app_commands.Choice(name="Custom", value=0))
        return choices
    
    async def autocomplete_sessions(self, interaction: Interaction, current: str):
        choices = [app_commands.Choice(name=str(session), value=session.id)
            for session in get_sessions(interaction.guild_id)
            if current.lower() in str(session).lower()]
        return choices
    async def autocomplete_active_sessions(self, interaction: Interaction, current: str):
        choices = [app_commands.Choice(name=str(session), value=session.id)
            for session in get_sessions(interaction.guild_id)
            if session.active_in() and current.lower() in str(session).lower()]
        return choices

    @SessionGroup.command(name="new", description="Start recording server logs at specified time")
    @app_commands.autocomplete(
        server=autocomplete_credentials
    )
    async def create_new_session(self, interaction: Interaction, name: str, start_time: str, end_time: str, server: int):
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

        if datetime.now(tz=timezone.utc) > end_time:
            raise CustomException("Invalid end time!", "It can't be past the end time yet.")
        if start_time > end_time:
            raise CustomException("Invalid dates provided!", "The start time can't be later than the end time.")
        
        diff = end_time - start_time
        minutes = int(diff.total_seconds() / 60 + 0.5)
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
            value=f"<t:{int(end_time.timestamp())}:f>\n:calling: {minutes} minutes later"
        )

        @only_once
        async def on_confirm(_interaction: Interaction):
            if not credentials:
                embed = discord.Embed(
                    description=f"**Important notice!**\nIn order to retrieve logs, RCON access to your server is needed! You shouldn't hand your credentials to any sources you don't trust however. See [what was done to make sharing your password with me as safe as possible :bust_in_silhouette:]({SECURITY_URL}).\n\nPressing the below button will open a form where you can enter the needed information."
                )
                view = View(timeout=600)
                view.add_item(CallableButton(on_form_request, label="Open form", emoji="📝", style=discord.ButtonStyle.gray))
                await _interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
            else:
                await create_session(_interaction, credentials)
        
        async def on_form_request(_interaction: Interaction):
            modal = RCONCredentialsModal(on_form_submit, title="RCON Credentials Form")
            await _interaction.response.send_modal(modal)

        @only_once
        async def on_form_submit(_interaction: Interaction, name: str, address: str, port: int, password: str):
            credentials = Credentials.create_temporary(_interaction.guild_id, name=name, address=address, port=port, password=password)

            @only_once
            async def on_save_accept(_interaction: Interaction):
                try:
                    credentials.insert_in_db()
                except TypeError:
                    raise CustomException("Credentials have already been saved!")
                
                await create_session(_interaction, credentials)
            
            @only_once
            async def on_save_decline(_interaction: Interaction):
                await create_session(_interaction, credentials)

            embed = discord.Embed(
                title="Do you want me to save these credentials?",
                description=f"That way you don't have to type 'em in every time, and can I recover your session in case of a restart.",
                url=SECURITY_URL
            )

            view = View(timeout=300)
            view.add_item(CallableButton(on_save_accept, label="Save", style=discord.ButtonStyle.blurple))
            view.add_item(CallableButton(on_save_decline, label="Decline", style=discord.ButtonStyle.gray))

            await _interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        @only_once
        async def create_session(_interaction: Interaction, credentials: Credentials):
            embed = discord.Embed(
                title="Log capture session scheduled!",
                description="\n".join([
                    f"**{esc_md(name)}**",
                    f"🕓 <t:{int(start_time.timestamp())}:f> - <t:{int(end_time.timestamp())}:t>",
                    f"🚩 Server: `{credentials.name}`"
                ]),
                timestamp=datetime.now(tz=timezone.utc),
                colour=discord.Colour(16746296)
            ).set_footer(
                text=str(interaction.user),
                icon_url=interaction.user.avatar.url
            )

            HLLCaptureSession.create_in_db(
                guild_id=interaction.guild_id,
                name=name,
                start_time=start_time,
                end_time=end_time,
                credentials=credentials
            )

            await _interaction.response.send_message(embed=embed)

        view = View(timeout=300)
        view.add_item(CallableButton(on_confirm, label="Confirm", style=discord.ButtonStyle.green))
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @SessionGroup.command(name="list", description="View all available sessions")
    async def list_all_sessions(self, interaction: Interaction, filter: SessionFilters = SessionFilters.all):
        all_sessions = get_sessions(interaction.guild_id)
        count = 0
        description = ""

        if filter == SessionFilters.all or filter == SessionFilters.scheduled:
            sessions = [session for session in all_sessions if isinstance(session.active_in(), timedelta)]
            count += len(sessions)
            if sessions:
                description += "\n\n📅 **Scheduled records**"
                for session in sessions:
                    description += f"\n> • {esc_md(session.name)} (Starts <t:{int(session.start_time.timestamp())}:R>)\n> ⤷ <t:{int(session.start_time.timestamp())}:f> > <t:{int(session.end_time.timestamp())}:t> ({int(session.duration.total_seconds() // 60)} min.)"

        if filter == SessionFilters.all or filter == SessionFilters.ongoing:
            sessions = [session for session in all_sessions if session.active_in() is True]
            count += len(sessions)
            if sessions:
                description += "\n\n🎦 **Currently recording**"
                for session in sessions:
                    description += f"\n> • {esc_md(session.name)} (Ends <t:{int(session.end_time.timestamp())}:R>)\n> ⤷ <t:{int(session.start_time.timestamp())}:f> > <t:{int(session.end_time.timestamp())}:t> ({int(session.duration.total_seconds() // 60)} min.)"

        if filter == SessionFilters.all or filter == SessionFilters.finished:
            sessions = [session for session in all_sessions if session.active_in() is False]
            count += len(sessions)
            if sessions:
                description += "\n\n✅ **Finished records**"
                for session in sessions:
                    description += f"\n> • {esc_md(session.name)} (<t:{int(session.end_time.timestamp())}:R>) **[🗑️ <t:{int((session.end_time + DELETE_SESSION_AFTER).timestamp())}:R>]**\n> ⤷ <t:{int(session.start_time.timestamp())}:f> > <t:{int(session.end_time.timestamp())}:t> ({int(session.duration.total_seconds() // 60)} min.)"

        embed = discord.Embed(
            title=f"There are {count} {'total' if filter == SessionFilters.all else filter.value} sessions",
            description=description or "Sessions can be created with the `/session new` command."
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @SessionGroup.command(name="stop", description="Stop a session pre-emptively")
    @app_commands.autocomplete(
        session=autocomplete_active_sessions
    )
    async def stop_active_session(self, interaction: Interaction, session: int):
        session: HLLCaptureSession = SESSIONS[session]
        if not session.active_in():
            raise CustomException(
                "Invalid session!",
                "Session has already ended and no longer needs to be stopped."
            )
        
        @only_once
        async def on_confirm(_interaction: Interaction):
            await session.stop()
            await _interaction.response.send_message(embed=get_success_embed(
                f"Stopped \"{session.name}\"!"
            ), ephemeral=True)

        embed = discord.Embed(
            title="Are you sure you want to stop this session?",
            description="This will end the session, which cannot be reverted. Logs up until this point will still be available for download."
        )

        view = View()
        view.add_item(CallableButton(on_confirm, label="Confirm", style=discord.ButtonStyle.gray))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @SessionGroup.command(name="delete", description="Delete a session and its records")
    @app_commands.autocomplete(
        session=autocomplete_sessions
    )
    async def delete_session(self, interaction: Interaction, session: int):
        session: HLLCaptureSession = SESSIONS[session]

        @only_once
        async def on_confirm(_interaction: Interaction):
            session.delete()
            await _interaction.response.send_message(embed=get_success_embed(
                f"Deleted \"{session.name}\"!"
            ), ephemeral=True)
        
        embed = discord.Embed(
            title="Are you sure you want to delete this session?",
            description="This will also remove all the associated records. This cannot be reverted."
        )

        view = View()
        view.add_item(CallableButton(on_confirm, label="Confirm", style=discord.ButtonStyle.gray))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


    @app_commands.command(name="getlogs", description="Download logs from a session")
    @app_commands.autocomplete(
        session=autocomplete_sessions
    )
    async def get_logs_from_session(self, interaction: Interaction, session: int, format: ExportFormats = ExportFormats.text):
        session: HLLCaptureSession = SESSIONS[session]
        converter: Converter = format.value

        logs = session.get_logs()
        fp = StringIO(converter.convert_many(logs))
        file = discord.File(fp, filename=session.name + '.' + converter.ext())
        
        await interaction.response.send_message(
            content=f"Logs for **{esc_md(session.name)}**",
            file=file
        )


async def setup(bot):
    await bot.add_cog(sessions(bot))