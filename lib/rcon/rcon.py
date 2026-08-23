import asyncio
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import hllrcon

from lib.games import Game, game_switch
from lib.rcon.models import (
    Player,
    PlayerEnterAdminCamEvent,
    PlayerExitAdminCamEvent,
    PlayerKillEvent,
    PlayerMessageEvent,
    PlayerScore,
    PlayerScoreUpdateEvent,
    PlayerSuicideEvent,
    PlayerTeamkillEvent,
    Server,
    ServerMatchEndedEvent,
    ServerMatchStartedEvent,
    ServerWarmupEndedEvent,
    Snapshot,
    Squad,
    Team,
)

if TYPE_CHECKING:
    from lib.session import HLLCaptureSession

RE_LOG_KILL = re.compile(
    r"^(?P<is_teamkill>TEAM )?KILL: .+\((?:Allies|Axis)\/(?P<player_id>\d{17}|[\da-f]{32})\) -> .+\((?:Allies|Axis)\/(?P<victim_id>\d{17}|[\da-f]{32})\) with (?P<weapon>.+)$"
)
RE_LOG_CHAT = re.compile(
    r"^CHAT\[(?P<channel_name>Team|Unit)\]\[.+\((?:Allies|Axis)\/(?P<player_id>\d{17}|[\da-f]{32})\)\]: (?P<message>.+)$"
)
RE_LOG_ADMIN_CAM = re.compile(
    r"^Player \[.+ \((?P<player_id>\d{17}|[\da-f]{32})\)\] (?:Left|(?P<is_entering>Entered)) Admin Camera$"
)
RE_LOG_MATCH_START = re.compile(r"^MATCH START (?P<map_name>.+)$")
RE_LOG_MATCH_ENDED = re.compile(
    r"^MATCH ENDED `(?P<map_name>.+)` ALLIED \((?P<score>.+)\) AXIS *$"
)


