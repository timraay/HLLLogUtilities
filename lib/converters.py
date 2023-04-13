from inspect import isfunction
import json
from enum import Enum
from datetime import datetime
from typing import List

from lib.storage import LogLine, HLU_VERSION

__all__ = (
    'ExportFormats',
    'TextConverter',
    'CSVConverter',
    'JSONConverter',
)

class Converter:
    player_join_server=...
    player_leave_server=...
    player_death=...
    player_teamkill=...
    player_suicide=...
    player_join_team=...
    player_leave_team=...
    squad_created=...
    player_join_squad=...
    player_leave_squad=...
    squad_leader_change=...
    squad_disbanded=...
    player_change_role=...
    player_change_loadout=...
    player_enter_admin_cam=...
    player_exit_admin_cam=...
    player_message=...
    player_level_up=...
    player_score_update=...
    server_state_changed=...
    server_map_changed=...

    rule_violated=...
    arty_assigned=...
    arty_unassigned=...
    start_arty_cooldown=...
    cancel_arty_cooldown=...


    @classmethod
    def convert(cls, log: 'LogLine'):
        converter = getattr(cls, log.type)
        if isfunction(converter):
            return str(converter(log))
        elif isinstance(converter, str):
            return str(converter.format(**log.dict()))
        else:
            return None

    @staticmethod
    def ext():
        return 'txt'
    
    @staticmethod
    def header():
        return None
    
    @classmethod
    def convert_many(cls, logs: List['LogLine'], include_header=True):
        lines = list()

        if include_header:
            header = cls.header()
            if header is not None:
                lines.append(str(header))
        
        for log in logs:
            line = cls.convert(log)
            if line is not None:
                lines.append(str(line))
        
        return "\n".join(lines)

