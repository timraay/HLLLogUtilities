import discord
from discord import app_commands, Interaction, ui, ButtonStyle, SelectOption
from discord.ext import commands
from discord.utils import escape_markdown as esc_md
from datetime import datetime
from pydantic import BaseModel
from io import StringIO
from typing import Callable, List, Optional

from discord_utils import CallableButton, CallableSelect, only_once

from cogs.sessions import autocomplete_sessions
from lib.session import HLLCaptureSession, SESSIONS
from lib.storage import LogLine
from lib.info_types import EventFlags, EventTypes
from lib.converters import TextConverter

class ExportRange(BaseModel):
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    map_name: Optional[str]

    @property
    def duration(self):
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        else:
            return None

class ExportFilterView(ui.View):
    def __init__(self, interaction: Interaction, callback: Callable, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.interaction = interaction
        self._callback = callback
        
        self.flags = EventFlags.all()
        self.update_self()
    
    options = (
        ("Deaths", "💀", EventFlags.deaths()),
        ("Connections", "🧭", EventFlags.connections()),
        ("Gamestates", "🚥", EventFlags.game_states()),
        ("Teams", "🫐", EventFlags.teams()),
        ("Squads", "👬", EventFlags.squads()),
        ("Roles", "🏹", EventFlags.roles()),
        ("Messages", "✉️", EventFlags.messages()),
        ("Admin Cam", "🎥", EventFlags.admin_cam()),
    )
    
    async def toggle_value(self, interaction: Interaction, flags: EventFlags, enable: bool):
        if enable:
            self.flags |= flags
        else:
            self.flags ^= (self.flags & flags)
        
        await self.interaction.edit_original_response(view=self.update_self())
        await interaction.response.defer()

    def update_self(self):
        self.clear_items()
        for (name, emoji, flags) in self.options:
            enabled = (flags <= self.flags) # Subset of
            style = ButtonStyle.green if enabled else ButtonStyle.red
            self.add_item(CallableButton(self.toggle_value, flags, not enabled, label=name, emoji=emoji, style=style))
        self.add_item(CallableButton(self.callback, label="Continue...", style=ButtonStyle.gray, disabled=not self.flags))

        return self
    
    async def callback(self, interaction: Interaction):
        await interaction.response.defer()
        return await self._callback(interaction, self.flags)

class ExportRangeSelectView(ui.View):
    def __init__(self, interaction: Interaction, callback: Callable, logs: List[LogLine], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.interaction = interaction
        self._callback = callback

        flags = EventFlags(server_match_started=True)
        self.ranges = [ExportRange()]
        for log in flags.filter_logs(logs):
            self.ranges[-1].end_time = log.event_time
            self.ranges[-1].map_name = log.new

            self.ranges.append(ExportRange(
                start_time=log.event_time,
                map_name=log.new
            ))
        
        if len(self.ranges) == 1:
            self.ranges.clear()
        
        options = [SelectOption(label="Entire session", emoji="🟠", value="0")]
        for i, range in enumerate(self.ranges):

            description = "..."
            if range.start_time:
                description = range.start_time.strftime(range.start_time.strftime('%H:%Mh')) + description
            if range.end_time:
                description = description + range.end_time.strftime(range.end_time.strftime('%H:%Mh'))

            options.append(SelectOption(
                label=range.map_name,
                description=description,
                emoji="🔸",
                value=str(i + 1)
            ))
        
        self.add_item(CallableSelect(self.callback,
            placeholder="Select a time range...",
            options=options
        ))
        
    async def callback(self, interaction: Interaction, value: List[int]):
        int_value = int(value[0])
        range = self.ranges[int_value - 1] if int_value else None
        return await self._callback(interaction, range)


class exports(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    ExportGroup = app_commands.Group(
        name="export",
        description="Export saved sessions",
        default_permissions=discord.Permissions(0)
    )

    @ExportGroup.command(name="logs", description="Export logs from a session")
    @app_commands.describe(
        session="A log capture session"
    )
    @app_commands.autocomplete(
        session=autocomplete_sessions
    )
    async def export_logs(self, interaction: Interaction, session: int):
        session: HLLCaptureSession = SESSIONS[session]
        logs = session.get_logs()

        async def ask_export_range(_, flags: EventFlags):

            @only_once
            async def send_logs(_, range: ExportRange):
                range = range or ExportRange()

                logs = session.get_logs(
                    from_=range.start_time,
                    to=range.end_time,
                    filter=flags
                )
                converter = TextConverter

                fp = StringIO(converter.convert_many(logs))
                file = discord.File(fp, filename=session.name + '.' + converter.ext())

                content = f"Logs for **{esc_md(session.name)}**"
                if range.map_name:
                    content += f" ({range.map_name})"
                if flags != flags.all():
                    content += f"\n> Includes: **{'**, **'.join([option[0] for option in ExportFilterView.options if option[2] <= flags])}**"

                await interaction.delete_original_response()
                await interaction.followup.send(content=content, file=file)

            view = ExportRangeSelectView(interaction, send_logs, logs)
            await interaction.edit_original_response(
                content="Select a specific match to export the logs from by selecting it from the dropdown",
                view=view
            )

        view = ExportFilterView(interaction, ask_export_range)
        await interaction.response.send_message(
            content="Filter out certain log types by clicking on the categories below",
            view=view, ephemeral=True
        )

        

        
        

async def setup(bot: commands.Bot):
    await bot.add_cog(exports(bot))
