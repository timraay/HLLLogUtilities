from pydantic import BaseModel, validator
from datetime import datetime, timedelta
from pypika import Table, Query
import sqlite3

from typing import Union

from lib.info_types import *


class LogLine(BaseModel):
    event_time: datetime = None
    type: str = None
    player_name: str = None
    player_steamid: str = None
    player_team: str = None
    player_role: str = None
    player2_name: str = None
    player2_steamid: str = None
    player2_team: str = None
    player2_role: str = None
    weapon: str = None
    old: str = None
    new: str = None
    team_name: str = None
    squad_name: str = None
    message: str = None

    @validator('player_team', 'player2_team', 'team_name')
    def validate_team(cls, v):
        if v not in {'Allies', 'Axis'}:
            raise ValueError("%s is not a valid team name" % v)
        return v
    @validator('player_steamid', 'player2_steamid')
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
        player2 = event.get('other')
        squad = event.get('squad') or (player.get('squad') if player else None)
        team = event.get('team') or (squad.get('team') if squad else None) or (player.get('team') if player else None)

        if isinstance(event, SquadLeaderChangeEvent):
            player = event.new
            player2 = event.old
            old = None
            new = None
        else:
            old = event.get('old')
            new = event.get('new')
        
        if isinstance(event, PlayerMessageEvent):
            if isinstance(event.channel, Squad):
                squad = event.channel
                team = event.channel.team
            else:
                team = event.channel
        
        payload = dict()
        if player:
            player_team = player.get('team', team)
            payload.update(
                player_name=player.name,
                player_steamid=player.steamid,
                player_team=player_team.name if player_team else None,
                player_role=player.get('role'),
            )
        if player2:
            player2_team = player2.get('team')
            payload.update(
                player2_name=player2.name,
                player2_steamid=player2.steamid,
                player2_team=player2_team.name if player2_team else None,
                player2_role=player2.get('role'),
            )
        if team:
            payload['team_name'] = team.name
        if squad:
            payload['squad_name'] = squad.name
        payload['old'] = old
        payload['new'] = new
        
        payload['weapon'] = event.get('weapon')

        payload.setdefault('type', str(EventTypes(event.__class__)))
        return cls(event_time=event.event_time, **{k: v for k, v in payload.items() if v is not None})

database = sqlite3.connect('sessions.db')
cursor = database.cursor()

def insert_many_logs(sess_id: int, logs: Sequence['LogLine']):
    sess_name = f"session{int(sess_id)}"
    table = Table(sess_name)

    # Insert the logs
    insert_query = table
    for log in logs:
        insert_query = insert_query.insert(*log.dict().values())
    cursor.execute(str(insert_query))
    
    database.commit()

def delete_logs(sess_id: int):
    sess_name = f"session{int(sess_id)}"

    # Drop the table
    drop_query = Query.drop_table(sess_name)
    cursor.execute(str(drop_query))
    
    database.commit()