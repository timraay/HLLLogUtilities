import discord
from discord import app_commands, Interaction, ButtonStyle
from discord.ext import commands, tasks
from discord.utils import escape_markdown as esc_md
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse as dt_parse
from enum import Enum
from io import StringIO
from traceback import print_exc
from typing import Callable

from lib.session import DELETE_SESSION_AFTER, SESSIONS, HLLCaptureSession, get_sessions, assert_name
from lib.credentials import Credentials, credentials_in_guild_tll
from lib.converters import Converter, ExportFormats
from lib.storage import cursor
from lib.modifiers import ModifierFlags
from cogs.credentials import RCONCredentialsModal, SECURITY_URL
from discord_utils import CallableButton, CustomException, get_success_embed, only_once, View, ExpiredButtonError
from utils import get_config

MAX_SESSION_DURATION = timedelta(minutes=get_config().getint('Session', 'MaxDurationInMinutes'))

MODIFIERS_URL = "https://github.com/timraay/HLLLogUtilities/blob/main/README.md"

class SessionFilters(Enum):
    all = "all"
    scheduled = "scheduled"
    ongoing = "ongoing"
    finished = "finished"


async def autocomplete_credentials(interaction: Interaction, current: str):
    choices = [app_commands.Choice(name=str(credentials), value=credentials.id)
        for credentials in await credentials_in_guild_tll(interaction.guild_id) if current.lower() in str(credentials).lower()]
    choices.append(app_commands.Choice(name="Custom", value=0))
    return choices

async def autocomplete_end_time(_: Interaction, current: str):
    if current != "":
        return [
            app_commands.Choice(name=current, value=current)
        ]

    choices = list()
    candidates = (
        (0, 15),
        (0, 30),
        (1, 0),
        (1, 30),
        (1, 45),
        (2, 0),
        (2, 30),
        (3, 0),
        (4, 0),
        (5, 0),
        (6, 0),
        (7, 0),
        (8, 0),
    )
    for hrs, mins in candidates:
        if timedelta(hours=hrs, minutes=mins) > MAX_SESSION_DURATION:
            continue
        
        total_minutes = hrs*60 + mins
        value = f"{total_minutes} min"

        choices.append(app_commands.Choice(
            name=format('After {} minutes ({:02}:{:02}h)'.format(total_minutes, hrs, mins)),
            value=value)
        )

    return choices

async def autocomplete_sessions(interaction: Interaction, current: str):
    choices = [app_commands.Choice(name=str(session), value=session.id)
        for session in get_sessions(interaction.guild_id)
        if current.lower() in str(session).lower()]
    return choices

async def autocomplete_active_sessions(interaction: Interaction, current: str):
    choices = [app_commands.Choice(name=str(session), value=session.id)
        for session in get_sessions(interaction.guild_id)
        if session.active_in() and current.lower() in str(session).lower()]
    return choices


