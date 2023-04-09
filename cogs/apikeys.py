import discord
from discord import app_commands, ui, Interaction
from discord.ext import commands
from discord.utils import escape_markdown as esc_md
import asyncio
import http
from typing import Optional

from lib.hss.api_key import HSSApiKey, api_keys_in_guild_ttl
from lib.exceptions import HTTPException
from discord_utils import CallableButton, get_success_embed, get_error_embed, CustomException, View, Modal

SECURITY_URL = "https://github.com/timraay/HLLLogUtilities/blob/main/SECURITY.md"

class HSSApiKeysModal(Modal):
    key = ui.TextInput(label="API Key", required=True, min_length=40, max_length=40)

    def __init__(self, callback, *, title: str = ..., timeout: Optional[float] = None, **kwargs) -> None:
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

        try:
            team = await interaction.client.hss.resolve_token(key)
        except Exception as exc:
            if isinstance(exc, HTTPException) and exc.status == http.HTTPStatus.UNAUTHORIZED:
                raise CustomException(
                    "Invalid API key!",
                    "This API key does not belong to any team."
                )
            else:
                raise exc
            
        api_key = HSSApiKey.create_temporary(
            guild_id=interaction.guild_id,
            team=team,
            key=key,
        )

        await interaction.delete_original_response()
        await self._callback(interaction, api_key)

class api_keys(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    Group = app_commands.Group(name="hssapikeys", description="Manage API keys for Hell Let Loose Skill System")

    async def autocomplete_keys(self, interaction: Interaction, current: str):
        return [app_commands.Choice(name=str(key), value=key.id)
            for key in await api_keys_in_guild_ttl(interaction.guild_id) if current.lower() in str(key).lower()]

    @Group.command(name="list", description="Get a list of all known API Keys")
    async def list_credentials(self, interaction: Interaction):
        all_keys = HSSApiKey.in_guild(interaction.guild_id)
        embed = discord.Embed(
            title="API Keys for Teams",
            description="\n".join([
                f"> • **{esc_md(key.tag)}**"
                for key in all_keys
            ]) if all_keys else "No API keys are known yet."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @Group.command(name="remove", description="Remove an API Key")
    @app_commands.describe(
        keys="API Key to access Hell Let Loose Skill System"
    )
    @app_commands.autocomplete(
        keys=autocomplete_keys
    )
    async def remove_api_key(self, interaction: Interaction, keys: int):
        api_key = HSSApiKey.load_from_db(keys)
        api_key.delete()
        await interaction.response.send_message(embed=get_success_embed(
            title=f"Removed API Key for {api_key.tag}!",
        ), ephemeral=True)
    
    @Group.command(name="add", description="Add an API Key")
    async def add_api_key(self, interaction: Interaction):
        async def on_form_request(_interaction: Interaction):
            modal = HSSApiKeysModal(on_form_submit, title="Submit HSS API key...")
            await _interaction.response.send_modal(modal)

        async def on_form_submit(_interaction: Interaction, api_key: HSSApiKey):
            api_key.insert_in_db()

            await asyncio.gather(
                _interaction.followup.send(embed=get_success_embed(
                    title=f"Added API Key for {api_key.team}!",
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
    async def edit_api_key(self, interaction: Interaction, keys: int):
        api_key = HSSApiKey.load_from_db(keys)

        async def on_form_submit(interaction: Interaction, new_key: HSSApiKey):
            if api_key.team == new_key.team:
                await self.update_key(interaction, api_key, new_key)

            else:
                async def on_overwrite_key(interaction: Interaction):
                    await self.update_key(interaction, api_key, new_key)

                async def on_add_separate_key(interaction: Interaction):
                    new_key.insert_in_db()
                    await interaction.response.edit_message(embed=get_success_embed(
                        title=f"Added API Key for {api_key.team}!",
                    ), ephemeral=True)

                view = View()
                view.add_item(CallableButton(on_overwrite_key, label="Overwrite key", style=discord.ButtonStyle.gray))
                view.add_item(CallableButton(on_add_separate_key, label="Add as separate key", style=discord.ButtonStyle.gray))
                await interaction.followup.send(embed=get_error_embed(
                    "New key belongs to a different team!",
                    (
                        f"The old key belonged to {api_key.tag}, whereas the new key belongs to"
                        f" {new_key.tag}. Are you sure you still want to overwrite the current key?"
                    )
                ))

        modal = HSSApiKeysModal(on_form_submit, title="Editing API key for %s..." % api_key.team.tag)
        await interaction.response.send_modal(modal)
    
    async def update_key(self, interaction: Interaction, old_key: HSSApiKey, new_key: HSSApiKey):
        old_key.team = new_key.team
        old_key.key = new_key.key
        old_key.save()

        embed = get_success_embed(f"Edited API Key for {old_key.team}!")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.edit_message(embed=embed)


async def setup(bot):
    await bot.add_cog(api_keys(bot))