class TextConverter(Converter):
    player_join_server      = "CONNECTED           \t{player_name} ({player_steamid})"
    player_leave_server     = "DISCONNECTED        \t{player_name} ({player_steamid})"
    player_kill             = "KILL                \t{player_name} ({player_team}/{player_steamid}) -> {player2_name} ({player2_team}/{player2_steamid}) with {weapon}"
    player_teamkill         = "TEAM KILL           \t{player_name} ({player_team}/{player_steamid}) -> {player2_name} ({player2_team}/{player2_steamid}) with {weapon}"
    player_suicide          = "SUICIDE             \t{player_name} ({player_team}/{player_steamid})"
    player_switch_team      = "TEAM SWITCHED       \t{player_name} ({player_steamid}): {old} -> {new}"
    squad_created           = "UNIT CREATED        \tUnit {squad_name} created on team {team_name}"
    player_switch_squad     = "UNIT SWITCHED       \t{player_name} ({team_name}/{player_steamid}): {old} -> {new}"
    squad_disbanded         = "UNIT DISBANDED      \tUnit {squad_name} disbanded on team {team_name}"
    player_change_role      = "ROLE CHANGED        \t{player_name} ({player_team}/{player_steamid}) changed role: {old} -> {new}"
    player_change_loadout   = "LOADOUT CHANGED     \t{player_name} ({player_team}/{player_steamid}) changed loadout: {old} -> {new}"
    player_enter_admin_cam  = "CAMERA ENTERED      \t{player_name} ({player_team}/{player_steamid}) entered admin cam"
    player_exit_admin_cam   = "CAMERA EXITED       \t{player_name} ({player_team}/{player_steamid}) exited admin cam"
    player_level_up         = "LEVELUP             \t{player_name} ({player_steamid}) leveled up: {old} -> {new}"
    player_score_update     = "PLAYER SCORE        \t{player_name} ({player_steamid}): {player_combat_score} C, {player_offense_score} O, {player_defense_score} D, {player_support_score} S (KD: {new}/{message})"
    objective_capture       = "OBJECTIVE CAPTURED  \t{team_name} captured an objective: ALLIED ({message}) AXIS"
    server_map_changed      = "MAP CHANGED         \tMap changed from {old} to {new}"
    server_match_started    = "MATCH START         \tMATCH START {new}"
    server_match_ended      = "MATCH ENDED         \tMATCH ENDED `{new}` ALLIED ({message}) AXIS"
    server_warmup_ended     = "WARMUP ENDED        \tWARMUP ENDED"

    arty_assigned           = "ARTILLERY ASSIGNED  \t{player_name} ({player_team}/{player_steamid}) with {weapon}: {message}"
    arty_unassigned         = "ARTILLERY UNASSIGNED\t{player_name} ({player_team}/{player_steamid}): {message}"
    start_arty_cooldown     = "COOLDOWN STARTED    \t{player_name} ({player_team}/{player_steamid}): {message}"
    cancel_arty_cooldown    = "COOLDOWN CANCELED   \t{player_name} ({player_steamid}): {message}"

    @staticmethod
    def player_message(log: 'LogLine'):
        if log.squad_name:
            return f"CHAT[{log.team_name}][{log.squad_name}]".ljust(20) + f"\t{log.player_name}: {log.message} ({log.player_steamid})"
        else:
            return f"CHAT[{log.team_name}]".ljust(20) + f"\t{log.player_name}: {log.message} ({log.player_steamid})"
    
    @staticmethod
    def squad_leader_change(log: 'LogLine'):
        p1 = f"{log.player_name} ({log.player_steamid})" if log.player_name is not None else "None"
        p2 = f"{log.player2_name} ({log.player2_steamid})" if log.player2_name is not None else "None"
        return "OFFICER CHANGED".ljust(20) + f"\tOfficer for {log.squad_name} ({log.team_name}): {p2} -> {p1}"
    
    @staticmethod
    def rule_violated(log: 'LogLine'):
        msg = "RULE VIOLATED".ljust(20) + f"\t{log.player_name} ({log.player_team}/{log.player_steamid})"
        if log.player2_name:
            msg += f" -> {log.player2_name} ({log.player2_team}/{log.player2_steamid})"
        if log.weapon:
            msg += f" with {log.weapon}"
        if log.message:
            msg += f": {log.message}"
        return msg
    
    @staticmethod
    def header():
        return f"-- Captured and exported using HLL Log Utilities {HLU_VERSION}"
    
    @classmethod
    def convert(cls, log: 'LogLine'):
        out = super().convert(log)
        if out is not None:
            out = log.event_time.strftime('%H:%M:%S - %a, %b %d\t') + out
        return out

    @classmethod
    def convert_many(cls, logs: List['LogLine'], include_header=True):
        lines = list()

        if include_header:
            lines.append(cls.header())
        
        for log in logs:
            line = cls.convert(log)
            if line is not None:
                lines.append(line)
        
        return "\n".join(lines)


class CSVConverter(Converter):
    @classmethod
    def convert(cls, log: 'LogLine'):
        values = list()
        values = ['"' + (str(val).replace('"', '\"') if val is not None else '') + '"' for val in log.dict().values()]
        return ",".join(values)
    
    @staticmethod
    def header():
        return ",".join(LogLine.__fields__.keys())
    
    @staticmethod
    def ext():
        return 'csv'

class JSONConverter(Converter):
    @staticmethod
    def ext():
        return 'json'

    @classmethod
    def convert(cls, log: 'LogLine'):
        return log.dict()
    
    @classmethod
    def convert_many(cls, logs: List['LogLine']):
        converted = [log for log in [cls.convert(log) for log in logs] if log is not None]
        obj = dict(
            start_time=logs[0].event_time if converted else None,
            end_time=logs[-1].event_time if converted else None,
            logs=converted
        )
        return json.dumps(obj, indent=2, default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x))



class ExportFormats(Enum):
    text = TextConverter
    csv = CSVConverter
    json = JSONConverter
