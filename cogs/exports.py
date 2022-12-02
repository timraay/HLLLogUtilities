import discord
from discord import app_commands, Interaction, ui, ButtonStyle, SelectOption
from discord.ext import commands
from discord.utils import escape_markdown as esc_md
from datetime import datetime
from pydantic import BaseModel
from io import StringIO
from typing import Callable, List, Optional

from discord_utils import CallableButton, CallableSelect, only_once, CustomException, get_error_embed

from cogs.sessions import autocomplete_sessions
from lib.session import HLLCaptureSession, SESSIONS
from lib.storage import LogLine
from lib.info_types import EventFlags, EventTypes
from lib.converters import ExportFormats, Converter
from lib.mappings import get_map_and_mode
from lib.scores import create_scoreboard, MatchData

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
    def __init__(self, interaction: Interaction, callback: Callable, *args, timeout: float = 300.0, **kwargs):
        super().__init__(*args, timeout=timeout, **kwargs)
        self.interaction = interaction
        self._callback = callback
        
        self.flags = EventFlags.all()
        self.update_self()
    
    options = (
        ("Deaths", "💀", EventFlags.deaths()),
        ("Joins", "🚪", EventFlags.connections()),
        ("Teams", "🫐", EventFlags.teams()),
        ("Squads", "👬", EventFlags.squads()),
        ("Roles", "🏹", EventFlags.roles()),
        ("Messages", "✉️", EventFlags.messages()),
        ("Gamestates", "🚥", EventFlags.game_states()),
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
    def __init__(self, interaction: Interaction, callback: Callable, logs: List[LogLine], *args, timeout: float = 300.0, **kwargs):
        super().__init__(*args, timeout=timeout, **kwargs)
        self.interaction = interaction
        self._callback = callback

        flags = EventFlags(server_match_started=True, server_match_ended=True)
        self.ranges = [ExportRange()]
        for log in flags.filter_logs(logs):
            log_type = EventTypes(log.type)
            
            if log_type == EventTypes.server_match_ended:
                self.ranges[-1].map_name = " ".join(get_map_and_mode(log.new))

            elif log_type == EventTypes.server_match_started:
                self.ranges[-1].end_time = log.event_time
                self.ranges.append(ExportRange(
                    start_time=log.event_time,
                    map_name=" ".join(get_map_and_mode(log.new))
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
                label=range.map_name or "Unknown",
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
        await interaction.response.defer()
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
        if not logs:
            raise CustomException(
                "Invalid session!",
                "This session doesn't hold any logs yet"
            )

        async def ask_export_range(_, flags: EventFlags):

            async def ask_export_format(_, range: ExportRange):
                range = range or ExportRange()

                @only_once
                async def send_logs(_interaction: Interaction, format: List[str]):
                    await _interaction.response.defer()

                    logs = session.get_logs(
                        from_=range.start_time,
                        to=range.end_time,
                        filter=flags
                    )
                    converter: Converter = ExportFormats[format[0]].value

                    if logs:
                        fp = StringIO(converter.convert_many(logs))
                        file = discord.File(fp, filename=session.name + '.' + converter.ext())

                        content = f"Logs for **{esc_md(session.name)}**"
                        if range.map_name:
                            content += f" ({range.map_name})"
                        if flags != flags.all():
                            content += f"\n> Includes: **{'**, **'.join([option[0] for option in ExportFilterView.options if option[2] <= flags])}**"

                        await interaction.delete_original_response()
                        await interaction.followup.send(content=content, file=file)
                    
                    else:
                        await interaction.edit_original_response(
                            content=None,
                            embed=get_error_embed(
                                title="Couldn't export logs!",
                                description="No logs were found matching the given criteria"
                            ),
                            view=None
                        )

                view = ui.View(timeout=300.0)
                view.add_item(CallableSelect(send_logs,
                    placeholder="Select an export format...",
                    options=[SelectOption(label=format.name, description=f"A .{format.value.ext()} file")
                        for format in ExportFormats.__members__.values()]
                ))
                await interaction.edit_original_response(
                    content="Select a format to export the logs in by selecting it from the dropdown",
                    view=view
                )

            view = ExportRangeSelectView(interaction, ask_export_format, logs)
            await interaction.edit_original_response(
                content="Select a specific match to export the logs from by selecting it from the dropdown",
                view=view
            )

        view = ExportFilterView(interaction, ask_export_range)
        await interaction.response.send_message(
            content="Filter out certain log types by clicking on the categories below",
            view=view, ephemeral=True
        )
    
    @ExportGroup.command(name="scoreboard", description="Export a scoreboard from a session")
    @app_commands.describe(
        session="A log capture session"
    )
    @app_commands.autocomplete(
        session=autocomplete_sessions
    )
    async def export_scoreboard(self, interaction: Interaction, session: int):
        session: HLLCaptureSession = SESSIONS[session]
        logs = session.get_logs()
        if not logs:
            raise CustomException(
                "Invalid session!",
                "This session doesn't hold any logs yet"
            )

        @only_once
        async def send_scoreboard(_, range: ExportRange):
            range = range or ExportRange()

            logs = session.get_logs(
                from_=range.start_time,
                to=range.end_time
            )
            if not logs:
                raise CustomException(
                    "Invalid range!",
                    "No logs match the given criteria"
                )

            match_data = MatchData.from_logs(logs, range)
            scoreboard = create_scoreboard(match_data)

            fp = StringIO(scoreboard)
            file = discord.File(fp, filename=f'{session.name} scores.txt')

            content = f"Scoreboard for **{esc_md(session.name)}**"
            if range.map_name:
                content += f" ({range.map_name})"

            await interaction.delete_original_response()
            await interaction.followup.send(content=content, file=file)

        view = ExportRangeSelectView(interaction, send_scoreboard, logs)
        await interaction.response.send_message(
            content="Select a specific match to export a scoreboard from by selecting it from the dropdown",
            view=view, ephemeral=True
        )
        

        
        

async def setup(bot: commands.Bot):
    await bot.add_cog(exports(bot))
