from inspect import isfunction
import json
from typing import List

from lib.storage import LogLine

class Converter:
    player_join_server=...
    player_leave_server=...
    player_death=...
    player_teamkill=...
    player_join_team=...
    player_leave_team=...
    player_join_squad=...
    player_leave_squad=...
    squad_leader_change=...
    player_change_role=...
    player_change_loadout=...
    player_enter_admin_cam=...
    player_exit_admin_cam=...
    player_message=...
    player_level_up=...
    server_state_changed=...
    server_map_changed=...

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
    player_join_team        = "TEAM JOINED         \t{player_name} ({player_steamid}) joined team {team_name}"
    player_leave_team       = "TEAM LEFT           \t{player_name} ({player_steamid}) left team {team_name}"
    squad_created           = "UNIT CREATED        \tUnit {squad_name} created on team {team_name}"
    player_join_squad       = "UNIT JOINED         \t{player_name} ({player_team}/{player_steamid}) joined unit {squad_name}"
    player_leave_squad      = "UNIT LEFT           \t{player_name} ({player_team}/{player_steamid}) left unit {squad_name}"
    squad_leader_change     = "OFFICER CHANGED     \tOfficer for {squad_name}: {player_name} -> {player2_name} ({team_name})"
    squad_created           = "UNIT DISBANDED      \tUnit {squad_name} disbanded on team {team_name}"
    player_change_role      = "ROLE CHANGED        \t{player_name} ({player_team}/{player_steamid}) changed role: {old} -> {new}"
    player_change_loadout   = "LOADOUT CHANGED     \t{player_name} ({player_team}/{player_steamid}) changed loadout: {old} -> {new}"
    player_enter_admin_cam  = "ADMIN CAM ENTERED   \t{player_name} ({player_team}/{player_steamid}) entered admin cam"
    player_exit_admin_cam   = "ADMIN CAM EXITED    \t{player_name} ({player_team}/{player_steamid}) exited admin cam"
    player_level_up         = "LEVELUP             \t{player_name} ({player_steamid}) leveled up: {old} -> {new}"
    server_map_changed      = "MAP CHANGED         \tMap changed from {old} to {new}"
    server_state_changed    = "GAME STATE CHANGED  \tGame state changed from {old} to {new}"

    @staticmethod
    def player_message(log: 'LogLine'):
        if log.squad_name:
            return f"[{log.team_name}][{log.squad_name}]"
        else:
            return f"[{log.team_name}]"
    
    @classmethod
    def convert(cls, log: 'LogLine'):
        out = super().convert(log)
        if out is not None:
            out = log.event_time.strftime('%H%M%S - %a, %b %-d\t') + out
        return out


class CSVConverter(Converter):
    @classmethod
    def convert(cls, log: 'LogLine'):
        values = [('"'+str(val)+'"' if ',' in str(val) else str(val)) for val in log.dict().values()]
        return ",".join(values)
    
    @staticmethod
    def header():
        return ",".join(LogLine.__fields__.keys())

class JSONConverter(Converter):
    @classmethod
    def convert(cls, log: 'LogLine'):
        return log.dict()
    
    @classmethod
    def convert_many(cls, logs: List['LogLine'], include_header=True):
        converted = [log for log in [cls.convert(log) for log in logs] if log is not None]
        obj = dict(logs=converted)
        return json.dumps(obj, indent=2)
