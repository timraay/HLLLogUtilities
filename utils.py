import discord
from discord.ext import commands
from asyncio import TimeoutError

def int_to_emoji(value: int):
    if value == 0: return "0️⃣"
    elif value == 1: return "1️⃣"
    elif value == 2: return "2️⃣"
    elif value == 3: return "3️⃣"
    elif value == 4: return "4️⃣"
    elif value == 5: return "5️⃣"
    elif value == 6: return "6️⃣"
    elif value == 7: return "7️⃣"
    elif value == 8: return "8️⃣"
    elif value == 9: return "9️⃣"
    elif value == 10: return "🔟"
    else: return f"**#{str(value)}**"

def get_name(user):
    return user.nick if user.nick else user.name

def add_empty_fields(embed):
    try: fields = len(embed._fields)
    except AttributeError: fields = 0
    if fields > 3:
        empty_fields_to_add = 3 - (fields % 3)
        if empty_fields_to_add in (1, 2):
            for _ in range(empty_fields_to_add):
                embed.add_field(name="‏", value="‏") # These are special characters that can not be seen
    return embed

