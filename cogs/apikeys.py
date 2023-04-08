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
from lib.hss.apikeys import ApiKeys, api_keys_in_guild_ttl
from lib.rcon import create_plain_transport
from discord_utils import CallableButton, get_error_embed, get_success_embed, handle_error, CustomException, only_once, View
from utils import get_config

SECURITY_URL = "https://github.com/timraay/HLLLogUtilities/blob/main/SECURITY.md"

class HSSApiKeysModal(ui.Modal):
    tag = ui.TextInput(label="Team Tag", required=True, max_length=10)
    key = ui.TextInput(label="Bot API Key", required=True, min_length=40, max_length=40)

    def __init__(self, callback, *, title: str = ..., defaults: 'ApiKeys' = None, timeout: Optional[float] = None, **kwargs) -> None:
        if defaults:
            self.tag.default = defaults.tag
        super().__init__(title=title, timeout=timeout, **kwargs)
        self._callback = callback

    async def on_submit(self, interaction: Interaction):
        key = self.key.value
        if " " in key:
            raise CustomException(
                "Invalid API key!",
                "API Key must not contain spaces."
            )
        await interaction.response.defer(ephemeral=True, thinking=True)

        async def finish_callback(_interaction):
            await interaction.delete_original_response()
            await self._callback(
                _interaction,
                tag=self.tag.value,
                key=key,
            )

        await finish_callback(interaction)
    
    async def on_error(self, interaction: Interaction, error: Exception):
        await handle_error(interaction, error)

class api_keys(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    Group = app_commands.Group(name="hssapikeys", description="Manage API keys for Hell Let Loose Skill System")

    async def autocomplete_keys(self, interaction: Interaction, current: str):
        return [app_commands.Choice(name=str(key), value=key.id)
            for key in await api_keys_in_guild_ttl(interaction.guild_id) if current.lower() in str(key).lower()]

    @Group.command(name="list", description="Get a list of all known API Keys")
    async def list_credentials(self, interaction: Interaction):
        all_keys = ApiKeys.in_guild(interaction.guild_id)
        embed = discord.Embed(
            title="API Keys for Teams",
            description="\n".join([
                f"> • **{esc_md(key.tag)}**"
                for key in all_keys
            ]) if all_keys else "No API keys are known yet."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @Group.command(name="remove", description="Remove API Key")
    @app_commands.describe(
        keys="API Key to access Hell Let Loose Skill System"
    )
    @app_commands.autocomplete(
        keys=autocomplete_keys
    )
    async def remove_api_key(self, interaction: Interaction, keys: int):
        key_id = ApiKeys.load_from_db(keys)
        key_id.delete()
        await interaction.response.send_message(embed=get_success_embed(
            title=f"Removed API Key for team \"{key_id.tag}\"!",
        ), ephemeral=True)
    
    @Group.command(name="add", description="Add API Key")
    async def add_credentials(self, interaction: Interaction):
        async def on_form_request(_interaction: Interaction):
            modal = HSSApiKeysModal(on_form_submit, title="HSS API Key Form")
            await _interaction.response.send_modal(modal)

        async def on_form_submit(_interaction: Interaction, tag: str, key: str):
            key = ApiKeys.create_in_db(_interaction.guild_id, tag=tag, key=key)

            await asyncio.gather(
                _interaction.followup.send(embed=get_success_embed(
                    title=f"Added API Key for team \"{key.tag}\"!",
                ), ephemeral=True),
                interaction.edit_original_response(view=None)
            )
    
        embed = discord.Embed(
            title="Before you proceed...",
            description=f"API Keys are like passwords, sharing them over the internet is a dangerous thing, and you should only do so with sources your trust. For that reason, I feel it is necessary to provide full clarity in what we use your information for and how we handle it. [Click here]({SECURITY_URL}) for more information.\n\nPressing the below button will open a form where you can enter the needed information.",
        )
        view = View(timeout=600)
        view.add_item(CallableButton(on_form_request, label="Open form", emoji="📝", style=discord.ButtonStyle.gray))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @Group.command(name="edit", description="Edit existing API Key")
    @app_commands.describe(
        keys="API Key to access Hell Let Loose Skill System"
    )
    @app_commands.autocomplete(
        keys=autocomplete_keys
    )
    async def edit_credentials(self, interaction: Interaction, keys: int):
        api_key = ApiKeys.load_from_db(keys)

        async def on_form_submit(_interaction: Interaction, tag: str, key: str):
            api_key.tag = tag
            api_key.key = key
            api_key.save()

            await _interaction.followup.send(embed=get_success_embed(
                title=f"Edited API Key for team \"{api_key.tag}\"!",
            ), ephemeral=True)

        modal = HSSApiKeysModal(on_form_submit, title="HSS API Key Form", defaults=api_key)
        await interaction.response.send_modal(modal)


async def setup(bot):
    await bot.add_cog(api_keys(bot))
