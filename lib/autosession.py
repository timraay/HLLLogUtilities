import asyncio
from datetime import datetime, timezone
from discord.ext import tasks

from lib.exceptions import AutoSessionAlreadyCreatedError, TemporaryCredentialsError, HLLConnectionError, HLLAuthError
from lib.rcon import create_plain_transport
from utils import get_autosession_logger, get_config

from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.credentials import Credentials

MIN_PLAYERS_TO_START = get_config().getint('AutoSession', 'MinPlayersToStart')
MIN_PLAYERS_UNTIL_STOP = get_config().getint('AutoSession', 'MinPlayersUntilStop')
SECONDS_BETWEEN_ITERATIONS = get_config().getint('AutoSession', 'SecondsBetweenIterations')
SECONDS_BETWEEN_ITERATIONS_AFTER_FAIL = get_config().getint('AutoSession', 'SecondsBetweenIterationsAfterFail')
NUM_FAILED_ATTEMPTS_UNTIL_SLOW = 5
NUM_ITERATIONS_UNTIL_COOLDOWN_EXPIRE = 3
NUM_ATTEMPTS_PER_ITERATION = 3


AUTOSESSIONS: Dict[int, 'AutoSessionManager'] = dict()

class AutoSessionManager:
    def __init__(self, credentials: 'Credentials', enabled: bool = False, loop: asyncio.AbstractEventLoop = None):
        self.credentials = credentials
        self.loop = loop or asyncio.get_running_loop()
        self.id = self.credentials.id

        if self.credentials.temporary:
            raise TemporaryCredentialsError("Credentials %s are temporary" % self.credentials.name)
        if self.id in AUTOSESSIONS:
            raise AutoSessionAlreadyCreatedError("An auto-session with ID %s is already known" % self.id)

        self.logger = get_autosession_logger(self)
        self.protocol = None
        self._failed_attempts = 0
        self._cooldown = 0

        self.last_seen_playercount = 0
        self.last_seen_time = datetime.now(tz=timezone.utc)
        self.last_error = None
        self.is_slowed = False

        self.__enabled = enabled
        if enabled:
            self.loop.create_task(self.enable())

        AUTOSESSIONS[self.id] = self
    
    @property
    def enabled(self):
        return self.__enabled
    
    async def enable(self):
        if not self.enabled:
            self.__enabled = True
            if not self.credentials.temporary:
                self.credentials.save()

        self.gatherer.start()

    async def disable(self):
        if self.enabled:
            self.__enabled = False
            if not self.credentials.temporary:
                self.credentials.save()
        
        self.gatherer.stop()

    def close_protocol(self):
        if self.protocol and self.protocol._transport:
            self.protocol._transport.close()
        self.protocol = None

    async def _check_for_session_start(self):
        if not self.protocol or not self.protocol._transport:
            self.protocol = await create_plain_transport(
                host=self.credentials.address,
                port=self.credentials.port,
                password=self.credentials.password,
                loop=self.loop,
                logger=self.logger,
            )
        
        resp = await self.protocol.execute("get slots")
        playercount, _ = resp.split('/', 1)
        playercount = int(playercount)

        self.last_seen_playercount = playercount
        self.last_seen_time = datetime.now(tz=timezone.utc)

        self.logger.info("%s/%s players online for an auto-session to be started (Cooldown: %s)", playercount, MIN_PLAYERS_TO_START, self._cooldown)
        if playercount >= MIN_PLAYERS_TO_START:
            if self._cooldown == 0:
                self.create_session()
            self._cooldown = NUM_ITERATIONS_UNTIL_COOLDOWN_EXPIRE
        
        elif self._cooldown > 0:
            if playercount < MIN_PLAYERS_UNTIL_STOP:
                self._cooldown -= 1
                if self._cooldown == 0:
                    self.logger.info("Server has been empty for %s iterations in a row, cooldown has expired.", NUM_ITERATIONS_UNTIL_COOLDOWN_EXPIRE)
            else:
                self._cooldown = NUM_ITERATIONS_UNTIL_COOLDOWN_EXPIRE

    @tasks.loop(seconds=SECONDS_BETWEEN_ITERATIONS)
    async def gatherer(self):
        if self.get_active_session():
            self._cooldown = NUM_ITERATIONS_UNTIL_COOLDOWN_EXPIRE
            return
        
        for i in range(NUM_ATTEMPTS_PER_ITERATION):

            if i == (NUM_ATTEMPTS_PER_ITERATION - 1):
                # If on its third attempt, force the connection to be
                # reopened, hoping that that might resolve the issue
                self.close_protocol()

            try:
                await self._check_for_session_start()

            except HLLAuthError:
                # If the password is incorrect there is no point in
                # trying several times.
                self.logger.warning("Ended the iteration prematurely after receiving an authentication error")
                self._failed_attempts += 1
                self.last_error = "The RCON password is invalid"
                break

            except Exception as exc:
                self.logger.exception("Failed to receive player count, %s attempts left", 2 - i)

                if i == (NUM_ATTEMPTS_PER_ITERATION - 1):
                    self._failed_attempts += 1

                if isinstance(exc, HLLConnectionError):
                    self.close_protocol()
                    self.last_error = str(exc)
                elif isinstance(exc, asyncio.TimeoutError):
                    self.last_error = "Server took too long to respond"
                else:
                    self.last_error = "Unexpected: Reach out via [GitHub](https://github.com/timraay/HLLLogUtilities/issues/new) for support"

            else:
                self._failed_attempts = 0
                self.last_error = None
                break
        
        if self._failed_attempts >= NUM_FAILED_ATTEMPTS_UNTIL_SLOW:
            if not self.is_slowed:
                self.gatherer.change_interval(seconds=SECONDS_BETWEEN_ITERATIONS_AFTER_FAIL)
                self.is_slowed = True
                self.logger.warning("Failed %s iterations in a row, raising time between iterations to %s",
                    NUM_FAILED_ATTEMPTS_UNTIL_SLOW, SECONDS_BETWEEN_ITERATIONS_AFTER_FAIL)
        else:
            if self.is_slowed:
                self.gatherer.change_interval(seconds=SECONDS_BETWEEN_ITERATIONS)
                self.is_slowed = False
                self.logger.info("An iteration succeeded, lowering the time between iterations to %s again", SECONDS_BETWEEN_ITERATIONS)


    @gatherer.before_loop
    async def before_gatherer_start(self):
        self.close_protocol()
        self._failed_attempts = 0

    @gatherer.after_loop
    async def after_gatherer_stop(self):
        self.close_protocol()


    def create_session(self):
        from lib.session import HLLCaptureSession
        now = datetime.now(tz=timezone.utc)
        return HLLCaptureSession.create_in_db(
            guild_id=self.credentials.guild_id,
            name=now.strftime("AUTO_%a_%d_%b_%H.%M"),
            start_time=now,
            end_time=None,
            credentials=self.credentials,
            modifiers=self.credentials.default_modifiers,
        )

    def get_active_session(self):
        from lib.session import get_sessions
        return next((
            session for session in get_sessions(self.credentials.guild_id)
            if session.credentials == self.credentials and session.active_in() is True
        ), None)
