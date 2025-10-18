import asyncio
from datetime import datetime, timedelta, timezone
from discord.ext import tasks
from pypika import Table
from typing import Union, Dict, Tuple, Sequence

from lib.credentials import Credentials
from lib.exceptions import NotFound, SessionDeletedError, SessionAlreadyRunningError, SessionMissingCredentialsError
from lib.events import EventListener
from lib.flags import EventFlags
from lib.modifiers import ModifierFlags, Modifier, INTERNAL_MODIFIERS
from lib.rcon import HLLRcon
from lib.rcon.models import ActivationEvent, DeactivationEvent, EventModel, IterationEvent, PrivateEventModel, Snapshot
from lib.storage import LogLine, database, cursor, insert_many_logs, delete_logs
from utils import get_config, schedule_coro, get_logger

SECONDS_BETWEEN_ITERATIONS = get_config().getint('Session', 'SecondsBetweenIterations')
NUM_LOGS_REQUIRED_FOR_INSERT = get_config().getint('Session', 'NumLogsRequiredForInsert')
DELETE_SESSION_AFTER = timedelta(days=get_config().getint('Session', 'DeleteAfterDays'))
KICK_INCOMPATIBLE_NAMES = get_config().getboolean('Session', 'KickIncompatibleNames')

MAX_AUTOSESSION_DURATION_MINUTES = get_config().getint('AutoSession', 'MaxDurationInMinutes')
MIN_PLAYERS_UNTIL_AUTOSESSION_STOP = get_config().getint('AutoSession', 'MinPlayersUntilStop')
MIN_PLAYERS_ITERATIONS_UNTIL_STOP = 10

SESSIONS: Dict[int, 'HLLCaptureSession'] = dict()

def get_sessions(guild_id: int):
    return sorted([sess for sess in SESSIONS.values() if sess.guild_id == guild_id], key=lambda sess: sess.start_time)

