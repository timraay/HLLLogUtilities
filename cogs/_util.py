import discord
from discord.ext import commands
from discord import Interaction, app_commands
import ast



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

    @app_commands.command(name="view", description="View the bot's current latency")
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

async def setup(bot):
    await bot.add_cog(_util(bot))