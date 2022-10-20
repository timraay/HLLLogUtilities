import discord
from discord import ui, app_commands, Interaction
from discord.ext import commands
from datetime import datetime, timedelta
import traceback

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
    return embed

def get_success_embed(title: str, description: str = None):
    embed = discord.Embed(color=discord.Color(7844437))
    embed.set_author(name=title, icon_url="https://cdn.discordapp.com/emojis/809149148356018256.png")
    if description:
        embed.description = description
    return embed

def get_question_embed(title: str, description: str = None):
    embed = discord.Embed(color=discord.Color(3315710))
    embed.set_author(name=title, icon_url='https://cdn.discordapp.com/attachments/729998051288285256/924971834343059496/unknown.png')
    if description:
        embed.description = description
    return embed


class ExpiredButtonError(Exception):
    """Raised when pressing a button that has already expired"""

class CustomException(Exception):
    """Raised to log a custom exception"""
    def __init__(self, error, *args):
        self.error = error
        super().__init__(*args)


async def handle_error(interaction: Interaction, error: Exception):
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original

    if isinstance(error, app_commands.CommandNotFound):
        embed = get_error_embed(title='Unknown command!')

    elif type(error).__name__ == CustomException.__name__:
        embed = get_error_embed(title=error.error, description=str(error))
    
    elif isinstance(error, ExpiredButtonError):
        embed = get_error_embed(title="This action no longer is available.")
    elif isinstance(error, app_commands.CommandOnCooldown):
        sec = timedelta(seconds=int(error.retry_after))
        d = datetime(1,1,1) + sec
        output = ("%dh%dm%ds" % (d.hour, d.minute, d.second))
        if output.startswith("0h"):
            output = output.replace("0h", "")
        if output.startswith("0m"):
            output = output.replace("0m", "")
        embed = get_error_embed(title="That command is still on cooldown!", description="Cooldown expires in " + output + ".")
    elif isinstance(error, app_commands.MissingPermissions):
        embed = get_error_embed(title="Missing required permissions to use that command!", description=str(error))
    elif isinstance(error, app_commands.BotMissingPermissions):
        embed = get_error_embed(title="I am missing required permissions to use that command!", description=str(error))
    elif isinstance(error, app_commands.CheckFailure):
        embed = get_error_embed(title="Couldn't run that command!", description=None)
    # elif isinstance(error, app_commands.MissingRequiredArgument):
    #     embed = get_error_embed(title="Missing required argument(s)!")
    #     embed.description = str(error)
    # elif isinstance(error, app_commands.MaxConcurrencyReached):
    #     embed = get_error_embed(title="You can't do that right now!")
    #     embed.description = str(error)
    elif isinstance(error, commands.BadArgument):
        embed = get_error_embed(title="Invalid argument!", description=str(error))
    else:
        embed = get_error_embed(title="An unexpected error occured!", description=str(error))
        try:
            raise
        except:
            traceback.print_exc()

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


class View(ui.View):
    async def on_error(self, interaction: Interaction, error: Exception, item, /) -> None:
        await handle_error(interaction, error)

class Modal(ui.View):
    async def on_error(self, interaction: Interaction, error: Exception, item, /) -> None:
        await handle_error(interaction, error)

def only_once(func):
    func.__has_been_ran_once = False
    async def decorated(*args, **kwargs):
        if func.__has_been_ran_once:
            raise ExpiredButtonError
        res = await func(*args, **kwargs)
        func.__has_been_ran_once = True
        return res
    return decorated