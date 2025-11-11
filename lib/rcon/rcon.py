import asyncio
from datetime import datetime, timezone
import re
from typing import TYPE_CHECKING
from hllrcon import Rcon

from lib.rcon.models import (
    Player, PlayerEnterAdminCamEvent, PlayerExitAdminCamEvent, PlayerKillEvent, PlayerMessageEvent, PlayerScore, PlayerScoreUpdateEvent, PlayerSuicideEvent, PlayerTeamkillEvent,
    Server, ServerMatchEndedEvent, ServerMatchStartedEvent, ServerWarmupEndedEvent, Snapshot, Squad, Team
)

if TYPE_CHECKING:
    from lib.session import HLLCaptureSession

RE_LOG_KILL = re.compile(r"^(?P<is_teamkill>TEAM )?KILL: .+\((?:Allies|Axis)\/(?P<player_id>\d{17}|[\da-f]{32})\) -> .+\((?:Allies|Axis)\/(?P<victim_id>\d{17}|[\da-f]{32})\) with (?P<weapon>.+)$")
RE_LOG_CHAT = re.compile(r"^CHAT\[(?P<channel_name>Team|Unit)\]\[.+\((?:Allies|Axis)\/(?P<player_id>\d{17}|[\da-f]{32})\)\]: (?P<message>.+)$")
RE_LOG_ADMIN_CAM = re.compile(r"^Player \[.+ \((?P<player_id>\d{17}|[\da-f]{32})\)\] (?:Left|(?P<is_entering>Entered)) Admin Camera$")
RE_LOG_MATCH_START = re.compile(r"^MATCH START (?P<map_name>.+)$")
RE_LOG_MATCH_ENDED = re.compile(r"^MATCH ENDED `(?P<map_name>.+)` ALLIED \((?P<score>.+)\) AXIS *$")

