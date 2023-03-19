from pydantic import BaseModel, validator
from datetime import datetime, timedelta
from pypika import Table, Query
import sqlite3
import logging

from lib.info.models import *

DB_VERSION = 2
HLU_VERSION = "v1.4.0"

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
        elif isinstance(event, (PlayerSwitchSquadEvent, PlayerSwitchTeamEvent)):
            old = event.old.name if event.old else None
            new = event.new.name if event.new else None
        else:
            old = event.get('old')
            new = event.get('new') or event.get('map')
        
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
        
        payload['message'] = event.score if isinstance(event, (ServerMatchEnded, ObjectiveCaptureEvent)) else event.get('message')
        payload['weapon'] = event.get('weapon')

        payload.setdefault('type', str(EventTypes(event.__class__)))
        return cls(event_time=event.event_time, **{k: v for k, v in payload.items() if v is not None})

database = sqlite3.connect('sessions.db')
cursor = database.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS "db_version" (
	"format_version"	INTEGER DEFAULT 1 NOT NULL
);
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS "credentials" (
	"guild_id"	VARCHAR(18) NOT NULL,
	"name"	VARCHAR(80) NOT NULL,
	"address"	VARCHAR(25),
	"port"	INTEGER,
	"password"	VARCHAR(50)
);
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS "sessions" (
	"guild_id"	INTEGER NOT NULL,
	"name"	VARCHAR(40) NOT NULL,
	"start_time"	VARCHAR(30) NOT NULL,
	"end_time"	VARCHAR(30) NOT NULL,
	"deleted"	BOOLEAN NOT NULL CHECK ("deleted" IN (0, 1)) DEFAULT 0,
	"credentials_id"	INTEGER,
    FOREIGN KEY(credentials_id) REFERENCES credentials(ROWID) ON DELETE SET NULL
);
""")

cursor.execute("""
INSERT INTO "db_version" ("format_version")
    SELECT 1 WHERE NOT EXISTS(
        SELECT 1 FROM "db_version"
    );
""")

database.commit()

cursor.execute("SELECT format_version FROM db_version")
db_version: int = cursor.fetchone()[0]

# Very dirty way of doing this, I know
if db_version > DB_VERSION:
    logging.warn('Unrecognized database format version! Expected %s but got %s. Certain functionality may be broken. Did you downgrade versions?', DB_VERSION, db_version)
elif db_version < DB_VERSION:
    logging.info('Outdated database format version! Expected %s but got %s. Migrating now...', DB_VERSION, db_version)

    if db_version < 2:
        cursor.execute('ALTER TABLE "sessions" ADD "modifiers" INTEGER DEFAULT 0 NOT NULL;')
    
    cursor.execute('UPDATE "db_version" SET "format_version" = ?', (DB_VERSION,))
    database.commit()
    logging.info('Migrated database to format version %s!', DB_VERSION)


def insert_many_logs(sess_id: int, logs: Sequence['LogLine'], sort: bool = True):
    sess_name = f"session{int(sess_id)}"
    table = Table(sess_name)

    if sort:
        logs = sorted(logs, key=lambda l: l.event_time)

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