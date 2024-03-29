import discord
from discord import app_commands, Interaction, ButtonStyle
from discord.ext import commands, tasks
from discord.utils import escape_markdown as esc_md
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse as dt_parse
from enum import Enum
from traceback import print_exc
from typing import Union, Optional, Literal

from lib.session import DELETE_SESSION_AFTER, SESSIONS, HLLCaptureSession, get_sessions
from lib.credentials import Credentials, CREDENTIALS
from lib.storage import cursor
from lib.modifiers import ModifierFlags
from cogs.credentials import RCONCredentialsModal, SessionModifierView, SECURITY_URL, MODIFIERS_URL, autocomplete_credentials
from discord_utils import CallableButton, CustomException, get_success_embed, get_question_embed, only_once, View, ExpiredButtonError, get_command_mention
from utils import get_config

MAX_SESSION_DURATION = timedelta(minutes=get_config().getint('Session', 'MaxDurationInMinutes'))

class SessionFilters(Enum):
    all = "all"
    scheduled = "scheduled"
    ongoing = "ongoing"
    finished = "finished"


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
    def __init__(self, name: str, guild: discord.Guild, credentials: Union[Credentials, Literal[False], None], start_time: datetime, end_time: datetime, session: 'HLLCaptureSession' = None, timeout: float = 180):
        super().__init__(timeout=timeout)

        self.name = name
        self.guild = guild
        self.credentials = credentials
        self.start_time = start_time
        self.end_time = end_time

        self.session = session
        self.do_edit = bool(self.session)
        
        if self.do_edit:
            self.modifiers = self.session.modifier_flags.copy()
        elif self.credentials:
            self.modifiers = self.credentials.default_modifiers.copy()
        else:
            self.modifiers = ModifierFlags()

        self._message = None
        self.__created = False

        if not self.do_edit and self.credentials is None:
            raise TypeError("When creating a session, credentials must either be False or Credentials, not None")

        self.add_item(CallableButton(self.on_confirm, label="Confirm", style=ButtonStyle.green))
        self.add_item(CallableButton(self.select_modifiers, label="Modifiers...", style=ButtonStyle.gray))
    
    @property
    def duration(self):
        return self.end_time - self.start_time
    @property
    def total_minutes(self):
        return int(self.duration.total_seconds() / 60 + 0.5)

    async def send(self, interaction: discord.Interaction, modifiers_first: bool = False):
        if modifiers_first:
            view = SessionModifierView(None, self.updated_modifiers, flags=self.modifiers)
            await interaction.response.send_message(content="Select all of the modifiers you want to enable by clicking on the buttons below", view=view, ephemeral=True)
            self._message = await interaction.original_response()
            view.message = self._message
        else:
            embed = self.get_embed()
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
            self._message = await interaction.original_response()

    @property
    def embed_color(self):
        if self.do_edit:
            return discord.Colour(3458795)
        else:
            return discord.Colour(16746296)

    def get_embed(self):
        if self.guild.icon is not None:
            icon_url = self.guild.icon.url
        else:
            icon_url = None

        if self.credentials:
            server_name = f"{self.credentials.name} - {self.credentials.address}:{self.credentials.port}"
        elif self.credentials is False:
            server_name = "Custom server"
        elif self.do_edit and self.session.credentials:
            server_name = f"{self.session.credentials.name} - {self.session.credentials.address}:{self.session.credentials.port}"
        else:
            server_name = "Unknown server ⚠️"
        
        embed = discord.Embed(
            title="Editing the session..." if self.do_edit else "Scheduling a new session...",
            description="Please verify that all the information is correct.",
            colour=self.embed_color
        ).set_author(
            name=server_name,
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
        if self.credentials is False:

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
                    if self.do_edit:
                        await self.edit_session(interaction)
                    else:
                        await self.create_session(interaction)

                @only_once
                async def on_save_decline(interaction: Interaction):
                    await msg1.delete()
                    await msg2.delete()
                    if self.do_edit:
                        await self.edit_session(interaction)
                    else:
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
            if self.do_edit:
                await self.edit_session(interaction)
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
            colour=self.embed_color
        ).set_footer(
            text=str(interaction.user),
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None
        )

        if self.modifiers:
            embed.description += f"\n🧮 Modifiers: " + ", ".join([
                f"[{m.config.name}]({MODIFIERS_URL}#{m.config.name.lower().replace(' ', '-')})"
                for m in self.modifiers.get_modifier_types()
            ])

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
        elif not interaction.response.is_done():
            await interaction.response.defer()

    async def edit_session(self, interaction: discord.Interaction):
        if self.__created:
            raise ExpiredButtonError
        
        credentials = self.credentials or self.session.credentials
        
        embed = discord.Embed(
            title="Log capture session edited!",
            description="\n".join([
                f"**{esc_md(self.name)}**",
                f"🕓 <t:{int(self.start_time.timestamp())}:f> - <t:{int(self.end_time.timestamp())}:t>",
                f"🚩 Server: `{credentials.name if credentials else 'Unknown ⚠️'}`"
            ]),
            timestamp=datetime.now(tz=timezone.utc),
            colour=self.embed_color
        ).set_footer(
            text=str(interaction.user),
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None
        )

        if self.modifiers:
            embed.description += f"\n🧮 Modifiers: " + ", ".join([
                f"[{m.config.name}]({MODIFIERS_URL}#{m.config.name.lower().replace(' ', '-')})"
                for m in self.modifiers.get_modifier_types()
            ])

        await interaction.response.defer()
        await self.session.edit(
            start_time=self.start_time,
            end_time=self.end_time,
            credentials=self.credentials,
            modifiers=self.modifiers
        )
        self.__created == True

        if interaction.channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.channel.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

        if self._message:
            await self._message.delete()

    async def select_modifiers(self, interaction: Interaction):
        view = SessionModifierView(self._message, self.updated_modifiers, flags=self.modifiers)
        await interaction.response.edit_message(content="Select all of the modifiers you want to enable by clicking on the buttons below", view=view, embed=None)
    
    async def updated_modifiers(self, interaction: discord.Interaction, modifiers: ModifierFlags, _skip_save_default=False):
        if (not _skip_save_default
            and self.credentials and not self.credentials.temporary
            and modifiers != self.credentials.default_modifiers):
            
            @only_once
            async def save_as_default(interaction: Interaction):
                self.credentials.default_modifiers = modifiers.copy()
                self.credentials.save()
                await self.updated_modifiers(interaction, modifiers, _skip_save_default=True)

            @only_once
            async def skip_save_default(interaction: Interaction):
                await self.updated_modifiers(interaction, modifiers, _skip_save_default=True)

            view = View()
            view.add_item(CallableButton(save_as_default, style=ButtonStyle.blurple, label="Set as default"))
            view.add_item(CallableButton(skip_save_default, style=ButtonStyle.gray, label="Skip"))

            await interaction.response.edit_message(content=None, view=view, embed=get_question_embed(
                "Do you want to save these modifiers as the default for this server?",
                "That way you don't have to re-enable them for every session. Do note that these defaults also apply to AutoSession. You can always change your preferences again later."
            ))

        else:
            self.modifiers = modifiers
            await interaction.response.edit_message(content=None, view=self, embed=self.get_embed())

