"""
Modifier to log the player's stats when the player leaves the server.
"""

from datetime import datetime, timezone
from pydantic import BaseModel, validator

from .base import Modifier
from lib.storage import LogLine
from lib.info.events import on_player_leave_server
from lib.info.models import PlayerLeaveServerEvent, EventModel, EventTypes


class PlayerStatsModifier(Modifier):

    class Config:
        id = "player_stats"
        name = "Player Stats"
        description = "Logging of the player's stats on server leave event"

    @on_player_leave_server()
    async def log_player_stats(self, event: PlayerLeaveServerEvent):
        player = event.player

        log = LogPlayerStatsLine.from_event(event)
        log.type = "additional_info"
        log.event_time=datetime.now(tz=timezone.utc)
        log.message = f"player stats for player {player}"
        self.session._logs.append(log)



class LogPlayerStatsLine(BaseModel):
    event_time: datetime = None
    type: str = None
    player_name: str = None
    player_steamid: str = None
    player_team: str = None
    player_role: str = None
    player_stats: str = None
    team_name: str = None
    squad_name: str = None
    message: str = None

    @validator('player_team', 'team_name')
    def validate_team(cls, v):
        if v not in {'Allies', 'Axis'}:
            raise ValueError("%s is not a valid team name" % v)
        return v
    @validator('player_steamid')
    def validate_steamid(cls, v):
        try:
            if len(v) != 17:
                raise ValueError('Unexpected SteamID size')
            int(v)
        except:
            raise ValueError("%s is not a valid Steam64ID" % v)
        return v
    
    @classmethod
    def from_event(cls, event: EventModel):
        player = event.get('player')
        squad = event.get('squad') or (player.get('squad') if player else None)
        team = event.get('team') or (squad.get('team') if squad else None) or (player.get('team') if player else None)
        
        payload = dict()
        if player:
            player_team = player.get('team', team)
            payload.update(
                player_name=player.name,
                player_steamid=player.steamid,
                player_team=player_team.name if player_team else None,
                player_role=player.get('role'),
                # add stats
                player_stats=player.get('score')
            )
        if team:
            payload['team_name'] = team.name
        if squad:
            payload['squad_name'] = squad.name
        
        payload['message'] = event.get('message')

        payload.setdefault('type', str(EventTypes(event.__class__)))
        return cls(event_time=event.event_time, **{k: v for k, v in payload.items() if v is not None})
