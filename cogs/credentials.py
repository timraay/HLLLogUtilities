import discord
from discord import app_commands, ui, Interaction
from discord.ext import commands
from discord.utils import escape_markdown as esc_md
from ipaddress import IPv4Address
import asyncio
from typing import Optional
import logging

from lib.credentials import Credentials, credentials_in_guild_tll
from lib.exceptions import HLLAuthError, HLLConnectionError, HLLConnectionRefusedError, HLLError
from lib.rcon import create_plain_transport
from discord_utils import CallableButton, get_error_embed, get_success_embed, handle_error, CustomException, only_once, View
from utils import get_config

MIN_ALLOWED_PORT = 1025
MAX_ALLOWED_PORT = 65536

SECURITY_URL = "https://github.com/timraay/HLLLogUtilities/blob/main/SECURITY.md"

class RCONCredentialsModal(ui.Modal):
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
                await interaction.delete_original_response()
                await finish_callback(interaction)

            view = View()
            view.add_item(CallableButton(finish_callback_delete, label="Ignore & Continue", style=discord.ButtonStyle.gray))
            
            await interaction.followup.send(embed=embed, view=view)
        else:
            logging.info('Successfully opened connection with %s:%s (GID: %s)', address, port, interaction.guild_id)
            await finish_callback(interaction)
    
    async def on_error(self, interaction: Interaction, error: Exception):
        await handle_error(interaction, error)

class credentials(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    Group = app_commands.Group(name="credentials", description="Manage your credentials")

    async def autocomplete_credentials(self, interaction: Interaction, current: str):
        return [app_commands.Choice(name=str(credentials), value=credentials.id)
            for credentials in await credentials_in_guild_tll(interaction.guild_id) if current.lower() in str(credentials).lower()]

    @Group.command(name="list", description="Get a list of all known credentials")
    async def list_credentials(self, interaction: Interaction):
        all_credentials = Credentials.in_guild(interaction.guild_id)
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
        credentials=autocomplete_credentials
    )
    async def remove_credentials(self, interaction: Interaction, credentials: int):
        credentials = Credentials.load_from_db(credentials)
        credentials.delete()
        await interaction.response.send_message(embed=get_success_embed(
            title=f"Removed \"{credentials.name}\"!",
            description=f"⤷ {credentials.address}:{credentials.port}"
        ), ephemeral=True)
    
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
        credentials=autocomplete_credentials
    )
    async def edit_credentials(self, interaction: Interaction, credentials: int):
        credentials = Credentials.load_from_db(credentials)

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

async def setup(bot):
    await bot.add_cog(credentials(bot))