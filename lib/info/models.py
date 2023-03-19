from datetime import datetime, timedelta, timezone
from enum import Enum, unique
from inspect import isclass

from lib.info.types import *

if TYPE_CHECKING:
    from lib.storage import LogLine

class Player(InfoModel):
    __key_fields__ = ("steamid", "id", "name",)
    __scope_path__ = "players"

    steamid: str = UnsetField
    """The Steam64 ID of the player"""

    name: str = UnsetField
    """The name of the player"""

    id: Union[int, str] = UnsetField
    """An ID unique to the player"""

    ip: Union[str, None] = UnsetField
    """The IP address of the player"""

    team: Union["Team", Link, None] = UnsetField
    """The team the player is a part of"""

    squad: Union["Squad", Link, None] = UnsetField
    """The squad this player is a part of"""

    role: Union[str, None] = UnsetField
    """The role (often referred to as class) the player is using"""

    loadout: Union[str, None] = UnsetField
    """The loadout the player is using"""

    level: int = UnsetField
    """The level of the player"""

    kills: int = UnsetField
    """The number of kills the player has"""

    deaths: int = UnsetField
    """The number of deaths the player has"""

    assists: int = UnsetField
    """The number of assists the player has"""

    alive: bool = UnsetField
    """Whether the player is currently alive"""
    
    score: 'HLLPlayerScore' = UnsetField
    """The score of the player"""

    location: Any = UnsetField
    """The location of the player"""

    ping: int = UnsetField
    """The latency of the player in milliseconds"""

    is_vip: bool = UnsetField
    """Whether the player is a VIP"""

    joined_at: datetime = UnsetField
    """The time the player joined the server at"""

    is_spectator: bool = UnsetField
    """Whether the player is currently spectating"""

    def is_squad_leader(self) -> Union[bool, None]:
        """Whether the player is a squad leader, or None if not part of a squad"""
        squad = self.get('squad')
        if squad:
            leader = squad.get('leader')
            if leader:
                if self == leader:
                    return True
                else:
                    return False
        return None

    def __hash__(self):
        return hash(self.get('steamid') or self.get('name'))
    
    def __eq__(self, other):
        if isinstance(other, Player):
            return hash(self) == hash(other)
        else:
            return super().__eq__(other)

class HLLPlayerScore(InfoModel):
    __scope_path__ = "players.hll_score"

    combat: int = UnsetField
    """The player's combat score"""
    
    offense: int = UnsetField
    """The player's offense score"""
    
    defense: int = UnsetField
    """The player's defense score"""
    
    support: int = UnsetField
    """The player's support score"""

class Squad(InfoModel):
    __key_fields__ = ("id", "name", "team")
    __scope_path__ = "squads"

    id: Union[int, str] = UnsetField
    """An ID unique to the squad"""

    leader: Union["Player", Link, None] = UnsetField
    """The leader of the squad"""

    creator: Union["Player", Link, None] = UnsetField
    """The creator of the squad"""

    name: str = UnsetField
    """The name of the squad"""

    type: str = UnsetField
    """The type of the squad"""

    private: bool = UnsetField
    """Whether the squad is private, commonly referred to as "locked" or "invite only\""""

    team: Union["Team", Link, None] = UnsetField
    """The team the squad belongs to"""

    players: Union[Sequence["Player"], Link] = UnsetField
    """All players part of the squad"""

    created_at: datetime = UnsetField
    """The time the squad was created at"""

class Team(InfoModel):
    __key_fields__ = ("id", "name",)
    __scope_path__ = "teams"
    
    id: Union[int, str] = UnsetField
    """An ID unique to the team"""

    leader: Union["Player", Link, None] = UnsetField
    """The leader of the team"""

    name: str = UnsetField
    """The name of the team"""

    squads: Union[Sequence["Squad"], Link] = UnsetField
    """All squads part of the team"""
    
    players: Union[Sequence["Player"], Link] = UnsetField
    """All players part of the team"""

    lives: int = UnsetField
    """The amount of lives (often referred to as tickets) left for this team"""

    score: int = UnsetField
    """The score of the team"""

    created_at: datetime = UnsetField
    """The time the team was created at"""

    def get_unassigned_players(self) -> Sequence["Player"]:
        """Get a list of players part of this team that are not part of a squad"""
        return [player for player in self.players if player.has('squad') and not player.squad]