class SessionCreateView(View):
    def __init__(self, name: str, guild: discord.Guild, credentials: Credentials, start_time: datetime, end_time: datetime, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.add_item(CallableButton(self.on_confirm, label="Confirm", style=ButtonStyle.green))
        self.add_item(CallableButton(self.select_modifiers, label="Modifiers...", style=ButtonStyle.gray))

        self.name = assert_name(name)
        self.guild = guild
        self.credentials = credentials
        self.start_time = start_time
        self.end_time = end_time

        self.modifiers = ModifierFlags()
        self._message = None
        self.__created = False
    
    @property
    def duration(self):
        return self.end_time - self.start_time
    @property
    def total_minutes(self):
        return int(self.duration.total_seconds() / 60 + 0.5)

    async def send(self, interaction: discord.Interaction):
        embed = self.get_embed()
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        self._message = await interaction.original_response()

    def get_embed(self):
        if self.guild.icon is not None:
            icon_url = self.guild.icon.url
        else:
            icon_url = None
        
        embed = discord.Embed(
            title="Scheduling a new session...",
            description="Please verify that all the information is correct. This cannot be changed later.",
            colour=discord.Colour(16746296)
        ).set_author(
            name=f"{self.credentials.name} - {self.credentials.address}:{self.credentials.port}" if self.credentials else "Custom server",
            icon_url=icon_url
        ).add_field(
            name="From",
            value=f"<t:{int(self.start_time.timestamp())}:f>\n:watch: <t:{int(self.start_time.timestamp())}:R>"
        ).add_field(
            name="To",
            value=f"<t:{int(self.end_time.timestamp())}:f>\n:calling: {self.total_minutes} minutes later"
        )

        if self.modifiers:
            embed.add_field(name=f"Active Modifiers ({len(self.modifiers)})", value="\n".join([
                f"{m.config.emoji} [**{m.config.name}**]({MODIFIERS_URL}#{m.config.name.lower().replace(' ', '-')}) - {m.config.description}"
                for m in self.modifiers.get_modifier_types()
            ]), inline=False)

        return embed

    async def on_confirm(self, interaction: Interaction):
        if not self.credentials:

            async def on_form_request(interaction: Interaction):
                modal = RCONCredentialsModal(on_form_submit, title="RCON Credentials Form")
                await interaction.response.send_modal(modal)

            async def on_form_submit(_interaction: Interaction, name: str, address: str, port: int, password: str):
                self.credentials = Credentials.create_temporary(interaction.guild_id, name=name, address=address, port=port, password=password)

                @only_once
                async def on_save_accept(interaction: Interaction):
                    try:
                        self.credentials.insert_in_db()
                    except TypeError:
                        raise CustomException("Credentials have already been saved!")

                    await msg1.delete()
                    await msg2.delete()
                    await self.create_session(interaction)

                @only_once
                async def on_save_decline(interaction: Interaction):
                    await msg1.delete()
                    await msg2.delete()
                    await self.create_session(interaction)

                embed = discord.Embed(
                    title="Do you want me to save these credentials?",
                    description=f"That way you don't have to type 'em in every time, and can I recover your session in case of a restart.",
                    url=SECURITY_URL
                )

                view = View(timeout=300)
                view.add_item(CallableButton(on_save_accept, label="Save", style=ButtonStyle.blurple))
                view.add_item(CallableButton(on_save_decline, label="Decline", style=ButtonStyle.gray))

                msg2 = await _interaction.followup.send(embed=embed, view=view, ephemeral=True, wait=True)

            embed = discord.Embed(
                description=f"**Important notice!**\nIn order to retrieve logs, RCON access to your server is needed! You shouldn't hand your credentials to any sources you don't trust however. See [what was done to make sharing your password with me as safe as possible :bust_in_silhouette:]({SECURITY_URL}).\n\nPressing the below button will open a form where you can enter the needed information."
            )
            view = View(timeout=600)
            view.add_item(CallableButton(on_form_request, label="Open form", emoji="📝", style=ButtonStyle.gray))
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            msg1 = await interaction.original_response()

        else:
            await self.create_session(interaction)
        
    async def create_session(self, interaction: discord.Interaction):
        if self.__created:
            raise ExpiredButtonError

        embed = discord.Embed(
            title="Log capture session scheduled!",
            description="\n".join([
                f"**{esc_md(self.name)}**",
                f"🕓 <t:{int(self.start_time.timestamp())}:f> - <t:{int(self.end_time.timestamp())}:t>",
                f"🚩 Server: `{self.credentials.name}`"
            ]),
            timestamp=datetime.now(tz=timezone.utc),
            colour=discord.Colour(16746296)
        ).set_footer(
            text=str(interaction.user),
            icon_url=interaction.user.avatar.url
        )

        HLLCaptureSession.create_in_db(
            guild_id=self.guild.id,
            name=self.name,
            start_time=self.start_time,
            end_time=self.end_time,
            credentials=self.credentials,
            modifiers=self.modifiers,
        )
        self.__created == True

        if interaction.channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.channel.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

        if self._message:
            await self._message.delete()
        else:
            await interaction.response.defer()

    async def select_modifiers(self, interaction: Interaction):
        view = SessionModifierView(self._message, self.updated_modifiers, flags=self.modifiers)
        await interaction.response.edit_message(content="Select all of the modifiers you want to enable by clicking on the buttons below", view=view, embed=None)
    
    async def updated_modifiers(self, interaction: discord.Interaction, modifiers: ModifierFlags):
        self.modifiers = modifiers
        await interaction.response.edit_message(content=None, view=self, embed=self.get_embed())


class SessionModifierView(View):
    def __init__(self, message: discord.InteractionMessage, callback: Callable, flags: ModifierFlags = None, timeout: float = 300.0, **kwargs):
        super().__init__(timeout=timeout, **kwargs)
        self.message = message
        self._callback = callback
        self.flags = flags or ModifierFlags()
        self.update_self()
    
    options = []
    for m_id, _ in ModifierFlags():
        flag = ModifierFlags(**{m_id: True})
        m = next(flag.get_modifier_types())
        options.append((m.config.name, m.config.emoji, flag))
    
    async def toggle_value(self, interaction: Interaction, flags: ModifierFlags, enable: bool):
        if enable:
            self.flags |= flags
        else:
            self.flags ^= (self.flags & flags)
        
        await self.message.edit(view=self.update_self())
        await interaction.response.defer()

    def update_self(self):
        self.clear_items()
        for (name, emoji, flags) in self.options:
            enabled = (flags <= self.flags) # Subset of
            style = ButtonStyle.green if enabled else ButtonStyle.red
            self.add_item(CallableButton(self.toggle_value, flags, not enabled, label=name, emoji=emoji, style=style))
        self.add_item(CallableButton(self.callback, label="Back...", style=ButtonStyle.gray))

        return self
    
    async def callback(self, interaction: Interaction):
        return await self._callback(interaction, self.flags)


class sessions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    SessionGroup = app_commands.Group(
        name="session",
        description="Manage log records",
        default_permissions=discord.Permissions(0)
    )

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize all sessions"""
        cursor.execute("SELECT ROWID FROM sessions WHERE deleted = 0")
        for (id_,) in cursor.fetchall():
            if id_ not in SESSIONS:
                try:
                    HLLCaptureSession.load_from_db(id_)
                except:
                    print('Failed to load session', id_)
                    print_exc()

        if not self.session_manager.is_running():
            self.session_manager.start()

    @tasks.loop(minutes=5)
    async def session_manager(self):
        """Clean up expired sessions"""
        for sess in tuple(SESSIONS.values()):
            if sess.should_delete():
                sess.delete()

    @SessionGroup.command(name="new", description="Start recording server logs at specified time")
    @app_commands.describe(
        name="A name to later identify your session with",
        start_time="The time when to start recording, in UTC. Can be \"now\" as well.",
        end_time="The time when to stop recording, in UTC.",
        server="The HLL server to record logs from"
    )
    @app_commands.autocomplete(
        server=autocomplete_credentials,
        end_time=autocomplete_end_time
    )
    async def create_new_session(self, interaction: Interaction, name: str, start_time: str, end_time: str, server: int):
        try:
            if start_time.lower() == 'now':
                start_time = datetime.now(tz=timezone.utc)
            else:
                start_time = dt_parse(start_time, fuzzy=True, dayfirst=True)
        except:
            raise CustomException(
                "Couldn't interpret start time!",
                "A few examples of what works:\n• `1/10/42 18:30`\n• `January 10 2042 6:30pm`\n• `6:30pm, 10th day of Jan, 2042`\n• `Now`"
            )

        if end_time.lower().endswith(" min"):
            try:
                stripped_num = end_time.lower().rsplit(" min", 1)[0].strip()
                minutes = int(stripped_num) # Raises ValueError if invalid

                if minutes <= 0:
                    raise ValueError('Time is not greater than 0 minutes')
                
                duration = timedelta(minutes=minutes)
                end_time = start_time + duration

            except ValueError:
                raise CustomException(
                    "Couldn't interpret end time!",
                    f"Format must be `X min`, with `X` being a whole, positive number in minutes, not `{stripped_num}`"
                )
        else:
            try:
                end_time = dt_parse(end_time, fuzzy=True, dayfirst=True)
            except:
                raise CustomException(
                    "Couldn't interpret end time!",
                    "A few examples of what works:\n• `1/10/42 20:30`\n• `January 10 2042 8:30pm`\n• `8:30pm, 10th day of Jan, 2042`\n• `Now`"
                )

        start_time = start_time.replace(microsecond=0, tzinfo=start_time.tzinfo or timezone.utc)
        end_time = end_time.replace(microsecond=0, tzinfo=end_time.tzinfo or timezone.utc)

        if server:
            credentials = Credentials.load_from_db(server)
        else:
            credentials = None

        if datetime.now(tz=timezone.utc) > end_time:
            raise CustomException(
                "Invalid end time!",
                f"It can't be past the end time yet.\n\n• Current time: `{datetime.now(tz=timezone.utc).replace(microsecond=0)}`\n• End time: `{end_time}`"
            )
        if start_time > end_time:
            raise CustomException(
                "Invalid dates provided!",
                f"The start time can't be later than the end time.\n\n• Start time: `{start_time}`\n• End time: `{end_time}`"
            )

        diff = end_time - start_time
        minutes = int(diff.total_seconds() / 60 + 0.5)
        if diff > MAX_SESSION_DURATION:
            max_minutes = int(MAX_SESSION_DURATION.total_seconds() / 60 + 0.5)
            raise CustomException(
                "Invalid dates provided!",
                f"The duration of the session exceeds the upper limit of {max_minutes} minutes.\n\n• Start time: `{start_time}`\n• End time: `{end_time}`\n• Duration: {minutes} minutes"
            )

        view = SessionCreateView(
            name=name,
            guild=interaction.guild,
            credentials=credentials,
            start_time=start_time,
            end_time=end_time
        )
        await view.send(interaction)

    @SessionGroup.command(name="list", description="View all available sessions")
    @app_commands.describe(
        filter="Filter shown session by their state"
    )
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
    @app_commands.describe(
        session="An ongoing log capture session"
    )
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
            await _interaction.response.edit_message(embed=get_success_embed(
                f"Stopped \"{session.name}\"!"
            ))

        embed = discord.Embed(
            title="Are you sure you want to stop this session?",
            description="This will end the session, which cannot be reverted. Logs up until this point will still be available for download."
        )

        view = View()
        view.add_item(CallableButton(on_confirm, label="Confirm", style=ButtonStyle.gray))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @SessionGroup.command(name="delete", description="Delete a session and its records")
    @app_commands.describe(
        session="A log capture session"
    )
    @app_commands.autocomplete(
        session=autocomplete_sessions
    )
    async def delete_session(self, interaction: Interaction, session: int):
        session: HLLCaptureSession = SESSIONS[session]

        @only_once
        async def on_confirm(_interaction: Interaction):
            session.delete()
            await _interaction.response.edit_message(embed=get_success_embed(
                f"Deleted \"{session.name}\"!"
            ))

        embed = discord.Embed(
            title="Are you sure you want to delete this session?",
            description="This will also remove all the associated records. This cannot be reverted."
        )

        view = View()
        view.add_item(CallableButton(on_confirm, label="Confirm", style=ButtonStyle.gray))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


    @SessionGroup.command(name="logs", description="DEPRECATED: Use the /export command instead")
    @app_commands.describe(
        session="A log capture session",
        format="The format the logs should be exported in"
    )
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
            content=f"Logs for **{esc_md(session.name)}**\n> *NOTE: This command has been deprecated and will be removed in the future. Use the `/export` command instead.*",
            file=file
        )


async def setup(bot):
    await bot.add_cog(sessions(bot))
