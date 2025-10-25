from datetime import datetime, timezone
from enum import Enum, unique
from functools import total_ordering
import itertools
import pydantic
from sortedcontainers import SortedList
from typing import Any, Generator, Iterator, Literal, Protocol, Sequence, TypeVar, cast

from lib.logs import LogLineBuilder
from hllrcon.responses import PlayerPlatform
from hllrcon.data import Role
from lib.storage import LogLine

__all__ = (
    'Snapshot',
    'Player',
    'PlayerScore',
    'Squad',
    'Team',
    'Server',
    'ActivationEvent',
    'IterationEvent',
    'DeactivationEvent',
    'PlayerJoinServerEvent',
    'ServerMapChangedEvent',
    'ServerMatchStartedEvent',
    'ServerWarmupEndedEvent',
    'ServerMatchEndedEvent',
    'SquadCreateEvent',
    'PlayerChangeTeamEvent',
    'PlayerChangeSquadEvent',
    'SquadChangeLeaderEvent',
    'PlayerChangeRoleEvent',
    'PlayerChangeLoadoutEvent',
    'PlayerEnterAdminCamEvent',
    'PlayerMessageEvent',
    'PlayerKillEvent',
    'PlayerTeamkillEvent',
    'PlayerSuicideEvent',
    'TeamCaptureObjectiveEvent',
    'PlayerLevelUpEvent',
    'PlayerScoreUpdateEvent',
    'PlayerExitAdminCamEvent',
    'PlayerLeaveServerEvent',
    'SquadDisbandEvent',
    'EventTypes',
)

class Comparable(Protocol):
    def __eq__(self, other: Any) -> bool: ...
    def __lt__(self, other: Any) -> bool: ...

T = TypeVar("T", bound=Comparable)

def align_sorted_lists(a: Sequence[T], b: Sequence[T]) -> Iterator[tuple[T | None, T | None]]:
    i = 0
    j = 0
    len_a = len(a)
    len_b = len(b)

    while i < len_a or j < len_b:
        if i < len_a and j < len_b:
            if a[i] == b[j]:
                yield (a[i], b[j])
                i += 1
                j += 1
            elif a[i] < b[j]:
                yield (a[i], None)
                i += 1
            else:
                yield (None, b[j])
                j += 1
        elif i < len_a:
            yield (a[i], None)
            i += 1
        else:
            yield (None, b[j])
            j += 1