class HLLCaptureSession:
    def __init__(self, id: int, guild_id: int, name: str, start_time: datetime, end_time: Union[datetime, None],
            credentials: Credentials | None, modifiers: ModifierFlags = ModifierFlags(), loop: asyncio.AbstractEventLoop | None = None):
        self.id = id
        self.guild_id = guild_id
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.credentials = credentials
        self.loop = loop or asyncio.get_running_loop()
        self._logs = list()
        self._session_expiration_count = 0

        if not self.end_time:
            self.is_auto_session = True
            self.end_time = self.start_time + timedelta(minutes=MAX_AUTOSESSION_DURATION_MINUTES)
        else:
            self.is_auto_session = False

        if self.id in SESSIONS:
            raise SessionAlreadyRunningError("A session with ID %s is already running")

        self.logger = get_logger(self)

        self.rcon: HLLRcon | None = None
        self.snapshot: Snapshot = Snapshot()

        self.modifiers = [
            modifier(self) for modifier in INTERNAL_MODIFIERS
        ] + [
            modifier(self) for modifier in modifiers.get_modifier_types()
        ]
        self.modifier_flags = modifiers.copy()
        self.logger.info("Installed modifiers: %s", ", ".join([modifier.config.name for modifier in self.modifiers]))
        
        if self.active_in():
            self._start_task = schedule_coro(self.start_time, self.activate, error_logger=self.logger)
            self._stop_task = schedule_coro(self.end_time, self.deactivate, error_logger=self.logger)
        else:
            self._start_task = None
            self._stop_task = None

        self.__listeners = None

        self.sent_helo_prompt_indices = list()

        SESSIONS[self.id] = self
        
    @classmethod
    def load_from_db(cls, id: int):
        cursor.execute('SELECT ROWID, guild_id, name, start_time, end_time, deleted, credentials_id, modifiers FROM sessions WHERE ROWID = ?', (id,))
        res = cursor.fetchone()

        if not res:
            raise NotFound(f"No session exists with ID {id}")

        deleted = bool(res[5])
        if deleted:
            raise SessionDeletedError

        credentials_id = res[6]
        if credentials_id is None:
            credentials = None
        else:
            try:
                credentials = Credentials.get(credentials_id)
            except NotFound:
                credentials = None

        return cls(
            id=int(res[0]),
            guild_id=int(res[1]),
            name=str(res[2]),
            start_time=datetime.fromisoformat(res[3]),
            end_time=datetime.fromisoformat(res[4]) if res[4] else None,
            credentials=credentials,
            modifiers=ModifierFlags(int(res[7]))
        )
    
    @classmethod
    def create_in_db(cls, guild_id: int, name: str, start_time: datetime, end_time: datetime | None, credentials: Credentials, modifiers: ModifierFlags = ModifierFlags()):
        if end_time is not None and datetime.now(tz=timezone.utc) > end_time:
            raise ValueError('This capture session would have already ended')

        cursor.execute('INSERT INTO sessions (guild_id, name, start_time, end_time, credentials_id, modifiers) VALUES (?,?,?,?,?,?)',
            (guild_id, name, start_time, end_time, credentials.id, modifiers.value))
        id_ = cursor.lastrowid
        if id_ is None:
            raise Exception("Failed to create session in the database")

        # Create the table if needed
        sess_name = f"session{id_}"
        cursor.execute(LogLine._get_create_query(sess_name))
        database.commit()

        self = cls(
            id=id_,
            guild_id=guild_id,
            name=name,
            start_time=start_time,
            end_time=end_time,
            credentials=credentials,
            modifiers=modifiers
        )
        self.logger.info("Created new session: %s", self)
        return self

    @property
    def duration(self) -> timedelta:
        if not self.end_time:
            raise ValueError("Session does not have an end time")
        return self.end_time - self.start_time

    @property
    def kick_incompatible_names(self):
        return KICK_INCOMPATIBLE_NAMES or any([
            modifier.config.enforce_name_validity
            for modifier in self.modifiers
        ])

    def __str__(self):
        return f"[#{self.id}] {self.name} ({self.credentials.name if self.credentials else '⚠️'})"

    def __eq__(self, other):
        if isinstance(other, HLLCaptureSession):
            return self.id == other.id
        return False

    def save(self):
        cursor.execute("""UPDATE sessions SET name = ?, start_time = ?, end_time = ?, credentials_id = ?, modifiers = ? WHERE ROWID = ?""",
            (self.name, self.start_time, self.end_time if not self.is_auto_session else None, self.credentials.id if self.credentials else None,
             self.modifier_flags.value, self.id))
        database.commit()

    def active_in(self) -> Union[timedelta, bool]:
        """Returns how long until the session should start. Otherwise
        returns whether the session should currently be active or not.

        Returns
        -------
        Union[timedelta, bool]
            The time until the session should activate, otherwise
            whether it is currently active.
        """
        now = datetime.now(tz=timezone.utc)
        if self.start_time > now:
            return now - self.start_time
        elif self.end_time:
            return self.end_time > now
        else:
            return True
    
    def should_delete(self):
        if self.end_time is None:
            return False
        return datetime.now(tz=timezone.utc) > (self.end_time + DELETE_SESSION_AFTER)

    async def activate(self):
        if not self.credentials:
            raise SessionMissingCredentialsError(f"Session with ID {self.id} does not have server credentials")
        
        for session in get_sessions(self.credentials.guild_id):
            if session.credentials == self.credentials and session != self and session.is_auto_session:
                assert session.credentials is not None
                assert session.credentials.autosession is not None
                session.credentials.autosession.logger.info("Disabling active session since a manual session was started")
                await session.stop()
                break

        if self.rcon is None:
            self.rcon = HLLRcon(session=self)
        self.gatherer.start()
    async def deactivate(self):
        self.gatherer.stop()
        # self.push_to_db()   This is handled by the gather after_loop

    async def stop(self):
        self.is_auto_session = False
        active = self.active_in()

        if active is False:
            pass
        elif active is True:
            self.end_time = datetime.now(tz=timezone.utc)
            self.save()
        else:
            self.start_time = self.end_time = datetime.now(tz=timezone.utc)
            self.save()
        
        await self.deactivate()
        self._clear_tasks()

    @tasks.loop(seconds=SECONDS_BETWEEN_ITERATIONS)
    async def gatherer(self):
        snapshot = None

        if self.rcon is None:
            # This realistically shouldn't happen
            await self.deactivate()
            return

        try:
            snapshot = await self.rcon.create_snapshot()
            self.snapshot = snapshot
        except Exception:
            self.logger.exception("Failed to create snapshot")
        else:
            events = [IterationEvent(snapshot=snapshot)] + snapshot.events
            for event in events:
                if not isinstance(event, PrivateEventModel):
                    try:
                        log = event.to_log_line()
                    except Exception:
                        self.logger.exception('Failed to cast event to log line: %s %s' % (type(event).__name__, event.model_dump()))
                    else:
                        self._logs.append(log)
                
                for modifier in self.modifiers:
                    for listener in modifier.get_listeners_for_event(event):
                        asyncio.create_task(listener.invoke(modifier, event))
                
            if len(self._logs) > NUM_LOGS_REQUIRED_FOR_INSERT:
                self.push_to_db()
        
        if self.is_auto_session:
            assert self.credentials is not None
            assert self.credentials.autosession is not None
            playercount = len(snapshot.players) if snapshot else 0
            if playercount < MIN_PLAYERS_UNTIL_AUTOSESSION_STOP:
                self._session_expiration_count += 1
                self.credentials.autosession.logger.info("%s/%s players online, session will expire after %s more iterations",
                    playercount, MIN_PLAYERS_UNTIL_AUTOSESSION_STOP, MIN_PLAYERS_ITERATIONS_UNTIL_STOP - self._session_expiration_count)
            else:
                if self._session_expiration_count != 0:
                    self.credentials.autosession.logger.info("%s/%s players online, session expiration has been cancelled",
                        playercount, MIN_PLAYERS_UNTIL_AUTOSESSION_STOP)
                self._session_expiration_count = 0
            
            if self._session_expiration_count >= MIN_PLAYERS_ITERATIONS_UNTIL_STOP:
                self.logger.info("The session has expired and will be stopped")
                await self.stop()

    @gatherer.before_loop
    async def before_gatherer_start(self):
        try:
            assert self.rcon is not None
            await self.rcon.start()
        except Exception:
            self.logger.exception('Failed to start RCON')
        
        self._session_expiration_count = 0

        event = ActivationEvent(snapshot=Snapshot())
        await self.invoke_event(event)

    @gatherer.after_loop
    async def after_gatherer_stop(self):
        event = DeactivationEvent(snapshot=self.snapshot)
        await self.invoke_event(event)

        if self.rcon:
            try:
                await self.rcon.stop()
            except Exception:
                self.logger.exception('Failed to stop RCON')
        self.push_to_db()

    def _clear_tasks(self):
        if self._start_task and not self._start_task.done():
            self._start_task.cancel()
        if self._stop_task and not self._stop_task.done():
            self._stop_task.cancel()

    @property
    def listeners(self) -> Dict[str, Tuple[EventListener]]:
        if self.__listeners is None:
            listeners = dict()
            for modifier in self.modifiers:
                for event_type, values in modifier.listeners.items():
                    listeners.setdefault(event_type, list()).extend(values)
            self.__listeners = {event_type: tuple(values) for event_type, values in listeners.items()}
        return self.__listeners
    def get_listeners_for_event(self, event: EventModel):
        """Returns a generator of all listeners that listen for this event

        Parameters
        ----------
        event : EventModel
            The event

        Yields
        ------
        EventListener
            A corresponding event listener
        """
        yield from self.listeners.get(event.get_type().name, ())

    async def invoke_event(self, event: EventModel, modifiers: Sequence['Modifier'] | None = None):
        if modifiers is None:
            modifiers = self.modifiers

        coros = list()
        for modifier in modifiers:
            for listener in modifier.get_listeners_for_event(event):
                coros.append(listener.invoke(modifier, event))
        if coros:
            await asyncio.gather(*coros)

    def push_to_db(self):
        self.logger.info('Pushing %s logs to the DB', len(self._logs))
        if self._logs:
            insert_many_logs(sess_id=self.id, logs=self._logs)
        self._logs = list()

    def get_logs(
        self,
        from_: datetime | None = None,
        to: datetime | None = None,
        filter: EventFlags | None = None,
        limit: int | None = None,
    ):
        self.push_to_db()

        sess_name = f"session{self.id}"
        columns = tuple(LogLine.model_fields)

        table = Table(sess_name)
        query = table.select(*columns)

        if from_:
            query = query.where(table.event_time >= from_)
        if to:
            query = query.where(table.event_time < to)
        if filter is not None:
            query = query.where(table.event_type.isin([k for k, v in filter if v]))
        if limit:
            query = query.limit(limit)
        
        cursor.execute(str(query))
        return [LogLine(
            **{k: v for k, v in zip(columns, record) if v is not None}
        ) for record in cursor.fetchall()]

    def delete(self):
        self.logger.info('Deleting session...')
        schedule_coro(datetime.now(tz=timezone.utc), self.deactivate, error_logger=self.logger)
        self._clear_tasks()
        delete_logs(sess_id=self.id)

        table = Table("sessions")
        update_query = table.update().set(table.deleted, True).where(table.ROWID == self.id)
        cursor.execute(str(update_query))
        database.commit()
        
        del SESSIONS[self.id]

    async def edit(self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        credentials: Credentials | None = None,
        modifiers: ModifierFlags = ModifierFlags()
    ):
        # Get differences between old and new modifier flags
        combined_flags = self.modifier_flags | modifiers
        modifier_flags_to_add = combined_flags ^ self.modifier_flags 
        modifier_flags_to_remove = combined_flags ^ modifiers

        # Get list of removed modifiers
        modifiers_to_remove = list()
        modifier_types_to_remove = list(modifier_flags_to_remove.get_modifier_types())
        for modifier in self.modifiers:
            if type(modifier) in modifier_types_to_remove:
                del self.modifiers[self.modifiers.index(modifier)]
                modifiers_to_remove.append(modifier)
        
        # Invoke DeactivationEvent
        if modifiers_to_remove:
            self.modifier_flags ^= modifier_flags_to_remove
            self.__listeners = None
            event = DeactivationEvent(snapshot=Snapshot())
            await self.invoke_event(event, modifiers_to_remove)
        
        # Update start and end time
        if start_time:
            self.start_time = start_time
        if end_time:
            self.end_time = end_time
        
        # Update credentials
        if credentials:
            self.credentials = credentials
            force_reconnect = True
        else:
            force_reconnect = False

        # Start or stop if needed
        await self.reevalute_start_stop(force_reconnect)

        # Get list of added modifiers
        modifiers_to_add = list()
        for m_cls in modifier_flags_to_add.get_modifier_types():
            modifier = m_cls(self)
            modifiers_to_add.append(modifier)

        # Invoke ActivationEvent
        if modifiers_to_add:
            self.__listeners = None
            self.modifiers += modifiers_to_add
            self.modifier_flags |= modifier_flags_to_add
            event = ActivationEvent(snapshot=Snapshot())
            await self.invoke_event(event, modifiers_to_add)

        # At last, save
        self.save()

    async def reevalute_start_stop(self, force_reconnect: bool = False):
        self._clear_tasks()

        is_activated = self.gatherer.is_running()
        active_in = self.active_in()
        
        if force_reconnect and self.rcon:
            await self.rcon.stop()

        self._start_task = None
        self._stop_task = None

        end_time = self.end_time
        assert end_time is not None

        if active_in and not is_activated:
            self._start_task = schedule_coro(self.start_time, self.activate, error_logger=self.logger)
        if active_in or is_activated:
            self._stop_task = schedule_coro(end_time, self.deactivate, error_logger=self.logger)
