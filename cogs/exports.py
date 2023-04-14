from datetime import datetime
from io import StringIO
from typing import Callable, List, Optional, Union

import discord
from discord import app_commands, Interaction, ui, ButtonStyle, SelectOption
from discord.ext import commands
from discord.ui import Select
from discord.utils import escape_markdown as esc_md, format_dt
from pydantic import BaseModel

from cogs.sessions import autocomplete_sessions
from cogs.credentials import SECURITY_URL
from cogs.apikeys import HSSApiKeysModal
from discord_utils import CallableButton, CallableSelect, View, only_once, CustomException, get_error_embed, get_success_embed
from lib.converters import ExportFormats, Converter
from lib.hss.api_key import api_keys_in_guild_ttl, HSSApiKey, HSSTeam
from lib.info.models import EventFlags, EventTypes
from lib.mappings import get_map_and_mode, Map
from lib.scores import create_scoreboard, MatchGroup
from lib.session import HLLCaptureSession, SESSIONS
from lib.storage import LogLine

class ExportRange(BaseModel):
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    unload_time: Optional[datetime]
    map_name: Optional[str]

    @property
    def has_end_time(self):
        return self.end_time or self.unload_time

    @property
    def shortest_end_time(self):
        if not self.has_end_time:
            return None
        elif not self.unload_time:
            return self.end_time
        elif not self.end_time:
            return self.unload_time
        else:
            return min(self.end_time, self.unload_time)
    
    @property
    def longest_end_time(self):
        if not self.has_end_time:
            return None
        elif not self.unload_time:
            return self.end_time
        elif not self.end_time:
            return self.unload_time
        else:
            return max(self.end_time, self.unload_time)

    @property
    def duration(self):
        if self.start_time and self.has_end_time:
            return self.shortest_end_time - self.start_time
        else:
            return None


class ExportFilterView(View):
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
        ("Scores", "🪙", EventFlags.scores()),
        ("Messages", "✉️", EventFlags.messages()),
        ("Gamestates", "🚥", EventFlags.game_states()),
        ("Admin Cam", "🎥", EventFlags.admin_cam()),
        ("Modifiers", "🧮", EventFlags.modifiers()),
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
            enabled = (flags <= self.flags)  # Subset of
            style = ButtonStyle.green if enabled else ButtonStyle.red
            self.add_item(CallableButton(self.toggle_value, flags, not enabled, label=name, emoji=emoji, style=style))
        self.add_item(
            CallableButton(self.callback, label="Continue...", style=ButtonStyle.gray, disabled=not self.flags))

        return self

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()
        return await self._callback(interaction, self.flags)


class ExportRangeSelectView(View):
    def __init__(self, interaction: Interaction, callback: Callable, logs: List[LogLine], *args, timeout: float = 300.0,
                 **kwargs):
        super().__init__(*args, timeout=timeout, **kwargs)
        self.interaction = interaction
        self._callback = callback

        flags = EventFlags(server_match_started=True, server_match_ended=True, server_map_changed=True)
        self.ranges = [ExportRange()]
        for log in flags.filter_logs(logs):
            try:
                log_type = EventTypes(log.type)
            except ValueError:
                continue

            if log_type == EventTypes.server_match_ended:
                self.ranges[-1].end_time = log.event_time
                if not self.ranges[-1].map_name:
                    self.ranges[-1].map_name = " ".join(get_map_and_mode(log.new))

            elif log_type == EventTypes.server_match_started:
                self.ranges[-1].unload_time = log.event_time
                self.ranges.append(ExportRange(
                    start_time=log.event_time,
                    map_name=" ".join(get_map_and_mode(log.new))
                ))

            elif log_type == EventTypes.server_map_changed:
                if not self.ranges[-1].start_time:
                    last_start = None
                else:
                    last_start = (log.event_time - self.ranges[-1].start_time).total_seconds()

                if len(self.ranges) >= 2 and last_start and last_start < 30:
                    # The line appeared after the server_match_ended event
                    self.ranges[-2].map_name = Map.load(log.old).pretty()
                    self.ranges[-1].map_name = Map.load(log.new).pretty()
                
                elif last_start > 60:
                    # The line appeared before the server_match_ended event
                    self.ranges[-1].map_name = Map.load(log.old)

        if len(self.ranges) == 1:
            self.ranges.clear()

        options = [SelectOption(label="Entire session", emoji="🟠", value="0")]
        for i, range in enumerate(self.ranges):

            description = "..."
            if range.start_time:
                description = range.start_time.strftime(range.start_time.strftime('%H:%Mh')) + description
            if range.has_end_time:
                description = description + range.shortest_end_time.strftime(range.shortest_end_time.strftime('%H:%Mh'))

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
        range_i = int_value - 1 if int_value else None
        range = self.ranges[int_value - 1] if int_value else None
        await interaction.response.defer()
        return await self._callback(interaction, range, range_i)