class Snapshot:
    players: list['Player']
    disconnected_players: list['Player']
    squads: list['Squad']
    disbanded_squads: list['Squad']
    teams: list['Team']
    server: 'Server'
    events: list['EventModel']

    def __init__(self) -> None:
        self.players = SortedList(key=lambda x: x.id)
        self.disconnected_players = SortedList(key=lambda x: x.id)
        self.squads = SortedList(key=lambda x: x.id)
        self.disbanded_squads = SortedList(key=lambda x: x.id)
        self.teams = SortedList(key=lambda x: x.id)
        self.server = None # type: ignore
        self.events = []

    def add_players(self, *players: 'Player'):
        cast('SortedList', self.players).update(players)
    def add_disconnected_players(self, *players: 'Player'):
        cast('SortedList', self.disconnected_players).update(players)
    def add_squads(self, *squads: 'Squad'):
        cast('SortedList', self.squads).update(squads)
    def add_disbanded_squads(self, *squads: 'Squad'):
        cast('SortedList', self.disbanded_squads).update(squads)
    def add_teams(self, *teams: 'Team'):
        cast('SortedList', self.teams).update(teams)
    def set_server(self, server: 'Server'):
        self.server = server
    
    def add_event(self, event: 'EventModel'):
        self.events.append(event)
  
    @property
    def team1(self):
        return self.teams[0]
    @property
    def team2(self):
        return self.teams[1]
    
    def compare_older(self, other: 'Snapshot', event_time: datetime | None = None):
        if not event_time:
            event_time = datetime.now(tz=timezone.utc)

        events = []

        for old_player, new_player in align_sorted_lists(other.players, self.players):
            player_id = ""
            old_team_id = None
            new_team_id = None
            old_squad_id = None
            new_squad_id = None
            old_role = Role.RIFLEMAN
            new_role = Role.RIFLEMAN

            if old_player is None:
                assert new_player is not None
                events.append(
                    PlayerJoinServerEvent(
                        snapshot=self,
                        event_time=event_time,
                        player_id=new_player.id
                    )
                )
            else:
                player_id = old_player.id
                old_team_id = old_player.team_id
                old_squad_id = old_player.squad_id
                old_role = old_player.role

            if new_player is None:
                assert old_player is not None
                new_role = old_role
                disconnected_player = old_player.model_copy(update={"snapshot": self})
                self.add_disconnected_players(disconnected_player)
                events.append(
                    PlayerLeaveServerEvent(
                        snapshot=self,
                        event_time=event_time,
                        player_id=disconnected_player.id
                    )
                )
                if other.server and other.server.state == "in_progress":
                    events.append(PlayerScoreUpdateEvent(
                        snapshot=self,
                        event_time=event_time,
                        player_id=disconnected_player.id
                    ))
            else:
                player_id = new_player.id
                new_team_id = new_player.team_id
                new_squad_id = new_player.squad_id
                new_role = new_player.role

            if old_player and new_player:
                if old_player.level != new_player.level:
                    events.append(
                        PlayerLevelUpEvent(
                            snapshot=self,
                            event_time=event_time,
                            player_id=new_player.id,
                            old_level=old_player.level,
                            new_level=new_player.level,
                        )
                    )
                new_player.joined_at = old_player.joined_at

            if new_role != old_role:
                events.append(
                    PlayerChangeRoleEvent(
                        snapshot=self,
                        event_time=event_time,
                        player_id=player_id,
                        old_role=old_role,
                        new_role=new_role,
                    )
                )

            if new_squad_id != old_squad_id:
                events.append(
                    PlayerChangeSquadEvent(
                        snapshot=self,
                        event_time=event_time,
                        player_id=player_id,
                        old_squad_id=old_squad_id,
                        new_squad_id=new_squad_id,
                    )
                )

            if new_team_id != old_team_id:
                events.append(
                    PlayerChangeTeamEvent(
                        snapshot=self,
                        event_time=event_time,
                        player_id=player_id,
                        old_team_id=old_team_id,
                        new_team_id=new_team_id,
                    )
                )

        for old_squad, new_squad in align_sorted_lists(other.squads, self.squads):
            squad_id = 0
            team_id = 0
            old_leader = None
            new_leader = None

            if old_squad is None:
                assert new_squad is not None
                events.append(
                    SquadCreateEvent(
                        snapshot=self,
                        event_time=event_time,
                        squad_id=new_squad.id,
                        team_id=new_squad.team_id,
                    )
                )
            else:
                squad_id = old_squad.id
                team_id = old_squad.team_id
                old_leader = old_squad.get_leader()

            if new_squad is None:
                assert old_squad is not None
                new_leader = old_leader
                self.add_disbanded_squads(old_squad.model_copy(update={"snapshot": self}))
                events.append(
                    SquadDisbandEvent(
                        snapshot=self,
                        event_time=event_time,
                        squad=old_squad
                    )
                )
            else:
                squad_id = new_squad.id
                team_id = new_squad.team_id
                new_leader = new_squad.get_leader()

            if new_squad and old_squad:
                new_squad.created_at = old_squad.created_at
            
            if new_leader != old_leader:
                events.append(
                    SquadChangeLeaderEvent(
                        snapshot=self,
                        event_time=event_time,
                        squad_id=squad_id,
                        team_id=team_id,
                        old_leader=old_leader,
                        new_leader=new_leader,
                    )
                )

        for old_team, new_team in align_sorted_lists(other.teams, self.teams):
            if old_team is None or new_team is None:
                # TODO: Emit warning
                continue

            if new_team.score > old_team.score:
                events.append(TeamCaptureObjectiveEvent(
                    snapshot=self,
                    event_time=event_time,
                    team_id=new_team.id,
                    score=f"{self.team1.score} - {self.team2.score}"
                ))

        if other.server and self.server.map != other.server.map:
            events.append(ServerMapChangedEvent(
                snapshot=self,
                event_time=event_time,
                old_map=other.server.map,
                new_map=self.server.map,
            ))
        
        self.events.extend(events)