class Server(InfoModel):
    __key_fields__ = ("name",)
    __scope_path__ = "server"

    name: str = UnsetField
    """The name of the server"""

    map: str = UnsetField
    """The name of the current map"""

    gamemode: str = UnsetField
    """The current gamemode"""

    next_map: str = UnsetField
    """The name of the upcoming map"""

    next_gamemode: str = UnsetField
    """The upcoming gamemode"""

    round_start: datetime = UnsetField
    """The time the current round started at"""

    round_end: datetime = UnsetField
    """The time the current round is estimated to end at"""

    state: str = UnsetField
    """The current gameplay state of the server, such as "end_of_round" or "warmup\""""

    queue_length: int = UnsetField
    """The amount of people currently waiting in queue"""

    ranked: bool = UnsetField
    """Whether the server is ranked or not"""

    vac_enabled: bool = UnsetField # Valve Anti Cheat
    """Whether the server utilises Valve Anti-Cheat"""

    pb_enabled: bool = UnsetField # Punkbuster
    """Whether the server utilises Punkbuster Anti-Cheat"""

    location: Any = UnsetField
    """The location of the server"""

    tickrate: float = UnsetField
    """The current tickrate of the server"""

    online_since: datetime = UnsetField
    """The time the server went online"""

    settings: 'ServerSettings' = UnsetField
    """The server's settings"""

class ServerSettings(InfoModel):
    __scope_path__ = "server.settings"

    rotation: Union[List[str], List[Any]] = UnsetField
    """A list of maps/layers currently in rotation"""

    require_password: bool = UnsetField
    """Whether the server requires a password to enter"""
    password: str = UnsetField
    """The password required to enter the server"""
    
    max_players: int = UnsetField
    """The maximum amount of players that can be on the server at once"""

    max_queue_length: int = UnsetField
    """The maximum amount of players that can be waiting in queue to enter the server at once"""
    
    max_vip_slots: int = UnsetField
    """The number of slots that the server holds reserved for VIPs"""
    
    time_dilation: float = UnsetField
    """The time dilation of the server"""
    
    idle_kick_time: timedelta = UnsetField
    """The time players can stay idle until kicked"""
    idle_kick_enabled: bool = UnsetField
    """Whether players get kicked for staying idle too long"""

    ping_threshold: Union[int, None] = UnsetField
    """The latency threshold in milliseconds past which players get kicked for a poor connection"""
    ping_threshold_enabled: bool = UnsetField
    """Whether players can get kicked for having a poor latency"""
    
    team_switch_cooldown: Union[timedelta, None] = UnsetField
    """The time players have to wait between switching teams"""
    team_switch_cooldown_enabled: bool = UnsetField
    """Whether there is a cooldown preventing teams from switching teams too quickly"""
    
    auto_balance_threshold: int = UnsetField
    """The difference in amount of players per team required for auto balance measures to be put in place"""
    auto_balance_enabled: bool = UnsetField
    """Whether the server will apply auto balance measures if necessary"""
    
    vote_kick_enabled: bool = UnsetField
    """Whether the server allows vote kicking"""
    
    chat_filter: set = UnsetField
    """The list of words that will get flagged by the server's chat filter"""
    chat_filter_enabled: bool = UnsetField
    """Whether the server has a chat filter enabled"""

#####################################
#              EVENTS               #
#####################################

class EventModel(InfoModel):
    __key_fields__ = ()
    event_time: datetime = None
    
    @pydantic.validator('event_time', pre=True, always=True)
    def set_ts_now(cls, v):
        return v or datetime.now(tz=timezone.utc)

