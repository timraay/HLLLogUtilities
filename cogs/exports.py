from datetime import datetime
from io import StringIO
from typing import List, Optional

import discord
from discord import app_commands, Interaction, ui, ButtonStyle, SelectOption
from discord.ext import commands
from discord.ui import Select
from discord.utils import escape_markdown as esc_md, format_dt
from pydantic import BaseModel

from cogs.sessions import autocomplete_sessions
from cogs.credentials import SECURITY_URL
from cogs.apikeys import HSSApiKeysModal
from discord_utils import CallableButton, CallableSelect, View, CustomException, get_error_embed, get_success_embed
from lib.converters import ExportFormats, Converter
from lib.hss.api_key import api_keys_in_guild_ttl, HSSApiKey, HSSTeam
from lib.rcon.models import EventTypes
from lib.flags import EventFlags
from lib.mappings import get_map_and_mode, parse_layer
from lib.scores import MatchGroup
from lib.session import HLLCaptureSession, SESSIONS
from lib.storage import LogLine

class ExportRange(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    unload_time: Optional[datetime] = None
    map_name: Optional[str] = None

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
    
    def is_eligible_for_helo(self):
        return self.start_time and self.has_end_time

def get_ranges(logs):
    flags = EventFlags(server_match_start=True, server_match_end=True, server_map_change=True)
    ranges = [ExportRange()]
    for log in flags.filter_logs(logs):
        try:
            log_type = EventTypes(log.event_type)
        except ValueError:
            continue

        if log_type == EventTypes.server_match_end:
            ranges[-1].end_time = log.event_time
            if not ranges[-1].map_name:
                ranges[-1].map_name = " ".join(get_map_and_mode(log.new))

        elif log_type == EventTypes.server_match_start:
            ranges[-1].unload_time = log.event_time
            ranges.append(ExportRange(
                start_time=log.event_time,
                map_name=" ".join(get_map_and_mode(log.new))
            ))

        # TODO: Re-enable after U18 hotfix or U19 release, once `server.map` returns the layer name again
        # elif log_type == EventTypes.server_map_change:
        #     if not ranges[-1].start_time:
        #         last_start = None
        #     else:
        #         last_start = (log.event_time - ranges[-1].start_time).total_seconds()

        #     if len(ranges) >= 2 and last_start and last_start < 30:
        #         # The line appeared after the server_match_started event
        #         ranges[-2].map_name = parse_layer(log.old).pretty()
        #         ranges[-1].map_name = parse_layer(log.new).pretty()
            
        #     elif not last_start or last_start > 60:
        #         # The line appeared before the server_match_started event
        #         ranges[-1].map_name = parse_layer(log.old).pretty()

    if len(ranges) == 1:
        ranges.clear()

    return ranges


class ExportView(View):
    flags_options = (
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

    def __init__(self, interaction: Interaction, session: HLLCaptureSession, as_scoreboard: bool = False):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.session = session
        self.as_scoreboard = bool(as_scoreboard)
        
        self.logs = session.get_logs()
        if not self.logs:
            raise CustomException(
                "Invalid session!",
                "This session doesn't hold any logs yet"
            )

        self._ranges = get_ranges(self.logs)
        self._range_index = None

        if self.as_scoreboard:
            self.scores = MatchGroup.from_logs(self.logs) 
        else:
            self.scores = None

        self.range = ExportRange()
        self.flags = EventFlags.all()
        self.format = ExportFormats.text

        # Add flags select

        if not self.as_scoreboard:
            self.add_item(CallableSelect(self.select_flags,
                placeholder="Select log types to include...",
                options=[
                    SelectOption(label=label, emoji=emoji, value=str(i), default=True)
                    for i, (label, emoji, _) in enumerate(self.flags_options)
                ],
                min_values=0,
                max_values=len(self.flags_options)
            ))

        # Add range select

        options = [SelectOption(label="Entire session", emoji="🕐", value="0", default=True)]
        for i, range in enumerate(self._ranges):

            description = "..."
            if range.start_time:
                description = range.start_time.strftime(range.start_time.strftime('%H:%Mh')) + description
            if range.has_end_time:
                description = description + range.shortest_end_time.strftime(range.shortest_end_time.strftime('%H:%Mh'))

            options.append(SelectOption(
                label=range.map_name or "Unknown",
                description=description,
                emoji="⏱️",
                value=str(i + 1)
            ))

        self.add_item(CallableSelect(self.select_range,
            placeholder="Select a time range...",
            options=options
        ))

        # Add format select

        self.add_item(CallableSelect(self.select_format,
            placeholder="Select a file format...",
            options=[
                SelectOption(
                    label=f"Export as .{format.value.ext()}",
                    description=f"A {format.name} file",
                    emoji="📑",
                    value=format.name,
                    default=format.name == "text"
                )
                for format in ExportFormats.__members__.values()
            ]
        ))
        
    async def send(self):
        await self.interaction.response.defer(thinking=True)
        content, file = self.get_message_payload()
        if file:
            await self.interaction.followup.send(content, file=file)
        else:
            await self.interaction.followup.send(content)

        await self.interaction.followup.send(
            content="Select any of the options to change the output above!",
            view=self,
            ephemeral=True
        )

    async def edit(self):
        content, file = self.get_message_payload()
        attachments = [file] if file else []
        await self.interaction.edit_original_response(content=content, attachments=attachments)

    def get_message_payload(self):
        self.logs = self.session.get_logs(
            from_=self.range.start_time,
            to=self.range.unload_time,
            filter=self.flags
        )

        content = f"{'Scoreboard' if self.as_scoreboard else 'Logs'} for **{esc_md(self.session.name)}**"
        if self.range.map_name:
            content += f" ({self.range.map_name})"
        if self.flags != self.flags.all():
            content += f"\n> Includes: **{'**, **'.join([option[0] for option in self.flags_options if option[2] <= self.flags])}**"

        file = None

        if self.logs:
            converter: Converter = self.format.value

            if self.as_scoreboard:
                if self._range_index is None:
                    match_data = self.scores
                else:
                    match_data = self.scores.matches[self._range_index]

                fp = StringIO(converter.create_scoreboard(match_data))
                file = discord.File(fp, filename=self.session.name + '.' + converter.ext())

            else:
                fp = StringIO(converter.convert_many(self.logs))
                file = discord.File(fp, filename=self.session.name + '.' + converter.ext())

        else:
            content += '\n```\nNo logs match the given criteria!\n```'
        
        return content, file

    async def select_range(self, interaction: Interaction, values: List[str]):
        range_i = int(values[0])
        if range_i:
            self._range_index = range_i - 1
            self.range = self._ranges[self._range_index]
        else:
            self._range_index = None
            self.range = ExportRange()

        await interaction.response.defer()
        await self.edit()

        if self.range.is_eligible_for_helo() and range_i not in self.session.sent_helo_prompt_indices:
            view = HeLOSubmitPromptView(self.session.get_logs(from_=self.range.start_time, to=self.range.unload_time), self.interaction.user)
            view.message = await interaction.followup.send(content=f"The above match (**{esc_md(self.session.name)}**) may be submitted to HeLO!", view=view, ephemeral=True, wait=True)
            self.session.sent_helo_prompt_indices.append(range_i)
    
    async def select_flags(self, interaction: Interaction, values: List[str]):
        flags = EventFlags()
        for value in values:
            flags |= self.flags_options[int(value)][2]
        if not flags:
            flags = EventFlags.all()
        self.flags = flags
        await interaction.response.defer()
        await self.edit()

    async def select_format(self, interaction: Interaction, values: List[str]):
        self.format = ExportFormats[values[0]]
        await interaction.response.defer()
        await self.edit()

class ToHeLOExportView(View):
    def __init__(self, interaction: Interaction, session: HLLCaptureSession):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.session = session
        
        self.logs = session.get_logs()
        if not self.logs:
            raise CustomException(
                "Invalid session!",
                "This session doesn't hold any logs yet"
            )

        self._ranges = get_ranges(self.logs)
        self._range_index = None

        self.range = ExportRange()

        # Add range select

        options = [SelectOption(label="Select a match...", emoji="🕐", value="0", default=True)]
        for i, range in enumerate(self._ranges):

            description = "..."
            if range.start_time:
                description = range.start_time.strftime(range.start_time.strftime('%H:%Mh')) + description
            if range.has_end_time:
                description = description + range.shortest_end_time.strftime(range.shortest_end_time.strftime('%H:%Mh'))

            options.append(SelectOption(
                label=range.map_name or "Unknown",
                description=description,
                emoji="⏱️",
                value=str(i + 1)
            ))

        self.add_item(CallableSelect(self.select_range,
            placeholder="Select a time range...",
            options=options
        ))
        
        # Add HeLO submit button

        self.submit_button = CallableButton(self.submit_to_helo,
            style=ButtonStyle.green,
            label="Submit to HeLO",
            disabled=True,
        )
        self.add_item(self.submit_button)
        
    async def send(self):
        content, embed = self.get_message_payload()
        await self.interaction.response.send_message(
            content=content,
            embed=embed,
            view=self,
            ephemeral=True,
        )

    async def edit(self, interaction: Interaction):
        content, embed = self.get_message_payload()
        self.submit_button.disabled = not self.range.is_eligible_for_helo()
        await interaction.response.edit_message(content=content, embed=embed, view=self)

    def get_message_payload(self):
        self.logs = self.session.get_logs(
            from_=self.range.start_time,
            to=self.range.unload_time
        )

        content = f"Logs for **{esc_md(self.session.name)}**"
        if self.range.map_name:
            content += f" ({self.range.map_name})"

        embed = None

        if self.range.is_eligible_for_helo():
            end_log = next(log for log in self.logs if log.event_type == str(EventTypes.server_match_end))
            map_name = get_map_and_mode(end_log.new)[0]
            allies_score = int(end_log.message.split(' - ')[0])
            axis_score = int(end_log.message.split(' - ')[1])
            duration = self.logs[-1].event_time - self.logs[0].event_time
            
            embed = discord.Embed(
                title=f"{map_name} ({format_dt(self.logs[0].event_time, 'f')})",
                description="Score: " + (
                    f"**{allies_score} - {axis_score}**"
                    if abs(allies_score - axis_score) != 5
                    else f"**{allies_score} - {axis_score} ({int(duration.total_seconds() // 60)} mins.)**"
                ),
                color=discord.Color(7844437),
            )

        elif self.logs:
            embed = get_error_embed("Select a match that has been captured from start to finish!")

        else:
            content += '\n```\nNo logs match the given criteria!\n```'
        
        return content, embed

    async def select_range(self, interaction: Interaction, values: List[str]):
        range_i = int(values[0])
        if range_i:
            self._range_index = range_i - 1
            self.range = self._ranges[self._range_index]
        else:
            self._range_index = None
            self.range = ExportRange()

        await self.edit(interaction)

    async def submit_to_helo(self, interaction: Interaction):
        await send_hss_submit_prompt(interaction, self.logs)


async def send_hss_submit_prompt(interaction: Interaction, logs: List[LogLine]):
    api_keys = await api_keys_in_guild_ttl(interaction.guild.id)
    if not api_keys:
        view = HeLOSubmitPromptApiKeyView(logs)
    elif len(api_keys) == 1:
        teams = await interaction.client._hss_teams()
        view = HeLOSubmitSelectOpponentView(api_keys[0], logs, teams)
    else:
        view = HeLOSubmitSelectApiKeyView(api_keys, logs)
    embed = view.get_embed()
    await interaction.response.edit_message(content=None, embed=embed, view=view)

class HeLOSubmitPromptView(View):
    def __init__(self, logs: List[LogLine], user: discord.Member):
        super().__init__(timeout=60 * 10)
        self.logs = logs
        self.user = user
        self.message = None

        self.add_item(ui.Button(label="Learn more", url="https://helo-system.de/"))
    
    @discord.ui.button(label="Submit to HeLO", style=ButtonStyle.green)
    async def submit_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user != self.user and not interaction.channel.permissions_for(interaction.user).manage_guild:
            raise CustomException(
                "You are not allowed to use this!",
                "Only the author of the command and server admins may invoke this interaction"
            )

        await send_hss_submit_prompt(interaction, self.logs)

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)

class HeLOSubmitPromptApiKeyView(View):
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
    
    async def submit_form(self, interaction: Interaction, api_key: HSSApiKey):
        api_key.insert_in_db()
        teams = await interaction.client._hss_teams()
        view = HeLOSubmitSelectOpponentView(api_key, self.logs, teams)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)
    
