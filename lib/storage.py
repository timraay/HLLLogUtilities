import logging
from pypika import Table, Query
import sqlite3
from typing import Sequence

from lib.logs import LogLine

DB_VERSION = 7
HLU_VERSION = "v2.2.12"

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


def rename_table_columns(table_name: str, old: list[str], new: list[str]):
    if len(old) != len(new):
        raise ValueError("Old and new column lists must be of the same length")

    table_name_new = table_name + "_new"

    # Create a new table with the proper columns
    cursor.execute(LogLine._get_create_query(table_name_new, _explicit_fields=new))
    # Copy over the values
    query = Query.into(table_name_new).columns(*new).from_(table_name).select(*old)
    cursor.execute(str(query))
    # Drop the old table
    cursor.execute(str(Query.drop_table(table_name)))
    # Rename the new table
    cursor.execute(f'ALTER TABLE "{table_name_new}" RENAME TO "{table_name}";')

    database.commit()

    added = [c for c in new if c not in old]
    removed = [c for c in old if c not in new]
    logging.info("Altered table %s: Added %s and removed %s", table_name, added, removed)


def update_table_columns(table_name: str, old: list[str], new: list[str], defaults: dict = {}):
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
                old=['event_time', 'type', 'player_name', 'player_id', 'player_team', 'player_role', 'player2_name', 'player2_id',
                     'player2_team', 'player2_role', 'weapon', 'old', 'new', 'team_name', 'squad_name', 'message'],
                new=['event_time', 'type', 'player_name', 'player_id', 'player_team', 'player_role', 'player_combat_score',
                     'player_offense_score', 'player_defense_score', 'player_support_score', 'player2_name', 'player2_id', 'player2_team',
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

    if db_version < 7:
        # Rename "player_steamid" and "player2_steamid" columns to "player_id" and "player2_id" respectively in all session logs tables
        cursor.execute('SELECT name FROM sqlite_master WHERE type = "table" AND name LIKE "session%";')
        for (table_name,) in cursor.fetchall():
            try:
                int(table_name[7:])
            except ValueError:
                if table_name.endswith('_new'):
                    logging.warning('Found table with name %s, you will likely need to manually delete it', table_name)
                continue

            rename_table_columns(table_name,
                old=['event_time', 'type', 'player_name', 'player_steamid', 'player_team', 'player_role', 'player_combat_score',
                     'player_offense_score', 'player_defense_score', 'player_support_score', 'player2_name', 'player2_steamid', 'player2_team',
                     'player2_role', 'weapon', 'old', 'new', 'team_name', 'squad_name', 'message'],
                new=['event_time', 'event_type', 'player_name', 'player_id', 'player_team', 'player_role', 'player_combat_score',
                     'player_offense_score', 'player_defense_score', 'player_support_score', 'player2_name', 'player2_id', 'player2_team',
                     'player2_role', 'weapon', 'old', 'new', 'team_name', 'squad_name', 'message']
            )

    cursor.execute('UPDATE "db_version" SET "format_version" = ?', (DB_VERSION,))
    database.commit()
    logging.info('Migrated database to format version %s!', DB_VERSION)


def insert_many_logs(sess_id: int, logs: Sequence['LogLine'], sort: bool = True):
    sess_name = f"session{int(sess_id)}"
    table = Table(sess_name)

    if sort:
        logs = sorted(logs, key=lambda log: log.event_time)

    # Insert the logs
    insert_query = table
    for log in logs:
        insert_query = insert_query.insert(*log.model_dump().values())
    cursor.execute(str(insert_query))
    
    database.commit()

def delete_logs(sess_id: int):
    sess_name = f"session{int(sess_id)}"

    # Drop the table
    drop_query = Query.drop_table(sess_name)
    cursor.execute(str(drop_query))
    
    database.commit()