class PlayerJoinServerEvent(EventModel):
    __scope_path__ = 'events.player_join_server'
    player: Union[Player, Link] = UnsetField

class ServerMapChangedEvent(EventModel):
    __scope_path__ = 'events.server_map_changed'
    old: str = UnsetField
    new: str = UnsetField

class ServerMatchStarted(EventModel):
    __scope_path__ = 'events.server_match_started'
    map: str = UnsetField
    
class ServerWarmupEnded(EventModel):
    __scope_path__ = 'events.server_warmup_ended'

class ServerMatchEnded(EventModel):
    __scope_path__ = 'events.server_match_ended'
    map: str = UnsetField
    score: str = UnsetField

class SquadCreatedEvent(EventModel):
    __scope_path__ = 'events.squad_created'
    squad: Union[Squad, Link] = UnsetField

class PlayerSwitchTeamEvent(EventModel):
    __scope_path__ = 'events.player_switch_team'
    player: Union[Player, Link] = UnsetField
    old: Union[Team, Link, None] = UnsetField
    new: Union[Team, Link, None] = UnsetField

class PlayerSwitchSquadEvent(EventModel):
    __scope_path__ = 'events.player_switch_squad'
    player: Union[Player, Link] = UnsetField
    old: Union[Squad, Link, None] = UnsetField
    new: Union[Squad, Link, None] = UnsetField

class SquadLeaderChangeEvent(EventModel):
    __scope_path__ = 'events.squad_leader_change'
    squad: Union[Squad, Link] = UnsetField
    old: Union[Player, Link, None] = UnsetField
    new: Union[Player, Link, None] = UnsetField

class PlayerChangeRoleEvent(EventModel):
    __scope_path__ = 'events.player_change_role'
    player: Union[Player, Link] = UnsetField
    old: Union[str, None] = UnsetField
    new: Union[str, None] = UnsetField

class PlayerChangeLoadoutEvent(EventModel):
    __scope_path__ = 'events.player_change_loadout'
    player: Union[Player, Link] = UnsetField
    old: Union[str, None] = UnsetField
    new: Union[str, None] = UnsetField

class PlayerEnterAdminCamEvent(EventModel):
    __scope_path__ = 'events.player_enter_admin_cam'
    player: Union[Player, Link] = UnsetField

class PlayerMessageEvent(EventModel):
    __scope_path__ = 'events.player_message'
    player: Union[Player, Link, str] = UnsetField
    message: str = UnsetField
    channel: Any = UnsetField

class PlayerKillEvent(EventModel):
    __scope_path__ = 'events.player_kill'
    player: Union[Player, Link, str] = UnsetField
    other: Union[Player, Link, None] = UnsetField
    weapon: str = UnsetField

class PlayerTeamkillEvent(PlayerKillEvent):
    __scope_path__ = 'events.player_teamkill'

class PlayerSuicideEvent(EventModel):
    __scope_path__ = 'events.player_suicide'
    player: Union[Player, Link, str] = UnsetField

class ObjectiveCaptureEvent(EventModel):
    __scope_path__ = 'events.objective_capture'
    team: Union[Team, Link] = UnsetField
    score: str = UnsetField

class PlayerLevelUpEvent(EventModel):
    __scope_path__ = 'events.player_level_up'
    player: Union[Player, Link] = UnsetField
    old: int = UnsetField
    new: int = UnsetField

class PlayerExitAdminCamEvent(EventModel):
    __scope_path__ = 'events.player_exit_admin_cam'
    player: Union[Player, Link] = UnsetField

class PlayerLeaveServerEvent(EventModel):
    __scope_path__ = 'events.player_leave_server'
    player: Union[Player, Link] = UnsetField

class SquadDisbandedEvent(EventModel):
    __scope_path__ = 'events.squad_disbanded'
    squad: Union[Squad, Link] = UnsetField

class PrivateEventModel(EventModel):
    """A special event model that simply flags
    this event as one that should not be adopted
    by info trees."""

class ActivationEvent(PrivateEventModel):
    __scope_path__ = 'events.activation'
