import discord
from discord import app_commands, ui, Interaction, ButtonStyle
from discord.ext import commands
from discord.utils import escape_markdown as esc_md
from ipaddress import IPv4Address
from datetime import timedelta
import asyncio
from functools import wraps
from typing import Optional, Callable
import logging

from lib.credentials import Credentials, credentials_in_guild_tll
from lib.exceptions import HLLAuthError, HLLConnectionError, HLLConnectionRefusedError
from lib.rcon import create_plain_transport
from lib.autosession import MIN_PLAYERS_TO_START, MIN_PLAYERS_UNTIL_STOP, SECONDS_BETWEEN_ITERATIONS, MAX_DURATION_MINUTES
from lib.modifiers import ModifierFlags
from discord_utils import CallableButton, get_error_embed, get_success_embed, get_question_embed, handle_error, CustomException, View, Modal, only_once, ExpiredButtonError

MIN_ALLOWED_PORT = 1025
MAX_ALLOWED_PORT = 65536

SECURITY_URL = "https://github.com/timraay/HLLLogUtilities/blob/main/SECURITY.md"
MODIFIERS_URL = "https://github.com/timraay/HLLLogUtilities/blob/main/README.md"

class RCONCredentialsModal(Modal):
    name = ui.TextInput(label="Server Name - How I should call this server", placeholder="My HLL Server #1", required=True, max_length=60)
    address = ui.TextInput(label="RCON Address - To connect to RCON", placeholder="XXX.XXX.XXX.XXX:XXXXX", required=True, min_length=12, max_length=21)
    password = ui.TextInput(label="RCON Password - For authentication", required=True, max_length=40)

    def __init__(self, callback, *, title: str = ..., defaults: 'Credentials' = None, timeout: Optional[float] = None, **kwargs) -> None:
        if defaults:
            self.name.default = defaults.name
            self.address.default = f"{defaults.address}:{defaults.port}"
        super().__init__(title=title, timeout=timeout, **kwargs)
        self._callback = callback

    async def on_submit(self, interaction: Interaction):
        try:
            address, port = self.address.value.split(':', 1)
            address = str(IPv4Address(address))
            port = int(port)
        except:
            raise CustomException(
                "Invalid RCON Address!",
                "The given input is not a valid IPv4 address with port."
            )
        
        if not MIN_ALLOWED_PORT <= port <= MAX_ALLOWED_PORT:
            raise CustomException(
                "Invalid port!",
                f"Port {port} is out of range 1025-65536."
            )

        password = self.password.value
        if " " in password:
            raise CustomException(
                "Invalid password!",
                "Password must not contain spaces."
            )

        async def finish_callback(_interaction):
            await interaction.delete_original_response()
            await self._callback(
                _interaction,
                name=self.name.value,
                address=address,
                port=port,
                password=password
            )

        logging.info('Attempting connection to %s:%s (GID: %s)', address, port, interaction.guild_id)
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            transport = await create_plain_transport(
                host=address,
                port=port,
                password=password
            )
            transport._transport.close()
        except HLLConnectionError as error:
            logging.error('Failed connection to %s:%s (GID: %s) - %s: %s', address, port, interaction.guild_id, type(error).__name__, str(error))
            if isinstance(error, HLLAuthError):
                embed = get_error_embed(
                    title=str(error),
                    description="Failed to authenticate with RCON. This means that the provided RCON password does not work. Possible solutions are as follows:\n\n• Verify that the password is correct\n\nIf you still wish to continue, press the below button. Otherwise you may dismiss this message."
                )
            elif isinstance(error, HLLConnectionRefusedError):
                embed = get_error_embed(
                    title=str(error),
                    description="Failed to connect to your server, because it actively refused connection via specified port. This most likely means that the port is incorrect. Possible solutions are as follows:\n\n• Verify that the port is correct\n\nIf you still wish to continue, press the below button. Otherwise you may dismiss this message."
                )
            else:
                embed = get_error_embed(
                    title=str(error),
                    description="Failed to connect to your server, because the address could not be resolved or the connection was refused. Possible solutions are as follows:\n\n• Verify that the address and port are correct\n• Make sure the server is online\n\nIf you still wish to continue, press the below button. Otherwise you may dismiss this message."
                )

            async def finish_callback_delete(_interaction):
                # await interaction.delete_original_response()
                await finish_callback(interaction)

            view = View()
            view.add_item(CallableButton(finish_callback_delete, label="Ignore & Continue", style=discord.ButtonStyle.gray))
            
            await interaction.followup.send(embed=embed, view=view)
        else:
            logging.info('Successfully opened connection with %s:%s (GID: %s)', address, port, interaction.guild_id)
            await finish_callback(interaction)
    
    async def on_error(self, interaction: Interaction, error: Exception):
        await handle_error(interaction, error)

