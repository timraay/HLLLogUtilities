import asyncio
from datetime import datetime, timedelta
from discord.ext import tasks
from pypika import Query, Table, Column
from typing import Union, Dict

from lib.rcon import HLLRcon
from lib.credentials import Credentials
from lib.storage import LogLine, database, cursor, insert_many_logs, delete_logs
from lib.exceptions import NotFound, SessionDeletedError, SessionAlreadyRunningError, SessionMissingCredentialsError
from utils import get_config, schedule_coro

NUM_LOGS_REQUIRED_FOR_INSERT = get_config().getint('Session', 'NumLogsRequiredForInsert')
DELETE_SESSION_AFTER = timedelta(days=get_config().getint('Session', 'DeleteAfterDays'))
SESSIONS: Dict[int, 'HLLCaptureSession'] = dict()

cursor.execute("""
CREATE TABLE IF NOT EXISTS "sessions" (
	"start_time"	VARCHAR(30) NOT NULL,
	"end_time"	VARCHAR(30) NOT NULL,
	"deleted"	BOOLEAN NOT NULL CHECK ("deleted" IN (0, 1)) DEFAULT 0,
	"credentials_id"	INTEGER,
    FOREIGN KEY(credentials_id) REFERENCES credentials(ROWID)
);""")
database.commit()

class HLLCaptureSession:
    def __init__(self, id: int, start_time: datetime, end_time: datetime, credentials: Credentials, loop: asyncio.AbstractEventLoop = None):
        self.id = id
        self.start_time = start_time
        self.end_time = end_time
        self.credentials = credentials
        self.loop = loop or asyncio.get_running_loop()
        self._logs = list()

        if self.id in SESSIONS:
            raise SessionAlreadyRunningError("A session with ID %s is already running")

        self.rcon = None
        
        if self.active_in():
            self.loop.create_task(schedule_coro(self.start_time, self.activate))
            self.loop.create_task(schedule_coro(self.end_time, self.deactivate))

        SESSIONS[self.id] = self
        
    @classmethod
    def load_from_db(cls, id: int):
        cursor.execute('SELECT ROWID, start_time, end_time, deleted, credentials_id FROM sessions WHERE ROWID = ?', (id,))
        res = cursor.fetchone()

        if not res:
            raise NotFound(f"No session exists with ID {id}")

        deleted = bool(res[3])
        if deleted:
            raise SessionDeletedError

        credentials_id = res[4]
        if credentials_id is None:
            credentials = None
        else:
            credentials = Credentials.load_from_db(credentials_id)

        return cls(
            id=int(res[0]),
            start_time=datetime.fromisoformat(res[1]),
            end_time=datetime.fromisoformat(res[2]),
            credentials=credentials
        )
    
    @classmethod
    def create_in_db(cls, start_time: datetime, end_time: datetime, credentials: Credentials):
        if datetime.utcnow() > end_time:
            raise ValueError('This capture session would have already ended')

        cursor.execute('INSERT INTO sessions (start_time, end_time, credentials_id) VALUES (?,?,?)', (start_time, end_time, credentials.id))
        id_ = cursor.lastrowid

        # Create the table if needed
        sess_name = f"session{id_}"
        table = Table(sess_name)
        create_table_query = Query.create_table(table).columns(*[
            Column(field.name, 'TEXT') for field in LogLine.__fields__.values()
        ])
        cursor.execute(str(create_table_query))
        database.commit()

        return cls(
            id=id_,
            start_time=start_time,
            end_time=end_time,
            credentials=credentials,
        )

    @property
    def duration(self):
        return self.end_time - self.start_time

    def active_in(self) -> Union[timedelta, bool]:
        """Returns how long until the session should start. Otherwise
        returns whether the session should currently be active or not.

        Returns
        -------
        Union[timedelta, bool]
            The time until the session should activate, otherwise
            whether it is currently active.
        """
        now = datetime.utcnow()
        if self.start_time > now:
            return now - self.start_time
        else:
            return self.end_time > now
    
    def should_delete(self):
        return datetime.utcnow() > (self.end_time + DELETE_SESSION_AFTER)

    async def activate(self):
        if not self.credentials:
            raise SessionMissingCredentialsError(f"Session with ID {self.id} does not have server credentials")
        if self.rcon is None:
            self.rcon = HLLRcon(credentials=self.credentials, loop=self.loop)
        self.gatherer.start()
    async def deactivate(self):
        self.gatherer.stop()

    @tasks.loop(seconds=5)
    async def gatherer(self):
        info = await self.rcon.update()
        for event in info.events.flatten():
            try:
                log = LogLine.from_event(event)
            except:
                print('boom?', event.to_dict(exclude_unset=True))
            self._logs.append(log)
        
        if len(self._logs) > NUM_LOGS_REQUIRED_FOR_INSERT:
            self.push_to_db()

    @gatherer.before_loop
    async def before_gatherer_start(self):
        await self.rcon.start()
    @gatherer.after_loop
    async def after_gatherer_stop(self):
        await self.rcon.stop()

    
    def push_to_db(self):
        if self._logs:
            insert_many_logs(sess_id=self.id, logs=self._logs)
        self._logs = list()

    def delete(self):
        delete_logs(sess_id=self.id)

        table = Table("sessions")
        update_query = table.update().set(table.deleted, True).where(table.ROWID == self.id)
        cursor.execute(str(update_query))
        database.commit()
        
        del SESSIONS[self.id]