class IterationEvent(PrivateEventModel):
    __scope_path__ = 'events.iteration'
class DeactivationEvent(PrivateEventModel):
    __scope_path__ = 'events.deactivation'

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
    server_map_changed = ServerMapChangedEvent
    server_match_started = ServerMatchStarted
    server_warmup_ended = ServerWarmupEnded
    server_match_ended = ServerMatchEnded
    squad_created = SquadCreatedEvent
    player_switch_team = PlayerSwitchTeamEvent
    player_switch_squad = PlayerSwitchSquadEvent
    squad_leader_change = SquadLeaderChangeEvent
    player_change_role = PlayerChangeRoleEvent
    player_change_loadout = PlayerChangeLoadoutEvent
    player_enter_admin_cam = PlayerEnterAdminCamEvent
    player_message = PlayerMessageEvent
    player_kill = PlayerKillEvent
    player_teamkill = PlayerTeamkillEvent
    player_suicide = PlayerSuicideEvent
    objective_capture = ObjectiveCaptureEvent
    player_level_up = PlayerLevelUpEvent
    player_exit_admin_cam = PlayerExitAdminCamEvent
    player_leave_server = PlayerLeaveServerEvent
    squad_disbanded = SquadDisbandedEvent

    @classmethod
    def _missing_(cls, value):
        try:
            return cls[value]
        except KeyError:
            return super()._missing_(cls, value)
    
    @classmethod
    def all(cls):
        """An iterator containing all events, including private ones."""
        return (cls._member_map_[name] for name in cls._member_names_)
    @classmethod
    def public(cls):
        """An iterator containing all events, excluding private ones."""
        return (cls._member_map_[name] for name in cls._member_names_ if not issubclass(cls._member_map_[name].value, PrivateEventModel))

#Events = pydantic.create_model('Events', __base__=InfoModel, **{event.name: (List[event.value], Unset) for event in EventTypes.public()})
class Events(InfoModel):
    player_join_server: List['PlayerJoinServerEvent'] = UnsetField
    server_map_changed: List['ServerMapChangedEvent'] = UnsetField
    server_match_started: List['ServerMatchStarted'] = UnsetField
    server_warmup_ended: List['ServerWarmupEnded'] = UnsetField
    squad_created: List['SquadCreatedEvent'] = UnsetField
    player_switch_team: List['PlayerSwitchTeamEvent'] = UnsetField
    player_switch_squad: List['PlayerSwitchSquadEvent'] = UnsetField
    squad_leader_change: List['SquadLeaderChangeEvent'] = UnsetField
    player_change_role: List['PlayerChangeRoleEvent'] = UnsetField
    player_change_loadout: List['PlayerChangeLoadoutEvent'] = UnsetField
    player_enter_admin_cam: List['PlayerEnterAdminCamEvent'] = UnsetField
    player_message: List['PlayerMessageEvent'] = UnsetField
    player_kill: List['PlayerKillEvent'] = UnsetField
    player_teamkill: List['PlayerTeamkillEvent'] = UnsetField
    player_suicide: List['PlayerSuicideEvent'] = UnsetField
    objective_capture: List['ObjectiveCaptureEvent'] = UnsetField
    server_match_ended: List['ServerMatchEnded'] = UnsetField
    player_level_up: List['PlayerLevelUpEvent'] = UnsetField
    player_exit_admin_cam: List['PlayerExitAdminCamEvent'] = UnsetField
    player_leave_server: List['PlayerLeaveServerEvent'] = UnsetField
    squad_disbanded: List['SquadDisbandedEvent'] = UnsetField

    def __getitem__(self, key) -> List[InfoModel]:
        return obj_getattr(self, str(EventTypes(key)))
    def __setitem__(self, key, value):
        setattr(self, str(EventTypes(key)), value)

    def add(self, *events: Union[EventModel, Type[EventModel]]):
        """Populate this model with events.

        Events are placed in the right attribute automatically. If
        still `Unset` they will be initialized. Note that private
        event models cannot be added.

        Passing an event class instead of an object will initialize
        the corresponding property. This will prevent this property
        from be overwritten when merging or when automatically
        compiling events.

        Parameters
        ----------
        *events : Union[EventModel, Type[EventModel]]
            The events to add and event types to initialize
        """
        for event in events:
            if isclass(event):
                if not issubclass(event, EventModel) or issubclass(event, PrivateEventModel):
                    raise ValueError("%s is a subclass of PrivateEventModel or is not an event")
                etype = EventTypes(event)
                if self[etype] is Unset:
                    self[etype] = InfoModelArray()
            else:
                if not isinstance(event, EventModel) or isinstance(event, PrivateEventModel):
                    raise ValueError("%s is of type PrivateEventModel or is not an event model")
                etype = EventTypes(event.__class__)
                if self[etype] is Unset:
                    self[etype] = InfoModelArray([event])
                else:
                    self[etype].append(event)