class HeLOSubmitSelectOpponentView(View):
    def __init__(self, api_key: HSSApiKey, logs: List[LogLine], teams: List[HSSTeam]):
        super().__init__()
        self.api_key = api_key
        self.logs = logs

        end_log = next(log for log in logs if log.event_type == str(EventTypes.server_match_end))
        self.map_name = get_map_and_mode(end_log.new)[0]
        self.allies_score = int(end_log.message.split(' - ')[0])
        self.axis_score = int(end_log.message.split(' - ')[1])
        self.duration = logs[-1].event_time - logs[0].event_time

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
        view = HeLOSubmitSelectWinnerView(self.api_key, self.logs, team, self.map_name, self.allies_score, self.axis_score)
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
    
class HeLOSubmitSelectApiKeyView(View):
    def __init__(self, api_keys: List[HSSApiKey], logs: List[LogLine]):
        super().__init__()
        self.api_keys = api_keys
        self.logs = logs

        self.duration = logs[-1].event_time - logs[0].event_time
        
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
        view = HeLOSubmitSelectOpponentView(api_key, self.logs, teams)
        embed = view.get_embed()
        await interaction.edit_original_response(embed=embed, view=view)

class HeLOSubmitSelectWinnerView(View):
    def __init__(self, api_key: HSSApiKey, logs: List[LogLine], opponent: HSSTeam, map_name: str, allies_score: int, axis_score: int):
        super().__init__()
        self.api_key = api_key
        self.logs = logs
        self.opponent = opponent
        self.map_name = map_name
        self.allies_score = allies_score
        self.axis_score = axis_score

        self.duration = logs[-1].event_time - logs[0].event_time

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
        view = HeLOSubmitSelectGameTypeView(self.api_key, self.logs, self.opponent, value[0] == "1", self.map_name, self.allies_score, self.axis_score)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

