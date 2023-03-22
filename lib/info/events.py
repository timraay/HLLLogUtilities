import asyncio
from datetime import datetime, timedelta, timezone
from functools import update_wrapper, wraps
from inspect import isfunction, iscoroutinefunction, isclass
from enum import Enum

from lib.info.models import EventModel, EventTypes, PlayerKillEvent, PlayerSuicideEvent
from utils import to_timedelta

from typing import Union, List, Tuple, Any, Callable, Sequence, Coroutine


class CooldownType(Enum):
    player='player'
    squad='squad'
    team='team'
    server='server'

class ListenerCooldown:
    def __init__(self, bucket_type: CooldownType, duration: Union[int, timedelta, datetime], callback: Callable = None):
        self.duration = to_timedelta(duration)
        self.bucket_type = CooldownType(bucket_type)
        self._cooldowns: List[Tuple[Any, datetime]] = list()
        self.callback = callback
    
    def _clean_cooldowns(self):
        new = list()
        for cooldown in self._cooldowns:
            if not (cooldown[1] + self.duration < datetime.now(tz=timezone.utc)):
                new.append(cooldown)
        self._cooldowns = new

    def get_property(self, event):
        fields = set(event.__fields__)
        if self.bucket_type == CooldownType.player:
            if 'player' in fields and event.has('player'):
                return event.player
        elif self.bucket_type == CooldownType.squad:
            if 'squad' in fields and event.has('squad'):
                return event.squad
            elif 'player' in fields and event.has('player') and event.player.has('squad'):
                return event.player.squad
        elif self.bucket_type == CooldownType.team:
            if 'team' in fields and event.has('team'):
                return event.team
            elif 'squad' in fields and event.has('squad') and event.squad.has('team'):
                return event.squad.team
            elif 'player' in fields and event.has('player') and event.player.has('team'):
                return event.player.team
        elif self.bucket_type == CooldownType.server:
            if event.root.has('server'):
                return event.root.server
        raise TypeError('%s does not have required attributes to apply cooldown %s: %s', type(event).__name__, self.bucket_type, event.to_dict(exclude_unset=True))

    def validate(self, event):
        try:
            prop = self.get_property(event)
        except TypeError:
            return True
        
        self._clean_cooldowns()

        for key, _ in self._cooldowns:
            if prop == key:
                return False
        return True

    def add(self, event):
        try:
            prop = self.get_property(event)
        except TypeError:
            print('%s does not have attribute %s, cannot apply cooldown condition', type(event).__name__, self.bucket_type)
        else:
            cooldown = (prop, datetime.now(tz=timezone.utc))
            self._cooldowns.append(cooldown)


class EventListener:
    def __init__(self,
        event_types: Sequence[str],
        func: Callable,
        timeout: Union[float, None] = None,
        conditions: Sequence[Callable[[EventModel], bool]] = None,
        cooldowns: Sequence[ListenerCooldown] = None,
    ):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError('Method \'%s\' must be a coroutine function' % func.__name__)
        self.events = tuple(str(etype) for etype in event_types)
        self.func = func
        self.timeout = timeout
        self._conditions = list(conditions or [])
        self._cooldowns = list(cooldowns or [])

        self._load_checks_from_func(func)
    
    def _load_checks_from_func(self, func):
        self._conditions += getattr(func, '_conditions', list())
        self._cooldowns += getattr(func, '_cooldowns', list())

    async def __call__(self, *args, **kwargs):
        return await self.func(*args, **kwargs)
    
    async def invoke(self, sf, event, *args, **kwargs):
        """Call the listener's method and catch any exceptions.

        Returns
        -------
        Union[Any, Exception]
            The method's result, or an exception if it failed
        """
        for condition in self._conditions:
            if iscoroutinefunction(condition):
                res = await condition(sf, event)
            else:
                res = condition(sf, event)

            if not res:
                return
            elif isinstance(res, EventModel):
                event = res

        if not all(cooldown.validate(event) for cooldown in self._cooldowns):
            for cooldown in self._cooldowns:
                if cooldown.callback:
                    try:
                        cooldown.callback(event)
                    except:
                        sf.logger.exception('Cooldown callback failed')
            return
        for cooldown in self._cooldowns:
            cooldown.add(event)

        try:
            return await asyncio.wait_for(self.__call__(sf, event, *args, **kwargs), timeout=self.timeout)
        except Exception as exc:
            sf.logger.exception('Failed to invoke %s', type(event).__name__)
            return exc
            
        
    def __hash__(self):
        return id(self.func)

    def add_condition(self, condition: Callable):
        self._conditions.append(condition)

def add_condition(callable: Callable):
    def decorator(func):
        conditions = getattr(func, '_conditions', list())
        conditions.append(callable)
        func._conditions = conditions
        return func
    return decorator

def add_cooldown(bucket_type: CooldownType, duration: Union[int, timedelta, datetime], callback: Callable = None):
    cd = ListenerCooldown(CooldownType(bucket_type), duration, callback)
    def decorator(func):
        cooldowns = getattr(func, '_cooldowns', list())
        cooldowns.append(cd)
        func._cooldowns = cooldowns
        return func
    return decorator