# ----- Info Hopper -----

class InfoHopper(ModelTree):
    players: List['Player'] = UnsetField
    squads: List['Squad'] = UnsetField
    teams: List['Team'] = UnsetField
    server: 'Server' = None
    events: 'Events' = None
    __solid__: bool

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.server:
            self.server = Server(self)
        if not self.events:
            self.events = Events(self)
        obj_setattr(self, '__solid__', not self.__config__.allow_mutation)
    
    def __getattribute__(self, name: str):
        if name in obj_getattr(self, '__fields__'):
            res = super().__getattribute__(name)
            if res is Unset:
                raise AttributeError(name)
            return res
        else:
            return super().__getattribute__(name)

    def add_players(self, *players: 'Player'):
        self._add('players', *players)
    def add_squads(self, *squads: 'Squad'):
        self._add('squads', *squads)
    def add_teams(self, *teams: 'Team'):
        self._add('teams', *teams)
    def set_server(self, server: 'Server'):
        self.server = server
  
    def find_players(self, single=False, ignore_unknown=False, **filters) -> Union['Player', List['Player'], None]:
        return self._get('players', multiple=not single, ignore_unknown=ignore_unknown, **filters)
    def find_squads(self, single=False, ignore_unknown=False, **filters) -> Union['Squad', List['Squad'], None]:
        return self._get('squads', multiple=not single, ignore_unknown=ignore_unknown, **filters)
    def find_teams(self, single=False, ignore_unknown=False, **filters) -> Union['Team', List['Team'], None]:
        return self._get('teams', multiple=not single, ignore_unknown=ignore_unknown, **filters)

    @property
    def team1(self):
        return self.teams[0]
    @property
    def team2(self):
        return self.teams[1]
    
    @classmethod
    def gather(cls, *infos: 'InfoHopper'):
        """Gathers and combines all :class:`InfoHopper`s
        and returns a new hopper"""
        info = cls()
        for other in infos:
            if not other:
                continue
            info.merge(other)
        return info
        
    def compare_older(self, other: 'InfoHopper', event_time: datetime = None):
        events = Events(self)

        # Since this method should only be used once done with
        # combining data from all sources, and events are never
        # really referenced backwards, it is completely safe to
        # pass objects directly. Much more reliable than Links.

        if not event_time:
            event_time = datetime.now(tz=timezone.utc)

        if self.has('players') and other.has('players'):
            others = InfoModelArray(other.players)
            for player in self.players:
                match = self._get(others, multiple=False, ignore_unknown=True, **player.get_key_attributes())
                if match:
                    del others[others.index(match)]

                    # Role Change Event

                    if player.has('role') and match.has('role'):
                        if player.role != match.role:
                            events.add(PlayerChangeRoleEvent(self, event_time=event_time, player=player.create_link(with_fallback=True), old=match.role, new=player.role))

                    # Loadout Change Event

                    """
                    if player.has('loadout') and match.has('loadout'):
                        if player.loadout != match.loadout:
                            events.add(PlayerChangeLoadoutEvent(self, event_time=event_time, player=player.create_link(with_fallback=True), old=match.loadout, new=player.loadout))
                    """

                    # Level Up Event

                    if player.has('level') and match.has('level'):
                        # Sometimes it takes the server a little to load the player's actual level. Here's an attempt
                        # to prevent a levelup event from occurring during those instances.
                        if player.level > match.level and not (match.level == 1 and player.level - match.level > 1):
                            events.add(PlayerLevelUpEvent(self, event_time=event_time, player=player.create_link(with_fallback=True), old=match.level, new=player.level))

                if not player.get('joined_at'):
                    if match:
                        player.joined_at = match.get('joined_at') or player.__created_at__
                    else:
                        player.joined_at = player.__created_at__

                if not match:
                    events.add(PlayerJoinServerEvent(self, event_time=event_time, player=player.create_link(with_fallback=True)))
                
                p_squad = player.get('squad')
                m_squad = match.get('squad') if match else None
                if p_squad != m_squad:
                    events.add(PlayerSwitchSquadEvent(self, event_time=event_time,
                        player=player.create_link(with_fallback=True),
                        old=m_squad.create_link(with_fallback=True) if m_squad else None,
                        new=p_squad.create_link(with_fallback=True) if p_squad else None,
                    ))
                    
                p_team = player.get('team')
                m_team = match.get('team') if match else None
                if p_team != m_team:
                    events.add(PlayerSwitchTeamEvent(self, event_time=event_time,
                        player=player.create_link(with_fallback=True),
                        old=m_team.create_link(with_fallback=True) if m_team else None,
                        new=p_team.create_link(with_fallback=True) if p_team else None,
                    ))

            for player in others:
                events.add(PlayerLeaveServerEvent(self, event_time=event_time,
                    player=player.create_link(with_fallback=True)
                ))
                if player.get('squad'):
                    events.add(PlayerSwitchSquadEvent(self, event_time=event_time,
                        player=player.create_link(with_fallback=True),
                        old=player.squad.create_link(with_fallback=True),
                        new=None
                    ))
                if player.get('team'):
                    events.add(PlayerSwitchTeamEvent(self, event_time=event_time,
                        player=player.create_link(with_fallback=True),
                        old=player.team.create_link(with_fallback=True),
                        new=None
                    ))
        
        if self.has('squads') and other.has('squads'):
            others = InfoModelArray(other.squads)
            for squad in self.squads:
                match = self._get(others, multiple=False, ignore_unknown=True, **squad.get_key_attributes())
                if match:
                    del others[others.index(match)]

                    # Squad Leader Change Event

                    if squad.has('leader') and match.has('leader'):
                        if squad.leader != match.leader:
                            old = match.leader.create_link(with_fallback=True) if match.leader else None
                            new = squad.leader.create_link(with_fallback=True) if squad.leader else None
                            events.add(SquadLeaderChangeEvent(self, event_time=event_time, squad=squad.create_link(with_fallback=True), old=old, new=new))
                
                if not squad.get('created_at'):
                    if match:
                        squad.created_at = match.get('created_at') or squad.__created_at__
                    else:
                        squad.created_at = squad.__created_at__

                if not match:
                    events.add(SquadCreatedEvent(self, event_time=event_time, squad=squad.create_link(with_fallback=True)))
            
            for squad in others:
                events.add(SquadDisbandedEvent(self, event_time=event_time, squad=squad.create_link(with_fallback=True)))
        
        if self.has('teams') and other.has('teams'):
            others = InfoModelArray(other.teams)
            for team in self.teams:
                match = self._get(others, multiple=False, ignore_unknown=True, **team.get_key_attributes())
                if match:
                    del others[others.index(match)]
                
                # Objective Capture Event

                if team.has('score') and match.has('score') and self.server.get('state') != 'warmup':
                    if team.score > match.score:
                        if team.id == 1:
                            message = f"{team.score} - {5 - team.score}"
                        else:
                            message = f"{5 - team.score} - {team.score}"
                        events.add(ObjectiveCaptureEvent(self, event_time=event_time, team=team.create_link(with_fallback=True), score=message))
                
                if not team.get('created_at'):
                    if match:
                        team.created_at = match.get('created_at') or team.__created_at__
                    else:
                        team.created_at = team.__created_at__

        self_map = self.server.get('map')
        other_map = other.server.get('map')
        if all([self_map, other_map]) and self_map != other_map:
            events.add(ServerMapChangedEvent(self, event_time=event_time, old=other_map, new=self_map))

        self.events.merge(events)


