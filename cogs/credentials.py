import discord
from discord import app_commands, ui, Interaction
from discord.ext import commands
from discord.utils import escape_markdown as esc_md
from ipaddress import IPv4Address
from typing import Optional

from lib.credentials import Credentials, credentials_in_guild_tll
from discord_utils import CallableButton, handle_error, CustomException, only_once, View
from utils import get_config

SECURITY_URL = "https://github.com/timraay/HLLLogUtilities/blob/main/SECURITY.md"

class RCONCredentialsModal(ui.Modal):
    name = ui.TextInput(label="Server Name - How I should call this server", placeholder="My HLL Server #1", required=True, max_length=60)
    address = ui.TextInput(label="RCON Address - To connect to RCON", placeholder="XXX.XXX.XXX.XXX:XXXXX", required=True, min_length=12, max_length=21)
    password = ui.TextInput(label="RCON Password - For authentication", required=True, max_length=40)

    def __init__(self, callback, *, title: str = ..., timeout: Optional[float] = None, **kwargs) -> None:
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

        await self._callback(
            interaction,
            name=self.name.value,
            address=address,
            port=port,
            password=password
        )
    
    async def on_error(self, interaction: Interaction, error: Exception):
        await handle_error(interaction, error)

class credentials(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    Group = app_commands.Group(name="credentials", description="Manage your credentials")

    async def autocomplete_credentials(self, interaction: Interaction, current: str):
        return [app_commands.Choice(name=str(credentials), value=credentials.id)
            for credentials in await credentials_in_guild_tll(interaction.guild_id) if current.lower() in str(credentials).lower()]

    @app_commands.command(name="list", description="Get a list of all known credentials")
    async def list_credentials(self, interaction: Interaction):
        all_credentials = Credentials.in_guild(interaction.guild_id)
        embed = discord.Embed(
            title="Credentials",
            description="\n".join([
                f"**{esc_md(credentials.name)}**\n_  _{credentials.address}:{credentials.port}"
                for credentials in all_credentials
            ]) if credentials else "No credentials are known yet."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(credentials(bot))