class TeamSelectView(View):
    def __init__(self, interaction: Interaction, callback: Callable, teams: list[dict], *args, timeout: float = 300.0,
                 **kwargs):
        super().__init__(*args, timeout=timeout, **kwargs)
        self.interaction = interaction
        self._callback = callback

        self.add_item(CallableSelect(
            callback=self.callback,
            custom_id='opposing_team',
            min_values=1,
            max_values=1,
            placeholder="Select the opposing team",
            options=[
                SelectOption(
                    label=team.get('tag'),
                    description=team.get('name')
                ) for team in teams
            ]
        ))

    async def callback(self, interaction: Interaction, value: List[int]):
        return await self._callback(interaction, value[0])


class HSSSubmitPromptView(View):
    def __init__(self, logs: List[LogLine], user: discord.Member):
        super().__init__(timeout=60 * 10)
        self.message: discord.Message = None
        self.logs = logs
        self.user = user
    
    @discord.ui.button(label="Submit to HeLO", style=ButtonStyle.green)
    async def submit_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user != self.user and not interaction.channel.permissions_for(interaction.user).manage_guild:
            raise CustomException(
                "You are not allowed to use this!",
                "Only the author of the command and server admins may invoke this interaction"
            )

        api_keys = await api_keys_in_guild_ttl(interaction.guild.id)
        if not api_keys:
            view = HSSSubmitPromptApiKeyView(self.logs)
        elif len(api_keys) == 1:
            teams = await interaction.client._hss_teams()
            view = HSSSubmitSelectOpponentView(api_keys[0], self.logs, teams)
        else:
            view = HSSSubmitSelectApiKeyView(api_keys, self.logs)
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)

class HSSSubmitPromptApiKeyView(View):
    def __init__(self, logs: List[LogLine]):
        super().__init__()
        self.logs = logs
    
    def get_embed(self):
        return discord.Embed(
            title="Before you proceed...",
            description=(
                "You are about to export your logs to the [HLL Skill System](https://helo-system.de/)."
                " To authenticate your request, you need to include an API key. Your team manager can"
                " generate one [here](https://helo-system.de/)!"
                "\n\nRemember, this key serves as a password. As such, do not share it with others you"
                f" do not trust. More information can be found [here]({SECURITY_URL})."
                "\n\nThe below button will open up a form where you will need to paste this API key."
            )
        )

    @discord.ui.button(label="Open form", emoji="📝", style=ButtonStyle.gray)
    async def open_form_button(self, interaction: Interaction, button: ui.Button):
        modal = HSSApiKeysModal(self.submit_form, title="Submit HeLO API key...")
        await interaction.response.send_modal(modal)
    
    async def submit_form(self, interaction: Interaction, key: str, tag: str):
        api_key = HSSApiKey.create_in_db(interaction.guild.id, tag, key)
        teams = await interaction.client._hss_teams()
        view = HSSSubmitSelectOpponentView(api_key, self.logs, teams)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)
    