class BaseModel(pydantic.BaseModel, arbitrary_types_allowed=True):
    snapshot: 'Snapshot' = pydantic.Field(exclude=True)

class TeamModelMixin(BaseModel):
    team_id: int | None

    def get_team(self) -> 'Team | None':
        if self.team_id is None:
            return None

        for team in self.snapshot.teams:
            if team.id == self.team_id:
                return team
        
        return None

class SquadModelMixin(TeamModelMixin):
    squad_id: int | None

    def get_squad(self) -> 'Squad | None':
        if self.squad_id is None or self.team_id is None:
            return None

        for squad in itertools.chain(self.snapshot.squads, self.snapshot.disbanded_squads):
            if squad.id == self.squad_id and squad.team_id == self.team_id:
                return squad
        
        return None

class PlayerModelMixin(BaseModel):
    player_id: str | None

    def get_player(self) -> 'Player | None':
        if self.player_id is None:
            return None

        for player in itertools.chain(self.snapshot.players, self.snapshot.disconnected_players):
            if player.id == self.player_id:
                return player
        
        return None


class PlayerScore(pydantic.BaseModel):
    combat: int
    offense: int
    defense: int
    support: int


@total_ordering
class Player(SquadModelMixin, TeamModelMixin, BaseModel):
    id: str
    platform: PlayerPlatform
    name: str
    eos_id: str
    role: Role
    loadout: str
    level: int
    kills: int
    deaths: int
    is_alive: bool
    score: PlayerScore
    location: tuple[float, float, float]
    joined_at: datetime = pydantic.Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    is_spectator: bool

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Player):
            return self.id == other.id
        return NotImplemented
    
    def __lt__(self, other: object) -> bool:
        if isinstance(other, Player):
            return self.id < other.id
        return NotImplemented
    
    def is_leader(self) -> bool:
        return self.role.is_squad_leader

@total_ordering
class Squad(TeamModelMixin, BaseModel):
    id: int
    team_id: int
    name: str
    created_at: datetime = pydantic.Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Squad):
            return self.id == other.id and self.team_id == other.team_id
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Squad):
            if self.team_id == other.team_id:
                return self.id < other.id
            else:
                return self.team_id < other.team_id
        return NotImplemented

    def get_players(self) -> Generator['Player', Any, None]:
        for player in self.snapshot.players:
            if player.squad_id == self.id and player.team_id == self.id:
                yield player

    def get_leader(self) -> 'Player | None':
        for player in self.get_players():
            if player.is_leader():
                return player
        return None

@total_ordering
class Team(BaseModel):
    id: int
    name: str
    faction: str
    score: int
    created_at: datetime = pydantic.Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Player):
            return self.id == other.id
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Team):
            return self.id < other.id
        return NotImplemented

    def get_players(self) -> Generator['Player', Any, None]:
        for player in self.snapshot.players:
            if player.team_id == self.id:
                yield player

    def get_squads(self) -> Generator['Squad', Any, None]:
        for squad in self.snapshot.squads:
            if squad.team_id == self.id:
                yield squad

    def get_commander(self) -> 'Player | None':
        for player in self.get_players():
            if player.role == Role.COMMANDER:
                return player
        return None

    def get_unassigned_players(self) -> Generator['Player', Any, None]:
        for player in self.get_players():
            if player.squad_id is None:
                yield player

class Server(BaseModel):
    name: str
    map: str
    round_start: datetime
    state: str
    max_players: int

    def get_players(self) -> Generator['Player', Any, None]:
        yield from self.snapshot.players

    def get_squads(self) -> Generator['Squad', Any, None]:
        yield from self.snapshot.squads

    def get_teams(self) -> Generator['Team', Any, None]:
        yield from self.snapshot.teams

    def get_unassigned_players(self) -> Generator['Player', Any, None]:
        for player in self.get_players():
            if player.team_id is None:
                yield player

#####################################
#              EVENTS               #
#####################################

class EventModel(BaseModel):
    event_time: datetime = pydantic.Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def get_type(self) -> 'EventTypes':
        return EventTypes(type(self))

    def to_log_line(self) -> LogLine:
        return LogLineBuilder.from_event(self).to_log_line()


class PlayerJoinServerEvent(PlayerModelMixin, EventModel):
    player_id: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .to_log_line()
        )

