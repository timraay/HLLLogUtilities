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
    player2_name: str = None
    player2_steamid: str = None
    player2_team: str = None
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
        if isinstance(event, SquadLeaderChangeEvent):
            payload = dict(
                player_name=event.new.name,
                player_steamid=event.new.steamid,
                player_team=event.new.team.name,
                player2_name=event.old.name,
                player2_steamid=event.old.steamid,
                player2_team=event.old.team.name,
                team_name=event.squad.team.name,
                squad_name=event.squad.name
            )
        elif isinstance(event, PlayerMessageEvent):
            payload = dict(
                player_name=event.player.name,
                player_steamid=event.player.steamid,
                player_team=event.player.team.name,
            )
            if isinstance(event.channel, Squad):
                payload['team_name'] = event.channel.team.name
                payload['squad_name'] = event.channel.name
            else:
                payload['team_name'] = event.channel.name
        
        else:
            payload = dict()
            if event.get('player'):
                payload = {**payload, **dict(
                    player_name=event.player.name,
                    player_steamid=event.player.steamid,
                    player_team=event.player.team.name,
                )}
            if event.get('other'):
                payload = {**payload, **dict(
                    player2_name=event.other.name,
                    player2_steamid=event.other.steamid,
                    player2_team=event.other.team.name,
                )}
            if event.get('team'):
                payload['team_name'] = event.team.name
            if event.get('squad'):
                payload['squad_name'] = event.team.name
            if event.get('item'):
                payload['weapon'] = event.item
            if event.get('old'):
                payload['old'] = event.old
            if event.get('new'):
                payload['new'] = event.new

        payload.setdefault('type', str(EventTypes(event.__class__)))
        return cls(event_time=event.event_time, **payload)

database = sqlite3.connect('sessions.db')
cursor = database.cursor()

def insert_many_logs(sess_id: int, logs: Sequence['LogLine']):
    sess_name = f"session{int(sess_id)}"
    table = Table(sess_name)

    # Insert the logs
    insert_query = table
    for log in logs:
        insert_query.insert(*log.dict().values())
    cursor.execute(str(insert_query))
    
    database.commit()

def delete_logs(sess_id: int):
    sess_name = f"session{int(sess_id)}"

    # Drop the table
    drop_query = Query.drop_table(sess_name)
    cursor.execute(str(drop_query))
    
    database.commit()