class HSSSubmitSelectOpponentView(View):
    def __init__(self, api_key: HSSApiKey, logs: List[LogLine], teams: List[HSSTeam]):
        super().__init__()
        self.api_key = api_key
        self.logs = logs

        end_log = next(log for log in logs if log.type == str(EventTypes.server_match_ended))
        self.map_name = get_map_and_mode(end_log.new)[0]
        self.allies_score = int(end_log.message.split(' - ')[0])
        self.axis_score = int(end_log.message.split(' - ')[1])
        self.duration = logs[1].event_time - logs[0].event_time

        # We can have at most 25 values per select dropdown, so we need to divide all
        # available teams in separate groups to avoid exceeding this limit

        all_teams = sorted(teams, key=lambda team: str(team))
        ordered_teams = {char: list() for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890?"}
        for team in all_teams:
            if team == self.api_key.team:
                continue
            char = team.tag[0].upper()
            if char not in ordered_teams:
                char = "?"
            ordered_teams[char].append(team)
        
        first_char = "A"
        prev_char = "A"
        group = list()
        grouped_teams = dict()
        for char, teams in ordered_teams.items():
            if len(group) + len(teams) > 25:
                grouped_teams[f"{first_char}-{prev_char}"] = group
                group = list()
                first_char = char
            prev_char = char
            group += teams
        if group:
            grouped_teams[f"{first_char}-?"] = group
        self.grouped_teams = grouped_teams

        self.group_index = 0
        self.group_buttons = list()
        for i, group_name in enumerate(self.grouped_teams.keys()):
            # reeeeeeeeeee
            if i == 0: callable = self._change_category_0
            elif i == 1: callable = self._change_category_1
            elif i == 2: callable = self._change_category_2
            elif i == 3: callable = self._change_category_3
            elif i == 4: callable = self._change_category_4
            elif i == 5: callable = self._change_category_5
            elif i == 6: callable = self._change_category_6
            elif i == 7: callable = self._change_category_7
            elif i == 8: callable = self._change_category_8
            elif i == 9: callable = self._change_category_9
            button = CallableButton(callable, label=group_name, style=ButtonStyle.green)
            self.add_item(button)
            self.group_buttons.append(button)
        
        self.select = CallableSelect(self.team_select, placeholder="Select your opponent...")
        self.add_item(self.select)

        self.update_components()
    
    def update_components(self):
        for i, button in enumerate(self.group_buttons):
            if i == self.group_index:
                button.style = ButtonStyle.green
                button.disabled = True
            else:
                button.style = ButtonStyle.green
                button.disabled = False
        
        group_name = tuple(self.grouped_teams.keys())[self.group_index]
        group_teams = self.grouped_teams[group_name]
        self.select.options = [
            SelectOption(label=str(team), value=team.tag)
            for team in group_teams
        ]

    async def team_select(self, interaction: Interaction, value: List[str]):
        tag = value[0]
        team = HSSTeam(tag=tag) # We don't need the name so this is fine
        view = HSSSubmitSelectWinnerView(self.api_key, self.logs, team, self.map_name, self.allies_score, self.axis_score)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def change_category(self, interaction: Interaction, group_index: int):
        self.group_index = group_index
        self.update_components()
        await interaction.response.edit_message(view=self)
    
    async def _change_category_0(self, interaction: Interaction):
        return await self.change_category(interaction, 0)
    async def _change_category_1(self, interaction: Interaction):
        return await self.change_category(interaction, 1)
    async def _change_category_2(self, interaction: Interaction):
        return await self.change_category(interaction, 2)
    async def _change_category_3(self, interaction: Interaction):
        return await self.change_category(interaction, 3)
    async def _change_category_4(self, interaction: Interaction):
        return await self.change_category(interaction, 4)
    async def _change_category_5(self, interaction: Interaction):
        return await self.change_category(interaction, 5)
    async def _change_category_6(self, interaction: Interaction):
        return await self.change_category(interaction, 6)
    async def _change_category_7(self, interaction: Interaction):
        return await self.change_category(interaction, 7)
    async def _change_category_8(self, interaction: Interaction):
        return await self.change_category(interaction, 8)
    async def _change_category_9(self, interaction: Interaction):
        return await self.change_category(interaction, 9)
    
    def get_embed(self):
        embed = discord.Embed(
            title=f"Match Overview - {self.map_name} ({format_dt(self.logs[0].event_time, 'f')})",
            description="We are currently filling in the details of your match. React to the dropdown below to fill in the remaining gaps."
        ).add_field(
            name="Result",
            value="\n".join([
                "Winner: ???",
                "Score: " + (
                    f"**{self.allies_score} - {self.axis_score}**"
                    if abs(self.allies_score - self.axis_score) != 5
                    else f"**{self.allies_score} - {self.axis_score} ({int(self.duration.total_seconds() // 60)} mins.)**"
                )
            ])
        ).add_field(
            name="Team 1 (You)",
            value="\n".join([
                f"Name: **{self.api_key.tag}**",
                "Faction: ???"
            ])
        ).add_field(
            name="Team 2 (Opponent)",
            value="\n".join([
                "Name: ???",
                "Faction: ???"
            ])
        )
        return embed
    
class HSSSubmitSelectApiKeyView(View):
    def __init__(self, api_keys: List[HSSApiKey], logs: List[LogLine]):
        super().__init__()
        self.api_keys = api_keys
        self.logs = logs

        self.duration = logs[1].event_time - logs[0].event_time
        
        self.add_item(CallableSelect(
            self.api_key_select,
            placeholder="Select a team...",
            options=[
                SelectOption(label=api_key.tag, value=str(i))
                for i, api_key in enumerate(api_keys)
            ]
        ))
    
    def get_embed(self):
        return None
    
    async def api_key_select(self, interaction: Interaction, value: str):
        await interaction.response.defer()
        api_key = self.api_keys[int(value[0])]
        teams = await interaction.client._hss_teams()
        view = HSSSubmitSelectOpponentView(api_key, self.logs, teams)
        embed = view.get_embed()
        await interaction.edit_original_response(embed=embed, view=view)

class HSSSubmitSelectWinnerView(View):
    def __init__(self, api_key: HSSApiKey, logs: List[LogLine], opponent: HSSTeam, map_name: str, allies_score: int, axis_score: int):
        super().__init__()
        self.api_key = api_key
        self.logs = logs
        self.opponent = opponent
        self.map_name = map_name
        self.allies_score = allies_score
        self.axis_score = axis_score

        self.duration = logs[1].event_time - logs[0].event_time

        self.add_item(CallableSelect(
            self.winner_select,
            placeholder="Select the winner of the match...",
            options=[
                SelectOption(label=self.api_key.tag, value="1"),
                SelectOption(label=self.opponent.tag, value="2"),
            ]
        ))
    
    def get_embed(self):
        embed = discord.Embed(
            title=f"Match Overview - {self.map_name} ({format_dt(self.logs[0].event_time, 'f')})",
            description="We are currently filling in the details of your match. React to the dropdown below to fill in the remaining gaps."
        ).add_field(
            name="Result",
            value="\n".join([
                "Winner: ???",
                "Score: " + (
                    f"**{self.allies_score} - {self.axis_score}**"
                    if abs(self.allies_score - self.axis_score) != 5
                    else f"**{self.allies_score} - {self.axis_score} ({int(self.duration.total_seconds() // 60)} mins.)**"
                )
            ])
        ).add_field(
            name="Team 1 (You)",
            value="\n".join([
                f"Name: **{self.api_key.tag}**",
                "Faction: ???"
            ])
        ).add_field(
            name="Team 2 (Opponent)",
            value="\n".join([
                f"Name: **{self.opponent.tag}**",
                "Faction: ???"
            ])
        )
        return embed
    
    async def winner_select(self, interaction: Interaction, value: str):
        view = HSSSubmitSelectGameTypeView(self.api_key, self.logs, self.opponent, value[0] == "1", self.map_name, self.allies_score, self.axis_score)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

class HSSSubmitSelectGameTypeView(View):
    def __init__(self, api_key: HSSApiKey, logs: List[LogLine], opponent: HSSTeam, won: bool, map_name: str, allies_score: int, axis_score: int):
        super().__init__()
        self.api_key = api_key
        self.logs = logs
        self.opponent = opponent
        self.won = won
        self.map_name = map_name
        self.allies_score = allies_score
        self.axis_score = axis_score
    
        self.duration = logs[1].event_time - logs[0].event_time
        self.submitted = False

    @property
    def winning_faction(self):
        return "Allies" if self.allies_score > self.axis_score else "Axis"
    @property
    def losing_faction(self):
        return "Allies" if self.allies_score < self.axis_score else "Axis"
    
    def get_embed(self):
        embed = discord.Embed(
            title=f"Match Overview - {self.map_name} ({format_dt(self.logs[0].event_time, 'f')})",
            description="We are currently filling in the details of your match. React to the dropdown below to fill in the remaining gaps."
        ).add_field(
            name="Result",
            value="\n".join([
                f"Winner: **{self.api_key.tag if self.won else self.opponent.tag}**",
                "Score: " + (
                    f"**{self.allies_score} - {self.axis_score}**"
                    if abs(self.allies_score - self.axis_score) != 5
                    else f"**{self.allies_score} - {self.axis_score} ({int(self.duration.total_seconds() // 60)} mins.)**"
                )
            ])
        ).add_field(
            name="Team 1 (You)",
            value="\n".join([
                f"Name: **{self.api_key.tag}**",
                f"Faction: **{self.winning_faction if self.won else self.losing_faction}**"
            ])
        ).add_field(
            name="Team 2 (Opponent)",
            value="\n".join([
                f"Name: **{self.opponent.tag}**",
                f"Faction: **{self.losing_faction if self.won else self.winning_faction}**"
            ])
        )
        return embed

    @discord.ui.select(
        placeholder="Select what type of match this was...",
        options=[
            SelectOption(value="friendly", label="Friendly", description="A friendly scrim of which the outcome doesn't matter as much"),
            SelectOption(value="competitive", label="Tournament Match", description="A competitive match with both teams playing at their best"),
        ]
    )
    async def game_type_select(self, interaction: Interaction, select: Select):
        game_type = select.values[0]
        view = HSSSubmitConfirmationView(self.api_key, self.logs, self.opponent, self.won, game_type, self.map_name, self.allies_score, self.axis_score)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

class HSSSubmitConfirmationView(View):
    def __init__(self, api_key: HSSApiKey, logs: List[LogLine], opponent: HSSTeam, won: bool, game_type: str, map_name: str, allies_score: int, axis_score: int):
        super().__init__()
        self.api_key = api_key
        self.logs = logs
        self.opponent = opponent
        self.won = won
        self.game_type = game_type
        self.map_name = map_name
        self.allies_score = allies_score
        self.axis_score = axis_score
    
        self.duration = logs[1].event_time - logs[0].event_time
        self.submitted = False

    @property
    def winning_faction(self):
        return "Allies" if self.allies_score > self.axis_score else "Axis"
    @property
    def losing_faction(self):
        return "Allies" if self.allies_score < self.axis_score else "Axis"
    
    def get_embed(self):
        embed = discord.Embed(
            title=f"Match Overview - {self.map_name} ({format_dt(self.logs[0].event_time, 'f')}) [`{self.game_type.capitalize()}`]"
        ).add_field(
            name="Result",
            value="\n".join([
                f"Winner: **{self.api_key.tag if self.won else self.opponent.tag}**",
                "Score: " + (
                    f"**{self.allies_score} - {self.axis_score}**"
                    if abs(self.allies_score - self.axis_score) != 5
                    else f"**{self.allies_score} - {self.axis_score} ({int(self.duration.total_seconds() // 60)} mins.)**"
                )
            ])
        ).add_field(
            name="Team 1 (You)",
            value="\n".join([
                f"Name: **{self.api_key.tag}**",
                f"Faction: **{self.winning_faction if self.won else self.losing_faction}**"
            ])
        ).add_field(
            name="Team 2 (Opponent)",
            value="\n".join([
                f"Name: **{self.opponent.tag}**",
                f"Faction: **{self.losing_faction if self.won else self.winning_faction}**"
            ])
        )
        return embed

    @discord.ui.button(label="Confirm & Submit", style=ButtonStyle.green)
    async def confirm_button(self, interaction: Interaction, button: ui.Button):
        if self.submitted:
            raise CustomException(
                "Statistics already submitted!",
                (
                    "These statistics have already been or currently are being submitted."
                    " If you haven't received a confirmation, try again in a second."
                )
            )
        else:
            self.submitted = True

            try:
                await interaction.response.defer(ephemeral=True)

                converter = ExportFormats.csv.value
                fp = StringIO(converter.convert_many(self.logs))
                match_id = await interaction.client.hss.submit_match(
                    api_key=self.api_key,
                    opponent=self.opponent,
                    won=self.won,
                    kind=self.game_type,
                    submitting_user=interaction.user,
                    csv_export=fp,
                )
                await interaction.followup.send(embed=get_success_embed(
                    "Match submitted to HeLO",
                    f"Your {self.game_type} match against {self.opponent} has been submitted to the HLL Skill System (ID: #{match_id})"
                ))
                
            except:
                self.submitted = False
                raise

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

            async def ask_export_format(_, range: Union[ExportRange, None], range_i: Union[int, None]):
                range = range or ExportRange()

                @only_once
                async def send_logs(_interaction: Interaction, format: List[str]):
                    await _interaction.response.defer()

                    logs = session.get_logs(
                        from_=range.start_time,
                        to=range.unload_time,
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

                        if range.start_time and range.has_end_time:
                            # The full match was recorded
                            view = HSSSubmitPromptView(session.get_logs(from_=range.start_time, to=range.unload_time), _interaction.user)
                            view.message = await _interaction.followup.send(content=content, file=file, view=view, wait=True)
                        else:
                            await interaction.followup.send(content=content, file=file)

                        await interaction.delete_original_response()
                    
                    else:
                        await interaction.edit_original_response(
                            content=None,
                            embed=get_error_embed(
                                title="Couldn't export logs!",
                                description="No logs were found matching the given criteria"
                            ),
                            view=None
                        )

                view = View(timeout=300.0)
                view.add_item(CallableSelect(send_logs,
                                             placeholder="Select an export format...",
                                             options=[SelectOption(label=format.name,
                                                                   description=f"A .{format.value.ext()} file")
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
        async def send_scoreboard(_interaction: Interaction, range: Union[ExportRange, None], match_index: Union[int, None]):
            logs = session.get_logs()
            if not logs:
                raise CustomException(
                    "Invalid range!",
                    "No logs match the given criteria"
                )

            match_data = MatchGroup.from_logs(logs)
            if range:
                match_data = match_data.matches[match_index]
            scoreboard = create_scoreboard(match_data)

            fp = StringIO(scoreboard)
            file = discord.File(fp, filename=f'{session.name} scores.txt')

            content = f"Scoreboard for **{esc_md(session.name)}**"
            if range and range.map_name:
                content += f" ({range.map_name})"
            
            if range.start_time and range.has_end_time:
                # A full match was recorded
                view = HSSSubmitPromptView(session.get_logs(from_=range.start_time, to=range.unload_time), _interaction.user)
                view.message = await interaction.followup.send(content=content, file=file, view=view, wait=True)
            else:
                await interaction.followup.send(content=content, file=file)

            await interaction.delete_original_response()

        view = ExportRangeSelectView(interaction, send_scoreboard, logs)
        await interaction.response.send_message(
            content="Select a specific match to export a scoreboard from by selecting it from the dropdown",
            view=view, ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(exports(bot))