class HeLOSubmitSelectGameTypeView(View):
    def __init__(self, api_key: HSSApiKey, logs: List[LogLine], opponent: HSSTeam, won: bool, map_name: str, allies_score: int, axis_score: int):
        super().__init__()
        self.api_key = api_key
        self.logs = logs
        self.opponent = opponent
        self.won = won
        self.map_name = map_name
        self.allies_score = allies_score
        self.axis_score = axis_score
    
        self.duration = logs[-1].event_time - logs[0].event_time
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
        view = HeLOSubmitConfirmationView(self.api_key, self.logs, self.opponent, self.won, game_type, self.map_name, self.allies_score, self.axis_score)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

class HeLOSubmitConfirmationView(View):
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
    
        self.duration = logs[-1].event_time - logs[0].event_time
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
        view = ExportView(interaction, session)
        await view.send()
        
    @ExportGroup.command(name="scoreboard", description="Export a scoreboard from a session")
    @app_commands.describe(
        session="A log capture session"
    )
    @app_commands.autocomplete(
        session=autocomplete_sessions
    )
    async def export_scoreboard(self, interaction: Interaction, session: int):
        session: HLLCaptureSession = SESSIONS[session]
        view = ExportView(interaction, session, as_scoreboard=True)
        await view.send()
        
    @ExportGroup.command(name="to_helo", description="Export a session to HeLO")
    @app_commands.describe(
        session="A log capture session"
    )
    @app_commands.autocomplete(
        session=autocomplete_sessions
    )
    async def export_scoreboard(self, interaction: Interaction, session: int):
        session: HLLCaptureSession = SESSIONS[session]
        view = ToHeLOExportView(interaction, session)
        await view.send()
        
async def setup(bot: commands.Bot):
    await bot.add_cog(exports(bot))