def event_listener(event_types: Sequence[Union[EventModel, EventTypes, str]], timeout: float = 10.0, conditions: List[Callable] = None, cls=EventListener):
    try:
        timeout = float(timeout) if timeout else None
    except TypeError:
        if isfunction(timeout):
            raise TypeError(f"Listener expected an int but received a function {timeout.__name__}. Make sure you initialize the decorator before it wraps the function.")
        else:
            raise
    
    if not isclass(cls):
        raise TypeError("Cls %r must be a class, not a class instance" % cls)
    if not issubclass(cls, EventListener):
        raise ValueError("Cls %s must be a subclass of EventListener" % cls.__name__)

    event_types = list(event_types)
    for i, event_type in enumerate(event_types):
        if isinstance(event_type, EventModel):
            event_type = event_type.__event_name__
        elif isinstance(event_type, EventTypes):
            event_type = event_type.name
        elif not isinstance(event_type, str):
            raise TypeError("event_type must be either an EventModel, EventTypes or str, not %s" % type(event_type).__name__)
        event_types[i] = event_type
    

    def decorator(func):
        return cls(
            event_types=event_types,
            func=func,
            timeout=timeout,
            conditions=conditions
        )
    return decorator


def on_activation(timeout: float = 10.0):
    """Adds an event listener for when the session is activated
    and a RCON connection has been opened."""
    return event_listener(['activation'], timeout=timeout)

def on_iteration(timeout: float = 10.0):
    """Adds an event listener that triggers this function every
    time the info tree is refreshed."""
    return event_listener(['iteration'], timeout=timeout)

def on_deactivation(timeout: float = 10.0):
    """Adds an event listener for when the session is deactivated
    and the RCON connection is waiting to be closed."""
    return event_listener(['deactivation'], timeout=timeout)


def on_player_join_server(timeout: float = 10.0):
    """Adds an event listener for players joining the server."""
    return event_listener([EventTypes.player_join_server], timeout=timeout)

def on_server_map_changed(timeout: float = 10.0):
    """Adds an event listener for the server changing map."""
    return event_listener([EventTypes.server_map_changed], timeout=timeout)

def on_server_match_started(timeout: float = 10.0):
    """Adds an event listener for a new match being started."""
    return event_listener([EventTypes.server_match_started], timeout=timeout)

def on_server_warmup_ended(timeout: float = 10.0):
    """Adds an event listener for a match's warmup phase ending."""
    return event_listener([EventTypes.server_match_ended], timeout=timeout)

def on_server_match_ended(timeout: float = 10.0):
    """Adds an event listener for a match being finished."""
    return event_listener([EventTypes.server_match_ended], timeout=timeout)

def on_squad_created(timeout: float = 10.0):
    """Adds an event listener for squads being created."""
    return event_listener([EventTypes.squad_created], timeout=timeout)

def on_player_switch_team(timeout: float = 10.0):
    """Adds an event listener for players switching team."""
    return event_listener([EventTypes.player_switch_team], timeout=timeout)

def on_player_switch_squad(timeout: float = 10.0):
    """Adds an event listener for players switching squad."""
    return event_listener([EventTypes.player_switch_squad], timeout=timeout)

def on_squad_leader_change(timeout: float = 10.0):
    """Adds an event listener for when a squad gets a different leader."""
    return event_listener([EventTypes.squad_leader_change], timeout=timeout)

def on_player_change_role(timeout: float = 10.0):
    """Adds an event listener for when a player changes their role."""
    return event_listener([EventTypes.player_change_role], timeout=timeout)

def on_player_change_loadout(timeout: float = 10.0):
    """Adds an event listener for when a player changes their loadout."""
    return event_listener([EventTypes.player_change_loadout], timeout=timeout)

def on_player_enter_admin_cam(timeout: float = 10.0):
    """Adds an event listener for players entering the admin camera."""
    return event_listener([EventTypes.player_enter_admin_cam], timeout=timeout)

def on_player_message(timeout: float = 10.0):
    """Adds an event listener for players sending a message."""
    return event_listener([EventTypes.player_message], timeout=timeout)

def on_player_kill(timeout: float = 10.0):
    """Adds an event listener for players getting a kill."""
    return event_listener([EventTypes.player_kill], timeout=timeout)

def on_player_teamkill(timeout: float = 10.0):
    """Adds an event listener for players getting a teamkill."""
    return event_listener([EventTypes.player_teamkill], timeout=timeout)

def on_player_any_kill(timeout: float = 10.0):
    """Adds an event listener for players getting a kill or teamkill."""
    return event_listener([EventTypes.player_kill, EventTypes.player_teamkill], timeout=timeout)

def on_player_suicide(timeout: float = 10.0):
    """Adds an event listener for players killing themselves."""
    return event_listener([EventTypes.player_suicide], timeout=timeout)

def on_objective_capture(timeout: float = 10.0):
    """Adds an event listener for an objective being captured."""
    return event_listener([EventTypes.objective_capture], timeout=timeout)

def on_player_level_up(timeout: float = 10.0):
    """Adds an event listener for players leveling up."""
    return event_listener([EventTypes.player_level_up], timeout=timeout)

def on_player_score_update(timeout: float = 10.0):
    """Adds an event listener for whenever HLU sends an update on a player's
    score. It does this for every online player directly after a match ends, or
    prematurely for players who disconnect while the match is still in progress."""
    return event_listener([EventTypes.player_score_update], timeout=timeout)

def on_player_exit_admin_cam(timeout: float = 10.0):
    """Adds an event listener for players exiting the admin camera."""
    return event_listener([EventTypes.player_exit_admin_cam], timeout=timeout)

def on_player_leave_server(timeout: float = 10.0):
    """Adds an event listener for players leaving the server."""
    return event_listener([EventTypes.player_leave_server], timeout=timeout)

def on_squad_disbanded(timeout: float = 10.0):
    """Adds an event listener for squads being disbanded."""
    return event_listener([EventTypes.squad_disbanded], timeout=timeout)
