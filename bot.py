# HLLLogUtilities by timraay/Abu

import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import os
from pathlib import Path

from utils import get_config, ttl_cache
from lib.hss.api import HSSApi

HSS_API_BASE = get_config().get('HSS', 'ApiBaseUrl')

async def load_all_cogs():
    for cog in os.listdir(Path("./cogs")):
        if cog.endswith(".py"):
            try:
                cog = f"cogs.{cog.replace('.py', '')}"
                await bot.load_extension(cog)
            except Exception as e:
                print(f"{cog} can not be loaded:")
                raise e
    print('Loaded all cogs')

async def sync_commands():
    for cmd in bot.tree.walk_commands():
        cmd.default_permissions = discord.Permissions(manage_guild=True)
    try:
        await asyncio.wait_for(bot.tree.sync(), timeout=5)
        print('Synced app commands')
    except asyncio.TimeoutError:
        print("Didn't sync app commands. This was likely last done recently, resulting in rate limits.")

    print("\nLaunched " + bot.user.name + " on " + str(datetime.now()))
    print("ID: " + str(bot.user.id))


class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.remove_command('help')
        self.hss = HSSApi(HSS_API_BASE)
    
    async def setup_hook(self) -> None:
        await load_all_cogs()
        await sync_commands()
    
    @ttl_cache(size=60, seconds=300)
    async def _hss_teams(self):
        return await self.hss.teams()

bot = Bot(
    intents=discord.Intents.default(),
    command_prefix=commands.when_mentioned,
    case_insensitive=True
)


@bot.command(aliases=["load"])
@commands.is_owner()
async def enable(ctx: commands.Context, cog: str):
    """ Enable a cog """
    cog = cog.lower()
    if Path(f"./cogs/{cog}.py").exists():
        await bot.load_extension(f"cogs.{cog}")
        await ctx.send(f"Enabled {cog}")
    else:
        await ctx.send(f"{cog} doesn't exist")

@bot.command(aliases=["unload"])
@commands.is_owner()
async def disable(ctx: commands.Context, cog: str):
    """ Disable a cog """
    cog = cog.lower()
    if Path(f"./cogs/{cog}.py").exists():
        await bot.unload_extension(f"cogs.{cog}")
        await ctx.send(f"Disabled {cog}")
    else:
        await ctx.send(f"{cog} doesn't exist")

@bot.command()
@commands.is_owner()
async def reload(ctx: commands.Context, cog: str = None):
    """ Reload cogs """

    async def reload_cog(ctx: commands.Context, cog: str):
        """ Reloads a cog """
        try:
            await bot.reload_extension(f"cogs.{cog}")
            await ctx.send(f"Reloaded {cog}")
        except Exception as e:
            await ctx.send(f"Couldn't reload {cog}, " + str(e))

    if not cog:
        for cog in os.listdir(Path("./cogs")):
            if cog.endswith(".py"):
                cog = cog.replace(".py", "")
                await reload_cog(ctx, cog)
    else:
        if Path(f"./cogs/{cog}.py").exists():
            await reload_cog(ctx, cog)
        else:
            await ctx.send(f"{cog} doesn't exist")

bot.run(get_config()['Bot']['Token'])