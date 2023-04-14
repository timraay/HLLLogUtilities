import discord
from discord.ext import commands, tasks
from discord import Interaction, app_commands
import asyncio
import aiohttp
import ast
import logging
from typing import List

from utils import get_config

REPO_AUTHOR_NAME = "timraay/HLLLogUtilities"

UPDATE_CHANNEL_OVERRIDES: List[int] = list()
for channel in get_config().get('Updates', 'UpdateChannelOverrides').split(','):
    channel = channel.strip()

    if not channel:
        continue
    
    try:
        channel = int(channel)
    except ValueError:
        logging.error('Failed to interpret %s as a guild ID', channel)
    else:
        UPDATE_CHANNEL_OVERRIDES.append(channel)


def insert_returns(body):
    # insert return stmt if the l expression is a expression statement
    if isinstance(body[-1], ast.Expr):
        body[-1] = ast.Return(body[-1].value)
        ast.fix_missing_locations(body[-1])

    # for if statements, we insert returns into the body and the orelse
    if isinstance(body[-1], ast.If):
        insert_returns(body[-1].body)
        insert_returns(body[-1].orelse)

    # for with blocks, again we insert returns into the body
    if isinstance(body[-1], ast.With):
        insert_returns(body[-1].body)


class _util(commands.Cog):
    """Utility commands to get help, stats, links and more"""

    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.last_release_id: int = None
        self.get_github_releases.start()

    @app_commands.command(name="ping", description="View the bot's current latency")
    async def ping(self, interaction: Interaction):
        latency = self.bot.latency * 1000
        color = discord.Color.dark_green()
        if latency > 150: color = discord.Color.green()
        if latency > 200: color = discord.Color.gold()
        if latency > 300: color = discord.Color.orange()
        if latency > 500: color = discord.Color.red()
        if latency > 1000: color = discord.Color(1)
        embed = discord.Embed(description=f'🏓 Pong! {round(latency, 1)}ms', color=color)
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="invite", description="Get an invite link to add me to your server")
    async def invite(self, interaction: Interaction):
        oauth = discord.utils.oauth_url(self.bot.user.id, permissions=discord.Permissions(permissions=35840))
        await interaction.response.send_message(content=f"You can invite me to your server by [clicking here]({oauth})!", ephemeral=True)
    
    @commands.command(description="Evaluate a python variable or expression", usage="r!eval <cmd>", hidden=True)
    @commands.is_owner()
    async def eval(self, ctx, *, cmd):
        """Evaluates input.
        Input is interpreted as newline seperated statements.
        If the last statement is an expression, that is the return value.
        Usable globals:
        - `bot`: the bot instance
        - `discord`: the discord module
        - `commands`: the discord.ext.commands module
        - `ctx`: the invokation context
        - `__import__`: the builtin `__import__` function
        Such that `>eval 1 + 1` gives `2` as the result.
        The following invokation will cause the bot to send the text '9'
        to the channel of invokation and return '3' as the result of evaluating
        >eval ```
        a = 1 + 2
        b = a * 2
        await ctx.send(a + b)
        a
        ```
        """
        fn_name = "_eval_expr"

        cmd = cmd.strip("` ")
        if cmd.startswith("py"): cmd = cmd.replace("py", "", 1)

        # add a layer of indentation
        cmd = "\n".join(f"    {i}" for i in cmd.splitlines())

        # wrap in async def body
        body = f"async def {fn_name}():\n{cmd}"

        parsed = ast.parse(body)
        body = parsed.body[0].body

        insert_returns(body)

        env = {
            'self': self,
            'discord': discord,
            'commands': commands,
            'ctx': ctx,
            '__import__': __import__
        }
        exec(compile(parsed, filename="<ast>", mode="exec"), env)

        result = (await eval(f"{fn_name}()", env))
        try:
            await ctx.send(result)
        except discord.HTTPException:
            pass

    
    async def get_latest_release(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://api.github.com/repos/{REPO_AUTHOR_NAME}/releases/latest') as response:
                res = await response.json()
                if response.status != 200:
                    raise RuntimeError(f"Expected status 200 but got {response.status}: {res}")
        return res

    @tasks.loop(minutes=15)
    async def get_github_releases(self):
        res = await self.get_latest_release()
        if res["id"] != self.last_release_id and self.last_release_id is None:
            print('Loading release:', res["tag_name"])
        if res["id"] != self.last_release_id and self.last_release_id is not None:
            print('New release:', res["tag_name"])
            channels = list()

            for guild in self.bot.guilds:
                overrides = [channel for channel in guild.text_channels
                            if channel.id in UPDATE_CHANNEL_OVERRIDES
                            and channel.permissions_for(guild.me).send_messages]

                if overrides:
                    channels += overrides
                elif guild.public_updates_channel and guild.public_updates_channel.permissions_for(guild.me).send_messages:
                    channels.append(guild.public_updates_channel)
                elif guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                    channels.append(guild.system_channel)
            
            if channels:
                print('Forwarding to following guilds:')
                for channel in channels:
                    print(f'- {channel.guild.name} #{channel.name}')
                
                embed = discord.Embed(
                    title=res["name"],
                    url=res["html_url"],
                    description=res["body"],
                    color=discord.Colour.brand_green()
                ).set_author(
                    name="New release published!",
                    icon_url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
                )

                if self.bot.user.id == 1033779011005980773:
                    embed.set_footer(text="A short downtime will occur shortly to apply the update.")
            
                await asyncio.gather(*[
                    channel.send(embed=embed)
                    for channel in channels
                ])

        self.last_release_id = res["id"]


async def setup(bot):
    await bot.add_cog(_util(bot))