class ServerMapChangedEvent(EventModel):
    old_map: str
    new_map: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_old_and_new(self.old_map, self.new_map)
                .to_log_line()
        )

class ServerMatchStartedEvent(EventModel):
    map_name: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_old_and_new(None, self.map_name)
                .to_log_line()
        )
    
class ServerWarmupEndedEvent(EventModel):
    def to_log_line(self) -> LogLine:
        return LogLineBuilder.from_event(self).to_log_line()

class ServerMatchEndedEvent(EventModel):
    map_name: str
    score: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_old_and_new(None, self.map_name)
                .set_message(self.score)
                .to_log_line()
        )

class SquadCreateEvent(SquadModelMixin, EventModel):
    squad_id: int

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_squad(self.get_squad())
                .to_log_line()
        )

class PlayerChangeTeamEvent(PlayerModelMixin, EventModel):
    player_id: str
    old_team_id: int | None
    new_team_id: int | None

    def get_old_team(self) -> 'Team | None':
        if self.old_team_id is None:
            return None
        for team in self.snapshot.teams:
            if team.id == self.old_team_id:
                return team
        return None

    def get_new_team(self) -> 'Team | None':
        if self.new_team_id is None:
            return None
        for team in self.snapshot.teams:
            if team.id == self.new_team_id:
                return team
        return None

    def to_log_line(self) -> LogLine:
        old_team = self.get_old_team()
        new_team = self.get_new_team()
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .set_old_and_new(
                    old_team.name if old_team else None,
                    new_team.name if new_team else None,
                )
                .to_log_line()
        )

class PlayerChangeSquadEvent(PlayerModelMixin, EventModel):
    player_id: str
    old_squad_id: int | None
    new_squad_id: int | None

    def get_old_squad(self) -> 'Squad | None':
        if self.old_squad_id is None:
            return None
        for squad in itertools.chain(self.snapshot.squads, self.snapshot.disbanded_squads):
            if squad.id == self.old_squad_id:
                return squad
        return None

    def get_new_squad(self) -> 'Squad | None':
        if self.new_squad_id is None:
            return None
        for squad in self.snapshot.squads:
            if squad.id == self.new_squad_id:
                return squad
        return None

    def to_log_line(self) -> LogLine:
        old_squad = self.get_old_squad()
        new_squad = self.get_new_squad()
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .set_old_and_new(
                    old_squad.name if old_squad else None,
                    new_squad.name if new_squad else None,
                )
                .to_log_line()
        )

class SquadChangeLeaderEvent(SquadModelMixin, EventModel):
    squad_id: int
    old_leader: Player | None
    new_leader: Player | None

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.new_leader)
                .set_player2(self.old_leader)
                .set_squad(self.get_squad())
                .to_log_line()
        )

class PlayerChangeRoleEvent(PlayerModelMixin, EventModel):
    player_id: str
    old_role: Role
    new_role: Role

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .set_old_and_new(self.old_role.name, self.new_role.name)
                .to_log_line()
        )

class PlayerChangeLoadoutEvent(PlayerModelMixin, EventModel):
    player_id: str
    old_loadout: str
    new_loadout: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .set_old_and_new(self.old_loadout, self.new_loadout)
                .to_log_line()
        )

class PlayerEnterAdminCamEvent(PlayerModelMixin, EventModel):
    player_id: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .to_log_line()
        )

class PlayerExitAdminCamEvent(PlayerModelMixin, EventModel):
    player_id: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .to_log_line()
        )

class PlayerMessageEvent(PlayerModelMixin, SquadModelMixin, EventModel):
    player_id: str
    message: str
    channel_name: Literal["Unit", "Team"]
    old_channel: Team | Squad | None

    def get_channel(self) -> Team | Squad | None:
        if player := self.get_player():
            if self.channel_name == "Unit":
                return player.get_squad() or self.old_channel
            else:
                return player.get_team() or self.old_channel
        return None

    def to_log_line(self) -> LogLine:
        player = self.get_player()

        builder = (
            LogLineBuilder
                .from_event(self)
                .set_player(player)
                .set_message(self.message)
        )

        if player:
            if self.channel_name == "Unit":
                assert isinstance(self.old_channel, Squad | None)
                builder.set_squad(player.get_squad() or self.old_channel)
            else:
                assert isinstance(self.old_channel, Team | None)
                builder.set_team(player.get_team() or self.old_channel)

        return builder.to_log_line()

