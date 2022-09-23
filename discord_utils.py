import discord
from discord import ui, app_commands, Interaction

from typing import Callable

class CallableButton(ui.Button):
    def __init__(self, callback: Callable, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._callback = callback
    async def callback(self, interaction: Interaction):
        await self._callback(interaction)

class CallableSelect(ui.Select):
    def __init__(self, callback: Callable, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._callback = callback
    async def callback(self, interaction: Interaction):
        await self._callback(interaction, self.values)


def get_error_embed(title: str, description: str = None):
    embed = discord.Embed(color=discord.Color.from_rgb(221, 46, 68))
    embed.set_author(name=title, icon_url='https://cdn.discordapp.com/emojis/808045512393621585.png')
    if description:
        embed.description = description

def get_success_embed(title: str, description: str = None):
    embed = discord.Embed(color=discord.Color(7844437))
    embed.set_author(name=title, icon_url="https://cdn.discordapp.com/emojis/809149148356018256.png")
    if description:
        embed.description = description

def get_question_embed(title: str, description: str = None):
    embed = discord.Embed(color=discord.Color(3315710))
    embed.set_author(name=title, icon_url='https://cdn.discordapp.com/attachments/729998051288285256/924971834343059496/unknown.png')
    if description:
        embed.description = description

