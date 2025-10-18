import asyncio
from datetime import datetime, timedelta, timezone
from inspect import isfunction, iscoroutinefunction, isclass

from lib.rcon.models import EventModel, EventTypes
from utils import to_timedelta

from typing import Union, List, Tuple, Any, Callable, Sequence


class ListenerCooldown:
    def __init__(
        self,
        field_name: str,
        duration: Union[int, timedelta, datetime],
        callback: Callable | None = None,
    ):
        self.duration = to_timedelta(duration)
        self.field_names = field_name.split(".")
        self._cooldowns: List[Tuple[Any, datetime]] = list()
        self.callback = callback
    
    def _clean_cooldowns(self):
        new = list()
        for cooldown in self._cooldowns:
            if not (cooldown[1] + self.duration < datetime.now(tz=timezone.utc)):
                new.append(cooldown)
        self._cooldowns = new

    def get_property(self, event: EventModel):
        value = event
        for field_name in self.field_names:
            try:
                value = getattr(value, field_name)
            except AttributeError:
                raise TypeError(
                    '%s does not have required attributes to apply cooldown %s (failed on %s): %s',
                    type(event).__name__, self.field_names, field_name, event.model_dump(),
                )
        return value

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
        prop = self.get_property(event)
        cooldown = (prop, datetime.now(tz=timezone.utc))
        self._cooldowns.append(cooldown)


class EventListener:
    def __init__(self,
        event_types: Sequence[str],
        func: Callable,
        timeout: Union[float, None] = None,
        conditions: Sequence[Callable[[EventModel], bool]] | None = None,
        cooldowns: Sequence[ListenerCooldown] | None = None,
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
                res = await condition(sf, event) # type: ignore
            else:
                res = condition(sf, event) # type: ignore

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

def add_cooldown(field_name: str, duration: Union[int, timedelta, datetime], callback: Callable | None = None):
    cd = ListenerCooldown(field_name, duration, callback)
    def decorator(func):
        cooldowns = getattr(func, '_cooldowns', list())
        cooldowns.append(cd)
        func._cooldowns = cooldowns
        return func
    return decorator



def event_listener(
    event_types: Sequence[Union[EventModel, EventTypes, str]],
    timeout: float | None = 10.0,
    conditions: List[Callable] | None = None,
    cls=EventListener
):
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

    event_type_strs = []
    for event_type in event_types:
        if isinstance(event_type, EventModel):
            event_type_strs.append(event_type.get_type().name)
        elif isinstance(event_type, EventTypes):
            event_type_strs.append(event_type.name)
        elif isinstance(event_type, str):
            event_type_strs.append(event_type)
        else:
            raise TypeError("event_type must be either an EventModel, EventTypes or str, not %s" % type(event_type).__name__)

    def decorator(func):
        return cls(
            event_types=event_type_strs,
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
    return event_listener([EventTypes.server_map_change], timeout=timeout)

def on_server_match_started(timeout: float = 10.0):
    """Adds an event listener for a new match being started."""
    return event_listener([EventTypes.server_match_start], timeout=timeout)

def on_server_warmup_ended(timeout: float = 10.0):
    """Adds an event listener for a match's warmup phase ending."""
    return event_listener([EventTypes.server_warmup_end], timeout=timeout)

def on_server_match_ended(timeout: float = 10.0):
    """Adds an event listener for a match being finished."""
    return event_listener([EventTypes.server_match_end], timeout=timeout)

def on_squad_created(timeout: float = 10.0):
    """Adds an event listener for squads being created."""
    return event_listener([EventTypes.squad_create], timeout=timeout)

def on_player_switch_team(timeout: float = 10.0):
    """Adds an event listener for players switching team."""
    return event_listener([EventTypes.player_change_team], timeout=timeout)

def on_player_switch_squad(timeout: float = 10.0):
    """Adds an event listener for players switching squad."""
    return event_listener([EventTypes.player_change_squad], timeout=timeout)

def on_squad_leader_change(timeout: float = 10.0):
    """Adds an event listener for when a squad gets a different leader."""
    return event_listener([EventTypes.squad_change_leader], timeout=timeout)

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
    return event_listener([EventTypes.team_capture_objective], timeout=timeout)

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
    return event_listener([EventTypes.squad_disband], timeout=timeout)