from discord.flags import flag_value, fill_with_flags
# discord.py provides some nice tools for making flags. We have to be
# careful for breaking changes however.

@fill_with_flags()
class EventFlags(Flags):
    
    @classmethod
    def connections(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_join_server = True
        self.player_leave_server = True
        return self

    @classmethod
    def game_states(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.server_map_changed = True
        self.server_match_started = True
        self.server_warmup_ended = True
        self.server_match_ended = True
        self.objective_capture = True
        return self
    
    @classmethod
    def teams(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_switch_team = True
        return self
    
    @classmethod
    def squads(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_switch_squad = True
        self.squad_created = True
        self.squad_disbanded = True
        self.squad_leader_change = True
        return self
    
    @classmethod
    def deaths(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_kill = True
        self.player_teamkill = True
        self.player_suicide = True
        return self
    
    @classmethod
    def messages(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_message = True
        return self
    
    @classmethod
    def admin_cam(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_enter_admin_cam = True
        self.player_exit_admin_cam = True
        return self
    
    @classmethod
    def roles(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_change_role = True
        self.player_change_loadout = True
        self.player_level_up = True
        return self
    
    @classmethod
    def modifiers(cls: Type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.rule_violated = True
        self.arty_assigned = True
        self.arty_unassigned = True
        self.start_arty_cooldown = True
        self.cancel_arty_cooldown = True
        return self
    

    @flag_value
    def player_join_server(self):
        return 1 << 0

    @flag_value
    def server_map_changed(self):
        return 1 << 1

    @flag_value
    def server_match_started(self):
        return 1 << 2

    @flag_value
    def server_warmup_ended(self):
        return 1 << 3

    @flag_value
    def server_match_ended(self):
        return 1 << 4

    @flag_value
    def squad_created(self):
        return 1 << 5

    @flag_value
    def player_switch_team(self):
        return 1 << 6

    @flag_value
    def player_switch_squad(self):
        return 1 << 7

    @flag_value
    def squad_leader_change(self):
        return 1 << 8

    @flag_value
    def player_change_role(self):
        return 1 << 9

    @flag_value
    def player_change_loadout(self):
        return 1 << 10

    @flag_value
    def player_enter_admin_cam(self):
        return 1 << 11

    @flag_value
    def player_message(self):
        return 1 << 12

    @flag_value
    def player_kill(self):
        return 1 << 13

    @flag_value
    def player_teamkill(self):
        return 1 << 14

    @flag_value
    def player_suicide(self):
        return 1 << 15

    @flag_value
    def player_level_up(self):
        return 1 << 16

    @flag_value
    def player_exit_admin_cam(self):
        return 1 << 17

    @flag_value
    def player_leave_server(self):
        return 1 << 18

    @flag_value
    def squad_disbanded(self):
        return 1 << 19

    @flag_value
    def objective_capture(self):
        return 1 << 20
    
    @flag_value
    def rule_violated(self):
        return 1 << 21

    @flag_value
    def arty_assigned(self):
        return 1 << 22

    @flag_value
    def arty_unassigned(self):
        return 1 << 23

    @flag_value
    def start_arty_cooldown(self):
        return 1 << 24

    @flag_value
    def cancel_arty_cooldown(self):
        return 1 << 25


    def filter_logs(self, logs: Sequence['LogLine']):
        allowed_types = {type_ for type_, allowed in self if allowed}
        for log in logs:
            if log.type in allowed_types:
                yield log