class PlayerKillEvent(PlayerModelMixin, EventModel):
    player_id: str
    victim_id: str
    weapon: str

    def get_victim(self) -> 'Player | None':
        for player in itertools.chain(self.snapshot.players, self.snapshot.disconnected_players):
            if player.id == self.victim_id:
                return player
        return None

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .set_player2(self.get_victim())
                .set_weapon(self.weapon)
                .to_log_line()
        )

class PlayerTeamkillEvent(PlayerModelMixin, EventModel):
    player_id: str
    victim_id: str
    weapon: str

    def get_victim(self) -> 'Player | None':
        for player in itertools.chain(self.snapshot.players, self.snapshot.disconnected_players):
            if player.id == self.victim_id:
                return player
        return None

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .set_player2(self.get_victim())
                .set_weapon(self.weapon)
                .to_log_line()
        )

class PlayerSuicideEvent(PlayerModelMixin, EventModel):
    player_id: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .to_log_line()
        )

class TeamCaptureObjectiveEvent(TeamModelMixin, EventModel):
    team_id: int
    score: str

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_team(self.get_team())
                .set_message(self.score)
                .to_log_line()
        )

class PlayerLevelUpEvent(PlayerModelMixin, EventModel):
    player_id: str
    old_level: int
    new_level: int

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .set_old_and_new(str(self.old_level), str(self.new_level))
                .to_log_line()
        )

class PlayerScoreUpdateEvent(PlayerModelMixin, EventModel):
    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player(), include_score=True)
                .to_log_line()
        )

class PlayerLeaveServerEvent(PlayerModelMixin, EventModel):
    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_player(self.get_player())
                .to_log_line()
        )

class SquadDisbandEvent(EventModel):
    squad: Squad

    def to_log_line(self) -> LogLine:
        return (
            LogLineBuilder
                .from_event(self)
                .set_squad(self.squad)
                .to_log_line()
        )

class PrivateEventModel(EventModel):
    """A special event model that simply flags
    this event as one that should not be adopted
    by info trees."""

class ActivationEvent(PrivateEventModel):
    pass
class IterationEvent(PrivateEventModel):
    pass
class DeactivationEvent(PrivateEventModel):
    pass

#####################################

@unique
class EventTypes(Enum):

    def __str__(self):
        return self.name

    activation = ActivationEvent
    iteration = IterationEvent
    deactivation = DeactivationEvent
    
    # In order of evaluation!
    player_join_server = PlayerJoinServerEvent
    server_map_change = ServerMapChangedEvent
    server_match_start = ServerMatchStartedEvent
    server_warmup_end = ServerWarmupEndedEvent
    server_match_end = ServerMatchEndedEvent
    squad_create = SquadCreateEvent
    player_change_team = PlayerChangeTeamEvent
    player_change_squad = PlayerChangeSquadEvent
    squad_change_leader = SquadChangeLeaderEvent
    player_change_role = PlayerChangeRoleEvent
    player_change_loadout = PlayerChangeLoadoutEvent
    player_enter_admin_cam = PlayerEnterAdminCamEvent
    player_message = PlayerMessageEvent
    player_kill = PlayerKillEvent
    player_teamkill = PlayerTeamkillEvent
    player_suicide = PlayerSuicideEvent
    team_capture_objective = TeamCaptureObjectiveEvent
    player_level_up = PlayerLevelUpEvent
    player_score_update = PlayerScoreUpdateEvent
    player_exit_admin_cam = PlayerExitAdminCamEvent
    player_leave_server = PlayerLeaveServerEvent
    squad_disband = SquadDisbandEvent

    @classmethod
    def _missing_(cls, value):
        try:
            return cls[str(value)]
        except KeyError:
            return super()._missing_(value)
    
    @classmethod
    def all(cls):
        """An iterator containing all events, including private ones."""
        return (cls._member_map_[name] for name in cls._member_names_)
    @classmethod
    def public(cls):
        """An iterator containing all events, excluding private ones."""
        return (
            cls._member_map_[name]
            for name in cls._member_names_
            if not issubclass(cls._member_map_[name].value, PrivateEventModel)
        )