class HLLRcon:
    def __init__(self, session: "HLLCaptureSession"):
        self.session = session
        self._client: hllrcon.AnyRcon | None = None

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

        self._game: Game | None = None

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

    @property
    def game(self):
        return self._game or Game.HLL

    def _create_new_client(self):
        if self._client is not None:
            self._client.disconnect()

        if not self.credentials:
            raise RuntimeError("No credentials are known")

        client_cls = game_switch(self.game, hllrcon.HLLRcon, hllrcon.HLLVRcon)
        self._client = client_cls(
            host=self.credentials.address,
            port=self.credentials.port,
            password=self.credentials.password,
            logger=self.logger,
        )

    async def start(self):
        self._create_new_client()

    async def stop(self):
        if self._client is not None:
            self._client.disconnect()

        self._client = None

    async def detect_game(self):
        available_maps = await self.client.get_available_maps()
        old_game = self.game
        if "foy_warfare" in available_maps:
            self._game = Game.HLL
        else:
            self._game = Game.HLLV

        if self._game != old_game:
            self._create_new_client()

    async def create_snapshot(self):
        if self._game is None:
            await self.detect_game()

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
        log: str = ""

        for entry in response.entries:
            if skip:
                # Avoid duplicates
                if self._logs_last_seen_time > entry.timestamp:
                    continue
                elif self._logs_last_seen_time == entry.timestamp:
                    if self._logs_last_seen_content == entry.raw_message:
                        skip = False
                    continue
            skip = False

            self._parse_log(entry)

        if response.entries:
            latest_entry = response.entries[-1]
            self._logs_last_seen_time = latest_entry.timestamp
            self._logs_last_seen_content = latest_entry.raw_message
            return latest_entry.timestamp
        return None

    def _parse_log(self, entry: hllrcon.AnyAdminLog):
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
        if isinstance(entry, hllrcon.AnyPlayerKillAdminLog):
            self._snapshot.add_event(
                PlayerKillEvent(
                    snapshot=self._snapshot,
                    event_time=entry.timestamp,
                    player_id=entry.instigator_id,
                    victim_id=entry.victim_id,
                    weapon=entry.weapon_id,
                )
            )
            self._logged_deaths[entry.instigator_id] = (
                self._logged_deaths.get(entry.instigator_id, 0) + 1
            )

        elif isinstance(entry, hllrcon.AnyPlayerTeamKillAdminLog):
            self._snapshot.add_event(
                PlayerTeamkillEvent(
                    snapshot=self._snapshot,
                    event_time=entry.timestamp,
                    player_id=entry.instigator_id,
                    victim_id=entry.victim_id,
                    weapon=entry.weapon_id,
                )
            )
            self._logged_deaths[entry.instigator_id] = (
                self._logged_deaths.get(entry.instigator_id, 0) + 1
            )

        elif isinstance(entry, hllrcon.AnyPlayerSendMessageAdminLog):
            old_channel: Team | Squad | None = None
            if self.snapshot:
                for player in self.snapshot.players:
                    if player.id == entry.player_id:
                        if (
                            entry.channel
                            == hllrcon.admin_logs.PlayerMessageChannel.UNIT
                        ):
                            old_channel = player.get_squad()
                        else:
                            old_channel = player.get_team()
                        break

            self._snapshot.add_event(
                PlayerMessageEvent(
                    snapshot=self._snapshot,
                    event_time=entry.timestamp,
                    player_id=entry.player_id,
                    message=entry.message,
                    channel_name=entry.channel.value,
                    old_channel=old_channel,
                )
            )

        elif isinstance(entry, hllrcon.AnyPlayerEnterAdminCameraAdminLog):
            self._spectators.add(entry.player_id)
            self._snapshot.add_event(
                PlayerEnterAdminCamEvent(
                    snapshot=self._snapshot,
                    event_time=entry.timestamp,
                    player_id=entry.player_id,
                )
            )

        elif isinstance(entry, hllrcon.AnyPlayerLeaveAdminCameraAdminLog):
            self._spectators.discard(entry.player_id)
            self._snapshot.add_event(
                PlayerExitAdminCamEvent(
                    snapshot=self._snapshot,
                    event_time=entry.timestamp,
                    player_id=entry.player_id,
                )
            )

        elif isinstance(entry, hllrcon.AnyMatchStartAdminLog):
            self._snapshot.add_event(
                ServerMatchStartedEvent(
                    snapshot=self._snapshot,
                    event_time=entry.timestamp,
                    map_name=f"{entry.map_name} {entry.game_mode_id}",
                )
            )

            self._state = "warmup"
            if isinstance(self._end_warmup_handle, asyncio.TimerHandle):
                self._end_warmup_handle.cancel()
            self._end_warmup_handle = self.loop.call_later(
                180, self.__enter_playing_state
            )

            self._spectators.clear()
            self._previously_missing_deaths.clear()
            self._logged_deaths.clear()
            self._last_death_time.clear()

        elif isinstance(entry, hllrcon.AnyMatchEndAdminLog):
            self._snapshot.add_event(
                ServerMatchEndedEvent(
                    snapshot=self._snapshot,
                    event_time=entry.timestamp,
                    map_name=entry.map_name,
                    score=f"{entry.allied_score} - {entry.axis_score}",
                )
            )
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
                            event_time=entry.timestamp,
                            player_id=player.id,
                        )
                    )

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
            ),
        }
        self._snapshot.add_teams(*teams.values())

        for player_data in players_response.players:
            team_id: int | None = None
            squad_id: int | None = None

            faction = player_data.faction
            if faction is not None:
                team_id = faction.team.id
                teams[team_id].faction = faction.short_name

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
                kills=player_data.stats.infantry_kills,
                deaths=player_data.stats.deaths,
                is_alive=is_alive,
                score=score,
                location=location,
                is_spectator=is_spectator,
            )
            self._snapshot.add_players(player)

        server = Server(
            snapshot=self._snapshot,
            name=server_response.server_name,
            map=server_response.map_id,
            max_players=server_response.max_player_count,
            round_start=self._match_start_time,
            state=self._match_state,
        )
        self._snapshot.set_server(server)

    def _update_state(self):
        if self._end_warmup_handle is True:
            self._snapshot.add_event(ServerWarmupEndedEvent(snapshot=self._snapshot))
            self._end_warmup_handle = None

        missing_deaths = {}
        for player in self._snapshot.players:
            logged_deaths = self._logged_deaths.setdefault(
                player.id, max(player.deaths, 0)
            )
            missing = player.deaths - logged_deaths
            if missing < 0:
                missing = 0
                self._logged_deaths[player.id] = player.deaths

            missing_deaths[player.id] = missing

        for player_id, missing_old in self._previously_missing_deaths.items():
            missing = missing_deaths.get(player_id)

            if missing is None:
                continue

            if missing >= missing_old > 0:
                self._logged_deaths[player_id] += missing
                missing_deaths[player_id] = 0
                self._snapshot.add_event(
                    PlayerSuicideEvent(
                        snapshot=self._snapshot,
                        event_time=self._last_death_time.get(
                            player_id, datetime.now(tz=timezone.utc)
                        ),
                        player_id=player_id,
                    )
                )

        self._previously_missing_deaths = missing_deaths

    def __enter_playing_state(self):
        self._end_warmup_handle = True