class sessions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    SessionGroup = app_commands.Group(
        name="session",
        description="Manage log records",
    )

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize all sessions and autosessions"""

        cursor.execute("SELECT ROWID FROM sessions WHERE deleted = 0")
        for (id_,) in cursor.fetchall():
            if id_ not in SESSIONS:
                try:
                    HLLCaptureSession.load_from_db(id_)
                except:
                    print('Failed to load session', id_)
                    print_exc()
        
        cursor.execute("SELECT ROWID FROM credentials WHERE autosession_enabled = 1")
        for (id_,) in cursor.fetchall():
            if id_ not in CREDENTIALS:
                try:
                    Credentials.load_from_db(id_)
                except:
                    print('Failed to load credentials and initialize autosession', id_)
                    print_exc()

        if not self.session_manager.is_running():
            self.session_manager.start()

    @tasks.loop(minutes=5)
    async def session_manager(self):
        """Clean up expired sessions"""
        for sess in tuple(SESSIONS.values()):
            if sess.should_delete():
                sess.delete()

    def _parse_start_and_end_time(self, start_time: Union[str, datetime], end_time: Union[str, datetime]):
        if not isinstance(start_time, datetime):
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
        
        if not isinstance(end_time, datetime):
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
        
        return start_time, end_time

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
        start_time, end_time = self._parse_start_and_end_time(start_time, end_time)

        if server:
            credentials = Credentials.get(server)
        else:
            credentials = False

        duration = end_time - start_time
        minutes = int(duration.total_seconds() / 60 + 0.5)
        if duration > MAX_SESSION_DURATION:
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

        embeds = [discord.Embed()]

        if filter == SessionFilters.all or filter == SessionFilters.scheduled:
            sessions = [session for session in all_sessions if isinstance(session.active_in(), timedelta)]
            if sessions:
                count += len(sessions)
                embed = discord.Embed(title="📅 Scheduled records")
                for i, session in enumerate(sessions):
                    if i and (i % 15) == 0:
                        embeds.append(embed)
                        embed = discord.Embed(title="📅 Scheduled records")

                    description = f"> 🕓 <t:{int(session.start_time.timestamp())}:f> - <t:{int(session.end_time.timestamp())}:t> ({int(session.duration.total_seconds() // 60)} mins.)"
                    description += f"\n> 🚩 `{session.credentials.name if session.credentials else 'Unknown'}`"
                    if session.modifier_flags:
                        description += f" | 🧮 " + ", ".join([
                            f"[{m.config.name}]({MODIFIERS_URL}#{m.config.name.lower().replace(' ', '-')})"
                            for m in session.modifier_flags.get_modifier_types()
                        ])
                    description += f"\n> 🔆 Starts <t:{int(session.start_time.timestamp())}:R>"

                    embed.add_field(
                        name=f"> **{esc_md(session.name)}**",
                        value=description,
                        inline=False
                    )
                embeds.append(embed)

        if filter == SessionFilters.all or filter == SessionFilters.ongoing:
            sessions = [session for session in all_sessions if session.active_in() is True]
            if sessions:
                count += len(sessions)
                embed = discord.Embed(title="🎦 Currently recording")
                for i, session in enumerate(sessions):
                    if i and (i % 15) == 0:
                        embeds.append(embed)
                        embed = discord.Embed(title="🎦 Currently recording")

                    description = f"> 🕓 <t:{int(session.start_time.timestamp())}:f> - <t:{int(session.end_time.timestamp())}:t> ({int(session.duration.total_seconds() // 60)} mins.)"
                    description += f"\n> 🚩 `{session.credentials.name if session.credentials else 'Unknown'}`"
                    if session.modifier_flags:
                        description += f" | 🧮 " + ", ".join([
                            f"[{m.config.name}]({MODIFIERS_URL}#{m.config.name.lower().replace(' ', '-')})"
                            for m in session.modifier_flags.get_modifier_types()
                        ])

                    embed.add_field(
                        name=f"> **{esc_md(session.name)}**",
                        value=description,
                        inline=False
                    )
                embeds.append(embed)

        if filter == SessionFilters.all or filter == SessionFilters.finished:
            sessions = [session for session in all_sessions if session.active_in() is False]
            if sessions:
                count += len(sessions)
                embed = discord.Embed(title="✅ Finished records")
                for i, session in enumerate(sessions):
                    if i and (i % 15) == 0:
                        embeds.append(embed)
                        embed = discord.Embed(title="✅ Finished records")

                    description = f"> 🕓 <t:{int(session.start_time.timestamp())}:f> - <t:{int(session.end_time.timestamp())}:t> ({int(session.duration.total_seconds() // 60)} mins.)"
                    description += f"\n> 🚩 `{session.credentials.name if session.credentials else 'Unknown'}`"
                    if session.modifier_flags:
                        description += f" | 🧮 " + ", ".join([
                            f"[{m.config.name}]({MODIFIERS_URL}#{m.config.name.lower().replace(' ', '-')})"
                            for m in session.modifier_flags.get_modifier_types()
                        ])
                    description += f"\n> 🗑️ Expires <t:{int((session.end_time + DELETE_SESSION_AFTER).timestamp())}:R>"

                    embed.add_field(
                        name=f"> **{esc_md(session.name)}**",
                        value=description,
                        inline=False
                    )
                embeds.append(embed)

        embeds[0].title = f"**There are {count} {'total' if filter == SessionFilters.all else filter.value} sessions**"
        if len(embeds) == 1:
            mention = await get_command_mention(self.bot.tree, 'session', 'new')
            embeds[0].description = f"Sessions can be created with the {mention} command."

        await interaction.response.send_message(embeds=embeds, ephemeral=True)

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
            ), view=None)

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
            ), view=None)

        embed = discord.Embed(
            title="Are you sure you want to delete this session?",
            description="This will also remove all the associated records. This cannot be reverted."
        )

        view = View()
        view.add_item(CallableButton(on_confirm, label="Confirm", style=ButtonStyle.gray))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @SessionGroup.command(name="edit", description="Modify a session")
    @app_commands.describe(
        session="A yet to be started or ongoing log capture session",
        start_time="The time when to start recording, in UTC. Can be \"now\" as well.",
        end_time="The time when to stop recording, in UTC.",
        server="The HLL server to record logs from",
    )
    @app_commands.autocomplete(
        session=autocomplete_active_sessions,
        end_time=autocomplete_end_time,
        server=autocomplete_credentials,
    )
    async def edit_session(self, interaction: Interaction, session: int, start_time: Optional[str] = None, end_time: Optional[str] = None, server: Optional[int] = None):
        session: HLLCaptureSession = SESSIONS[session]

        if server:
            credentials = Credentials.get(server)
        elif server == 0:
            credentials = False
        else:
            credentials = None

        if session.is_auto_session and (start_time is not None or server is not None):
            raise CustomException(
                "Invalid arguments!",
                "You cannot change the start time or server for sessions that were created by AutoSession"
            )

        modifiers_first = False

        if session.active_in() is True:
            if session.credentials and server is not None:
                raise CustomException(
                    "Invalid arguments!",
                    "You cannot change the server for sessions that have already started"
                )
            if start_time:
                raise CustomException(
                    "Invalid arguments!",
                    "You cannot change the start time for sessions that have already started"
                )
            if end_time is None and server is None:
                modifiers_first = True
        
        elif (
            start_time is None
            and end_time is None
            and server is None
        ):
            modifiers_first = True

        if not start_time:
            start_time = session.start_time
        if not end_time:
            end_time = session.end_time

        start_time, end_time = self._parse_start_and_end_time(start_time, end_time)

        view = SessionCreateView(
            name=session.name,
            guild=interaction.guild,
            credentials=credentials,
            start_time=start_time,
            end_time=end_time,
            session=session,
        )
        await view.send(interaction, modifiers_first=modifiers_first)

async def setup(bot):
    await bot.add_cog(sessions(bot))