class HLLRcon:
    def __init__(self, session: 'HLLCaptureSession'):
        self.session = session
        self._client: Rcon | None = None

        self.snapshot: Snapshot | None = None
        self._snapshot = Snapshot()

        self._logs_last_seen_content = ""
        self._logs_last_seen_time = datetime.now(tz=timezone.utc)

        self._spectators: set[str] = set()
        
        self._match_start_time = datetime.now(tz=timezone.utc)
        self._match_state = "in_progress"
        self._end_warmup_handle = None
        
        self._previously_missing_deaths: dict[str, int] = {}
        self._logged_deaths: dict[str, int] = {}
        self._last_death_time: dict[str, datetime] = {}

    @property
    def loop(self):
        return self.session.loop
    @property
    def credentials(self):
        return self.session.credentials
    @property
    def logger(self):
        return self.session.logger
    @property
    def client(self):
        if not self._client:
            raise RuntimeError("RCON client is not connected")
        return self._client
    
    async def start(self):
        if self._client is not None:
            self._client.disconnect()

        if not self.credentials:
            raise RuntimeError("No credentials are known")

        self._client = Rcon(
            host=self.credentials.address,
            port=self.credentials.port,
            password=self.credentials.password,
            logger=self.logger,
        )
    
    async def stop(self):
        if self._client is not None:
            self._client.disconnect()

        self._client = None

    async def create_snapshot(self):
        self._snapshot = Snapshot()
        logs_last_seen_time = await self._fetch_logs()
        await self._fetch_server_state()

        self._update_state()

        if self.snapshot is not None:
            self._snapshot.compare_older(
                other=self.snapshot,
                event_time=logs_last_seen_time,
            )

        self.snapshot = self._snapshot
        return self.snapshot
    
    async def _fetch_logs(self) -> datetime | None:
        response = await self.client.get_admin_log(seconds_span=30)

        skip: bool = True
        time: datetime | None = None
        log: str = ""

        for entry in response.entries:
            try:
                match = re.match(r"^\[.+? \((?P<timestamp>\d+)\)\] (?P<log>[\w\W]+)$", entry.message, flags=re.M)
                if not match:
                    raise Exception("Failed to read timestamp from log line: %s" % entry.message)

                timestamp = int(match.group("timestamp"))
                log = match.group("log")

                time = datetime.fromtimestamp(timestamp).astimezone(timezone.utc)

                if skip:
                    # Avoid duplicates
                    if self._logs_last_seen_time > time:
                        continue
                    elif self._logs_last_seen_time == time:
                        if self._logs_last_seen_content == log:
                            skip = False
                        continue
                skip = False

                self._parse_log(time, log)
            except Exception:
                self.logger.exception("Failed to parse log line: %s", entry.message)

        if time:
            self._logs_last_seen_time = time
            self._logs_last_seen_content = log
            return time
        return None
        
    def _parse_log(self, event_time: datetime, log: str):
        """
        [10:00:00 hours (1639106251)] CONNECTED A Player Name (12345678901234567)
        [10:00:00 hours (1639122640)] DISCONNECTED A Player Name (12345678901234567)
        [10:00:00 hours (1639143555)] KILL: A Player Name(Axis/12345678901234567) -> (WTH) A Player name(Allies/12345678901234567) with MP40
        [10:00:00 hours (1639144073)] TEAM KILL: A Player Name(Allies/12345678901234567) -> A Player Name(Allies/12345678901234567) with M1 GARAND
        [30:00 min (1639144118)] CHAT[Team][A Player Name(Allies/12345678901234567)]: Please build garrisons!
        [30:00 min (1639145775)] CHAT[Unit][A Player Name(Axis/12345678901234567)]: comms working?
        [15.03 sec (1639148961)] Player [A Player Name (12345678901234567)] Entered Admin Camera
        [15.03 sec (1639148961)] Player [A Player Name (12345678901234567)] Left Admin Camera
        [15.03 sec (1639148961)] BAN: [A Player Name] has been banned. [BANNED FOR 2 HOURS BY THE ADMINISTRATOR!]
        [15.03 sec (1639148961)] KICK: [A Player Name] has been kicked. [BANNED FOR 2 HOURS BY THE ADMINISTRATOR!]
        [15.03 sec (1639148961)] MESSAGE: player [A Player Name(12345678901234567)], content [Stop teamkilling, you donkey!]
        [805 ms (1639148969)] MATCH START SAINTE-MÈRE-ÉGLISE WARFARE
        [805 ms (1639148969)] MATCH ENDED `SAINTE-MÈRE-ÉGLISE WARFARE` ALLIED (2 - 3) AXIS 
        """
        if log.startswith("KILL") or log.startswith("TEAM KILL"):
            data = RE_LOG_KILL.match(log).groupdict() # type: ignore
            data["snapshot"] = self._snapshot

            is_teamkill = bool(data.pop("is_teamkill"))
            e_cls = PlayerTeamkillEvent if is_teamkill else PlayerKillEvent

            event = e_cls.model_validate(data)
            self._snapshot.add_event(event)

            self._logged_deaths[event.player_id] = self._logged_deaths.get(event.player_id, 0) + 1

        elif log.startswith('CHAT'):
            data = RE_LOG_CHAT.match(log).groupdict() # type: ignore
            data["snapshot"] = self._snapshot

            old_channel: Team | Squad | None = None
            if self.snapshot:
                for player in self.snapshot.players:
                    if player.id == data["player_id"]:
                        if data["channel_name"] == "Unit":
                            old_channel = player.get_squad()
                        else:
                            old_channel = player.get_team()
                        break
            data["old_channel"] = old_channel            
            
            event = PlayerMessageEvent.model_validate(data)
            self._snapshot.add_event(event)

        elif log.startswith('Player'):
            data = RE_LOG_ADMIN_CAM.match(log).groupdict() # type: ignore
            data["snapshot"] = self._snapshot

            is_entering = bool(data.pop("is_entering"))
            if is_entering:
                e_cls = PlayerEnterAdminCamEvent
                self._spectators.add(data["player_id"])
            else:
                e_cls = PlayerExitAdminCamEvent
                try:
                    self._spectators.remove(data["player_id"])
                except KeyError:
                    pass
            
            event = e_cls.model_validate(data)
            self._snapshot.add_event(event)

        elif log.startswith('MATCH START'):
            data = RE_LOG_MATCH_START.match(log).groupdict() # type: ignore
            data["snapshot"] = self._snapshot

            event = ServerMatchStartedEvent.model_validate(data)
            self._snapshot.add_event(event)

            self._state = "warmup"
            if isinstance(self._end_warmup_handle, asyncio.TimerHandle):
                self._end_warmup_handle.cancel()
            self._end_warmup_handle = self.loop.call_later(180, self.__enter_playing_state)

            self._spectators.clear()
            self._previously_missing_deaths.clear()
            self._logged_deaths.clear()
            self._last_death_time.clear()

        elif log.startswith('MATCH ENDED'):
            data = RE_LOG_MATCH_ENDED.match(log).groupdict() # type: ignore
            data["snapshot"] = self._snapshot

            event = ServerMatchEndedEvent.model_validate(data)
            self._snapshot.add_event(event)
            self._state = "end_of_round"

            # Cancel the timer responsible for triggering the Warmup Ended event
            if isinstance(self._end_warmup_handle, asyncio.TimerHandle):
                self._end_warmup_handle.cancel()
            self._end_warmup_handle = None

            # Log the scores of all online players
            if self.snapshot:
                for player in self.snapshot.players:
                    self._snapshot.add_event(
                        PlayerScoreUpdateEvent(
                            snapshot=self._snapshot,
                            event_time=event_time,
                            player_id=player.id,
                        )
                    )

        elif log.split(' ', 1)[0] in {'CONNECTED', 'DISCONNECTED', 'TEAMSWITCH', 'KICK:', 'BAN:', 'VOTESYS:', 'MESSAGE:'}:
            # Suppress error logs
            pass
            
        else:
            raise Exception("Unknown log line: %s", log)

    async def _fetch_server_state(self):
        players_response, server_response = await asyncio.gather(
            self.client.get_players(),
            self.client.get_server_session(),
        )

        squads: dict[tuple[int, int], Squad] = {}
        teams: dict[int, Team] = {
            1: Team(
                snapshot=self._snapshot,
                id=1,
                name="Allies",
                faction="US",
                score=server_response.allied_score,
            ),
            2: Team(
                snapshot=self._snapshot,
                id=2,
                name="Axis",
                faction="GER",
                score=server_response.axis_score,
            )
        }
        self._snapshot.add_teams(*teams.values())

        for player_data in players_response.players:
            team_id: int | None = None
            squad_id: int | None = None

            faction = player_data.faction
            if faction is not None:
                team_id = faction.team.id
                teams[team_id].faction = faction.name

                squad_name = player_data.platoon
                if squad_name:
                    squad_id = ord(squad_name[0]) - ord("A") + 1
                    if (team_id, squad_id) not in squads:
                        squad = Squad(
                            snapshot=self._snapshot,
                            team_id=team_id,
                            id=squad_id,
                            name=squad_name,
                        )
                        squads[(team_id, squad_id)] = squad
                        self._snapshot.add_squads(squad)

            score_data = player_data.score_data
            score = PlayerScore(
                combat=score_data.combat,
                offense=score_data.offense,
                defense=score_data.defense,
                support=score_data.support,
            )

            location = player_data.world_position
            is_alive = any(location)

            player_id = player_data.id
            is_spectator = player_id in self._spectators

            player = Player(
                snapshot=self._snapshot,
                id=player_id,
                team_id=team_id,
                squad_id=squad_id,
                platform=player_data.platform,
                name=player_data.name,
                eos_id=player_data.eos_id,
                role=player_data.role,
                loadout=player_data.loadout,
                level=player_data.level,
                kills=player_data.kills,
                deaths=player_data.deaths,
                is_alive=is_alive,
                score=score,
                location=location,
                is_spectator=is_spectator,
            )
            self._snapshot.add_players(player)

        server = Server(
            snapshot=self._snapshot,
            name=server_response.server_name,
            map=server_response.map_name,
            max_players=server_response.max_player_count,
            round_start=self._match_start_time,
            state=self._match_state,
        )
        self._snapshot.set_server(server)

    def _update_state(self):
        if self._end_warmup_handle is True:
            self._snapshot.add_event(
                ServerWarmupEndedEvent(snapshot=self._snapshot)
            )
            self._end_warmup_handle = None

        missing_deaths = {}
        for player in self._snapshot.players:
            logged_deaths = self._logged_deaths.setdefault(player.id, max(player.deaths, 0))
            missing = player.deaths - logged_deaths
            if missing < 0:
                missing = 0
                self._logged_deaths[player.id] = player.deaths

            missing_deaths[player.id] = missing

        for player_id, missing_old in self._previously_missing_deaths.items():
            missing = missing_deaths.get(player_id)
            
            if missing is None:
                continue

            if missing >= missing_old and missing_old > 0:
                self._logged_deaths[player_id] += missing
                missing_deaths[player_id] = 0
                self._snapshot.add_event(
                    PlayerSuicideEvent(
                        snapshot=self._snapshot,
                        event_time=self._last_death_time.get(player_id, datetime.now(tz=timezone.utc)),
                        player_id=player_id,
                    )
                )
            
        self._previously_missing_deaths = missing_deaths

    def __enter_playing_state(self):
        self._end_warmup_handle = True