class AutoSessionView(View):
    def __init__(self, credentials: Credentials, guild: discord.Guild):
        super().__init__()
        self.credentials = credentials
        self.guild = guild
        self.message = None

        if self.enabled:
            self.button = CallableButton(self.disable_button_cb, label="Disable", style=discord.ButtonStyle.red)
        else:
            self.button = CallableButton(self.enable_button_cb, label="Enable", style=discord.ButtonStyle.green)
        
        self.add_item(self.button)
        self.add_item(CallableButton(self.select_modifiers_cb, label="Modifiers...", style=discord.ButtonStyle.blurple))
        self.add_item(ui.Button(label="Docs", style=discord.ButtonStyle.blurple, url="https://github.com/timraay/HLLLogUtilities#automatic-session-scheduling"))
        self.add_item(CallableButton(self.update, emoji="🔄", style=discord.ButtonStyle.gray))
    
    @property
    def autosession(self):
        return self.credentials.autosession
    
    @property
    def enabled(self):
        return self.autosession.enabled

    def get_embed(self):
        if self.guild.icon is not None:
            icon_url = self.guild.icon.url
        else:
            icon_url = None
        
        embed = discord.Embed(
            description="⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯",
        ).set_author(
            name=str(self.credentials),
            icon_url=icon_url
        ).set_footer(
            text=(
                "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
                f"Automatically start sessions with AutoSession! As soon as {MIN_PLAYERS_TO_START}\n"
                "or more players get online a new session will automatically be\n"
                f"started, which automatically ends after {(MAX_DURATION_MINUTES+59) // 60} hours or when the\n"
                f"server drops below {MIN_PLAYERS_UNTIL_STOP} players again."
            )
        )

        if self.credentials.autosession_enabled:
            session = self.autosession.get_active_session()

            if session:
                ts = int(session.start_time.timestamp())
                embed.title = "AutoSession is currently enabled."
                embed.color = discord.Colour.from_rgb(52,205,43)
                embed.add_field(name="Status", value="\🟢Enabled", inline=True)
                embed.add_field(name="Currently recording...", value=f"<t:{ts}:t> (<t:{ts}:R>)", inline=True)
            
            elif self.autosession.is_slowed:
                ts = int(self.autosession.last_seen_time.timestamp())
                embed.title = "AutoSession is having issues!"
                embed.color = discord.Colour.from_rgb(235,49,64)
                embed.add_field(name="Status", value="\🟠Problems", inline=True)
                embed.add_field(name="Last successful update", value=f"<t:{ts}:t> (<t:{ts}:R>)", inline=True)
                embed.add_field(name="Most recent error", value=self.autosession.last_error, inline=False)
            
            elif not self.autosession._cooldown:
                ts = int(self.autosession.last_seen_time.timestamp())
                embed.title = "AutoSession is currently enabled."
                embed.color = discord.Colour.from_rgb(52,205,43)
                embed.add_field(name="Status", value="\🟢Enabled", inline=True)
                embed.add_field(name="Waiting for players...", value=f"{self.autosession.last_seen_playercount}/{MIN_PLAYERS_TO_START} players (<t:{ts}:R>)", inline=True)
            
            elif self.autosession.last_seen_playercount >= MIN_PLAYERS_UNTIL_STOP:
                ts = int(self.autosession.last_seen_time.timestamp())
                embed.title = "AutoSession is currently enabled."
                embed.color = discord.Colour.from_rgb(255,243,33)
                embed.add_field(name="Status", value="\🟡Cooldown", inline=True)
                embed.add_field(name="Waiting for players...", value=f"{self.autosession.last_seen_playercount}/{MIN_PLAYERS_UNTIL_STOP} players (<t:{ts}:R>)", inline=True)
            
            else:
                ts = int((self.autosession.last_seen_time + self.autosession._cooldown * timedelta(SECONDS_BETWEEN_ITERATIONS)).timestamp())
                embed.title = "AutoSession is currently enabled."
                embed.color = discord.Colour.from_rgb(255,243,33)
                embed.add_field(name="Status", value="\🟡Cooldown", inline=True)
                embed.add_field(name="Available soon...", value=f"<t:{ts}:t> (<t:{ts}:R>)", inline=True)

        else:
            embed.title = "AutoSession is currently disabled!"
            embed.add_field(name="Status", value="\🔴Disabled", inline=True)
            embed.add_field(name="Documentation", value="[View on GitHub](https://github.com/timraay/HLLLogUtilities#automatic-session-scheduling)", inline=True)

        modifiers = self.credentials.default_modifiers
        if modifiers:
            embed.add_field(name=f"Enabled modifiers ({len(modifiers)})", value="\n".join([
                f"{m.config.emoji} [**{m.config.name}**]({MODIFIERS_URL}#{m.config.name.lower().replace(' ', '-')}) - {m.config.description}"
                for m in modifiers.get_modifier_types()
            ]), inline=False)

        return embed
    
    def __credentials_still_exist(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            if self.autosession.id is None:
                raise ExpiredButtonError
            return await func(self, *args, **kwargs)
        return wrapper

    @__credentials_still_exist
    async def enable_button_cb(self, interaction: Interaction):
        if not self.autosession.enabled:
            await self.autosession.enable()
        await self.update(interaction)

    @__credentials_still_exist
    async def disable_button_cb(self, interaction: Interaction):
        if self.autosession.enabled:
            await self.autosession.disable()
        await self.update(interaction)
    
    @__credentials_still_exist
    async def update(self, interaction: Interaction):
        if self.enabled:
            self.button.callback = self.disable_button_cb
            self.button.label = "Disable"
            self.button.style = discord.ButtonStyle.red
        else:
            self.button.callback = self.enable_button_cb
            self.button.label = "Enable"
            self.button.style = discord.ButtonStyle.green
        
        embed = self.get_embed()

        await interaction.response.edit_message(embed=embed, view=self)

    @__credentials_still_exist
    async def select_modifiers_cb(self, interaction: Interaction):
        view = SessionModifierView(self.message, self.updated_modifiers_cb, flags=self.credentials.default_modifiers)
        await interaction.response.edit_message(content="Select all of the modifiers you want to enable by clicking on the buttons below", view=view, embed=None)
    
    @__credentials_still_exist
    async def updated_modifiers_cb(self, interaction: discord.Interaction, modifiers: ModifierFlags):
        changed = (modifiers != self.credentials.default_modifiers)

        self.credentials.default_modifiers = modifiers.copy()
        self.credentials.save()
        self.modifiers = modifiers
        
        session = self.autosession.get_active_session()
        if changed and session and (modifiers != session.modifier_flags):
            
            @only_once
            async def do_edit_ongoing_session(interaction: Interaction):
                await session.edit(modifiers=modifiers)
                await interaction.response.edit_message(content=None, view=self, embed=self.get_embed())                

            @only_once
            async def skip_edit_ongoing_session(interaction: Interaction):
                await interaction.response.edit_message(content=None, view=self, embed=self.get_embed())

            view = View()
            view.add_item(CallableButton(do_edit_ongoing_session, style=ButtonStyle.blurple, label="Update session"))
            view.add_item(CallableButton(skip_edit_ongoing_session, style=ButtonStyle.gray, label="Skip"))

            await interaction.response.edit_message(content=None, view=view, embed=get_question_embed(
                "Do you want to apply these new modifiers to the ongoing session?",
                f"You currently have a session, **{esc_md(session.name)}**, already active. Do you want its active modifiers to be updated, or leave it as is?"
            ))

        else:
            await interaction.response.edit_message(content=None, view=self, embed=self.get_embed())

class SessionModifierView(View):
    def __init__(self, message: discord.InteractionMessage, callback: Callable, flags: ModifierFlags = None, timeout: float = 300.0, **kwargs):
        super().__init__(timeout=timeout, **kwargs)
        self.message = message
        self._callback = callback
        self.flags = flags.copy() or ModifierFlags()
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

async def autocomplete_credentials(interaction: Interaction, current: str):
    choices = [app_commands.Choice(name=str(credentials), value=credentials.id)
        for credentials in await credentials_in_guild_tll(interaction.guild_id) if current.lower() in str(credentials).lower() and credentials.id]
    choices.append(app_commands.Choice(name="Custom", value=0))
    return choices

async def autocomplete_credentials_no_custom(interaction: Interaction, current: str):
    return [app_commands.Choice(name=str(credentials), value=credentials.id)
        for credentials in await credentials_in_guild_tll(interaction.guild_id) if current.lower() in str(credentials).lower() and credentials.id]

class credentials(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    Group = app_commands.Group(name="credentials", description="Manage your credentials")

    @Group.command(name="list", description="Get a list of all known credentials")
    async def list_credentials(self, interaction: Interaction):
        all_credentials = list(Credentials.in_guild(interaction.guild_id))
        embed = discord.Embed(
            title="Credentials",
            description="\n".join([
                f"> • **{esc_md(credentials.name)}**\n> ⤷ {credentials.address}:{credentials.port}"
                for credentials in all_credentials
            ]) if all_credentials else "No credentials are known yet."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @Group.command(name="remove", description="Remove credentials")
    @app_commands.describe(
        credentials="Credentials for RCON access"
    )
    @app_commands.autocomplete(
        credentials=autocomplete_credentials_no_custom
    )
    async def remove_credentials(self, interaction: Interaction, credentials: int):
        credentials: Credentials = Credentials.get(credentials)

        scheduled = list()
        ongoing = list()
        autosession_enabled = credentials.autosession.enabled

        for session in credentials.get_sessions():
            if session.active_in() is True:
                ongoing.append(session)
            elif session.active_in():
                scheduled.append(session)

        @only_once
        async def _delete_credentials(_interaction: Interaction, do_edit=True):
            embed = get_success_embed(
                title=f"Removed \"{credentials.name}\"!",
                description=f"⤷ {credentials.address}:{credentials.port}"
            )

            for session in scheduled:
                session.logger.info("Deleting scheduled session since its credentials are also being deleted")
                session.delete()
            
            coros = []
            for session in ongoing:
                session.logger.info("Stopping ongoing session since its credentials are being deleted")
                coros.append(session.stop())
            if credentials.autosession.enabled:
                credentials.autosession.logger.info("Disabling AutoSession since its credentials are being deleted")
                coros.append(credentials.autosession.disable())
            if coros:
                await asyncio.gather(*coros)                            

            await credentials.delete()

            if do_edit:
                await interaction.response.edit_message(embed=embed, view=None)
            else:
                await _interaction.response.send_message(embed=embed, ephemeral=True)

        if scheduled or ongoing or autosession_enabled:
            embed = get_question_embed(
                "Are you sure?",
                "When you delete these credentials, the following actions will be taken:\n"
            )

            for session in ongoing:
                embed.description += f"\n• Stop ongoing session **{esc_md(session.name)}**"
            for session in scheduled:
                embed.description += f"\n• Delete scheduled session **{esc_md(session.name)}**"
            if autosession_enabled:
                embed.description += f"\n• Disable AutoSession for this server"

            embed.description += f"\n\nFor ongoing or finished sessions logs will remain available for export."

            view = View()
            view.add_item(CallableButton(_delete_credentials, label="Confirm"))

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        else:
            await _delete_credentials(interaction, do_edit=False)
    
    @Group.command(name="add", description="Add credentials")
    async def add_credentials(self, interaction: Interaction):
        async def on_form_request(_interaction: Interaction):
            modal = RCONCredentialsModal(on_form_submit, title="RCON Credentials Form")
            await _interaction.response.send_modal(modal)

        async def on_form_submit(_interaction: Interaction, name: str, address: str, port: int, password: str):
            credentials = Credentials.create_in_db(_interaction.guild_id, name=name, address=address, port=port, password=password)

            await asyncio.gather(
                _interaction.followup.send(embed=get_success_embed(
                    title=f"Added \"{credentials.name}\"!",
                    description=f"⤷ {credentials.address}:{credentials.port}"
                ), ephemeral=True),
                interaction.edit_original_response(view=None)
            )
    
        embed = discord.Embed(
            title="Before you proceed...",
            description=f"Sharing passwords over the internet is a dangerous thing, and you should only do so with sources you trust. For that reason, I feel it is necessary to provide full clarity in what we use your information for and how we handle it. [Click here]({SECURITY_URL}) for more information.\n\nPressing the below button will open a form where you can enter the needed information."
        )
        view = View(timeout=600)
        view.add_item(CallableButton(on_form_request, label="Open form", emoji="📝", style=discord.ButtonStyle.gray))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    @Group.command(name="edit", description="Edit existing credentials")
    @app_commands.describe(
        credentials="Credentials for RCON access"
    )
    @app_commands.autocomplete(
        credentials=autocomplete_credentials_no_custom
    )
    async def edit_credentials(self, interaction: Interaction, credentials: int):
        credentials = Credentials.get(credentials)

        async def on_form_submit(_interaction: Interaction, name: str, address: str, port: int, password: str):
            credentials.name = name
            credentials.address = address
            credentials.port = port
            credentials.password = password
            credentials.save()

            await _interaction.followup.send(embed=get_success_embed(
                title=f"Edited \"{credentials.name}\"!",
                description=f"⤷ {credentials.address}:{credentials.port}"
            ), ephemeral=True)

        modal = RCONCredentialsModal(on_form_submit, title="RCON Credentials Form", defaults=credentials)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="autosession", description="Manage AutoSession for a server")
    @app_commands.describe(
        credentials="A server's credentials"
    )
    @app_commands.autocomplete(
        credentials=autocomplete_credentials_no_custom
    )
    async def manage_autosession(self, interaction: Interaction, credentials: int):
        credentials: Credentials = Credentials.get(credentials)
        
        view = AutoSessionView(credentials, interaction.guild)
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()
        
async def setup(bot):
    await bot.add_cog(credentials(bot))