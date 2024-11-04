from pydantic import BaseModel, validator
from datetime import datetime
from pypika import Table, Query, Column
import sqlite3
import logging

from lib.info.models import *

DB_VERSION = 6
HLU_VERSION = "v2.2.10"

class LogLine(BaseModel):
    event_time: datetime = None
    type: str = None
    player_name: str = None
    player_steamid: str = None
    player_team: str = None
    player_role: str = None
    player_combat_score: int = None
    player_offense_score: int = None
    player_defense_score: int = None
    player_support_score: int = None
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
    # @validator('player_steamid', 'player2_steamid')
    # def validate_steamid(cls, v):
    #     try:
    #         if len(v) != 17:
    #             raise ValueError('Unexpected SteamID size')
    #         int(v)
    #     except:
    #         raise ValueError("%s is not a valid Steam64ID" % v)
    #     return v
    
    @classmethod
    def from_event(cls, event: EventModel):
        player = event.get('player')
        player2 = event.get('other')
        squad = event.get('squad') or (player.get('squad') if player else None)
        team = event.get('team') or (squad.get('team') if squad else None) or (player.get('team') if player else None)

        old = event.get('old')
        new = event.get('new') or event.get('map')
        message = event.get('message')

        if isinstance(event, SquadLeaderChangeEvent):
            player = event.new
            player2 = event.old
            old = None
            new = None
        elif isinstance(event, (PlayerSwitchSquadEvent, PlayerSwitchTeamEvent)):
            old = event.old.name if event.old else None
            new = event.new.name if event.new else None
        elif isinstance(event, PlayerScoreUpdateEvent):
            # Bit confusing, but cba to add two new columns to the table for this event alone
            new = event.player.get('kills', 0)
            message = event.player.get('deaths', 0)
        elif isinstance(event, (ServerMatchEndedEvent, ObjectiveCaptureEvent)):
            message = event.score
        
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
            if player.has('score'):
                payload.update(
                    player_combat_score=player.score.combat,
                    player_offense_score=player.score.offense,
                    player_defense_score=player.score.defense,
                    player_support_score=player.score.support,
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
        payload['message'] = message
        
        payload['weapon'] = event.get('weapon')

        payload.setdefault('type', str(EventTypes(event.__class__)))
        return cls(event_time=event.event_time, **{k: v for k, v in payload.items() if v is not None})

    @staticmethod
    def _get_create_query(table_name: str, _explicit_fields: Sequence = None):
        if _explicit_fields:
            field_names = list(_explicit_fields)
        else:
            field_names = [field.name for field in LogLine.__fields__.values()]

        # I really need to look into a better way to do this at some point
        exceptions = dict(
            player_combat_score='INTEGER',
            player_offense_score='INTEGER',
            player_defense_score='INTEGER',
            player_support_score='INTEGER',
        )
        query = Query.create_table(table_name).columns(*[
            Column(field_name, exceptions.get(field_name, 'TEXT')) for field_name in field_names
        ])
        return str(query)

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
CREATE TABLE IF NOT EXISTS "hss_api_keys" (
	"guild_id"	VARCHAR(18) NOT NULL,
	"tag"	VARCHAR(10) NOT NULL,
	"key"	VARCHAR(120)
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


def update_table_columns(table_name: str, old: list, new: list, defaults: dict = {}):
    table_name_new = table_name + "_new"

    # Create a new table with the proper columns
    cursor.execute(LogLine._get_create_query(table_name_new, _explicit_fields=new))
    # Copy over the values
    to_copy = [c for c in old if c in new]
    query = Query.into(table_name_new).columns(*to_copy).from_(table_name).select(*to_copy)
    cursor.execute(str(query))
    # Insert defaults
    defaults = {col: val for col, val in defaults.items() if col in new and col not in old}
    if defaults:
        query = Query.update(table_name_new)
        for col, val in defaults.items():
            query = query.set(col, val)
        cursor.execute(str(query))
    # Drop the old table
    cursor.execute(str(Query.drop_table(table_name)))
    # Rename the new table
    cursor.execute(f'ALTER TABLE "{table_name_new}" RENAME TO "{table_name}";')

    database.commit()

    added = [c for c in new if c not in old]
    removed = [c for c in old if c not in new]
    logging.info("Altered table %s: Added %s and removed %s", table_name, added, removed)

cursor.execute("SELECT format_version FROM db_version")
db_version: int = cursor.fetchone()[0]

# Very dirty way of doing this, I know
if db_version > DB_VERSION:
    logging.warn('Unrecognized database format version! Expected %s but got %s. Certain functionality may be broken. Did you downgrade versions?', DB_VERSION, db_version)
elif db_version < DB_VERSION:
    logging.info('Outdated database format version! Expected %s but got %s. Migrating now...', DB_VERSION, db_version)

    if db_version < 2:
        # Add a "modifiers" column to the "sessions" table
        cursor.execute('ALTER TABLE "sessions" ADD "modifiers" INTEGER DEFAULT 0 NOT NULL;')
    
    if db_version < 3:
        # Add "player_score_X" columns to all session logs tables
        cursor.execute('SELECT name FROM sqlite_master WHERE type = "table" AND name LIKE "session%";')
        for (table_name,) in cursor.fetchall():
            try:
                int(table_name[7:])
            except ValueError:
                if table_name.endswith('_new'):
                    logging.warning('Found table with name %s, you will likely need to manually delete it', table_name)
                continue

            update_table_columns(table_name,
                old=['event_time', 'type', 'player_name', 'player_steamid', 'player_team', 'player_role', 'player2_name', 'player2_steamid',
                     'player2_team', 'player2_role', 'weapon', 'old', 'new', 'team_name', 'squad_name', 'message'],
                new=['event_time', 'type', 'player_name', 'player_steamid', 'player_team', 'player_role', 'player_combat_score',
                     'player_offense_score', 'player_defense_score', 'player_support_score', 'player2_name', 'player2_steamid', 'player2_team',
                     'player2_role', 'weapon', 'old', 'new', 'team_name', 'squad_name', 'message']
            )
    
    if db_version < 4:
        # Add a "default_modifiers" column to the "credentials" table
        cursor.execute('ALTER TABLE "credentials" ADD "default_modifiers" INTEGER DEFAULT 0 NOT NULL;')

    if db_version < 5:
        # Add a "autosession_enabled" column to the "credentials" table
        cursor.execute('ALTER TABLE "credentials" ADD "autosession_enabled" BOOLEAN NOT NULL CHECK ("autosession_enabled" IN (0, 1)) DEFAULT 0;')

        # Remove NOT NULL constraint from "end_time" column of the "sessions" table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS "sessions_new" (
            "guild_id"	INTEGER NOT NULL,
            "name"	VARCHAR(40) NOT NULL,
            "start_time"	VARCHAR(30) NOT NULL,
            "end_time"	VARCHAR(30),
            "deleted"	BOOLEAN NOT NULL CHECK ("deleted" IN (0, 1)) DEFAULT 0,
            "credentials_id"	INTEGER,
            "modifiers" INTEGER DEFAULT 0 NOT NULL,
            FOREIGN KEY(credentials_id) REFERENCES credentials(ROWID) ON DELETE SET NULL
        );
        """)
        cursor.execute('INSERT INTO "sessions_new" SELECT * FROM "sessions";')
        cursor.execute(str(Query.drop_table("sessions")))
        cursor.execute('ALTER TABLE "sessions_new" RENAME TO "sessions";')

    if db_version < 6:
        # Create a new table with the proper columns
        table_name = 'hss_api_keys'
        table_name_new = f'{table_name}_new'
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS "{table_name_new}" (
                "guild_id"	VARCHAR(18) NOT NULL,
                "tag"	VARCHAR(10) NOT NULL,
                "key"	VARCHAR(120)
            );
            """)
        # Copy over the values
        to_copy = ['guild_id', 'tag', 'key']
        query = Query.into(table_name_new).columns(*to_copy).from_(table_name).select(*to_copy)
        cursor.execute(str(query))
        # Drop the old table
        cursor.execute(str(Query.drop_table(table_name)))
        # Rename the new table
        cursor.execute(f'ALTER TABLE "{table_name_new}" RENAME TO "{table_name}";')

        database.commit()


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
