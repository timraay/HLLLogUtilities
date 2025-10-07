from functools import reduce
from typing import TYPE_CHECKING, Self, Sequence
from discord.flags import BaseFlags
# discord.py provides some nice tools for making flags. We have to be
# careful for breaking changes however.

if TYPE_CHECKING:
    from lib.logs import LogLine

class Flags(BaseFlags):
    __slots__ = ()

    def __init__(self, value: int = 0, **kwargs: bool) -> None:
        self.value: int = value
        for key, value in kwargs.items():
            if key not in self.VALID_FLAGS:
                raise TypeError(f'{key!r} is not a valid flag name.')
            setattr(self, key, value)

    def is_subset(self, other: 'Flags') -> bool:
        """Returns ``True`` if self has the same or fewer permissions as other."""
        if isinstance(other, Flags):
            return (self.value & other.value) == self.value
        else:
            raise TypeError(f"cannot compare {self.__class__.__name__} with {other.__class__.__name__}")

    def is_superset(self, other: 'Flags') -> bool:
        """Returns ``True`` if self has the same or more permissions as other."""
        if isinstance(other, Flags):
            return (self.value | other.value) == self.value
        else:
            raise TypeError(f"cannot compare {self.__class__.__name__} with {other.__class__.__name__}")

    def is_strict_subset(self, other: 'Flags') -> bool:
        """Returns ``True`` if the permissions on other are a strict subset of those on self."""
        return self.is_subset(other) and self != other

    def is_strict_superset(self, other: 'Flags') -> bool:
        """Returns ``True`` if the permissions on other are a strict superset of those on self."""
        return self.is_superset(other) and self != other

    def __len__(self):
        i = 0
        for _, enabled in self:
            if enabled:
                i += 1
        return i

    def copy(self):
        return type(self)(self.value)

    __le__ = is_subset
    __ge__ = is_superset
    __lt__ = is_strict_subset
    __gt__ = is_strict_superset

    @classmethod
    def all(cls: type[Self]) -> Self:
        value = reduce(lambda a, b: a | b, cls.VALID_FLAGS.values())
        self = cls.__new__(cls)
        self.value = value
        return self

    @classmethod
    def none(cls: type[Self]) -> Self:
        self = cls.__new__(cls)
        self.value = self.DEFAULT_VALUE
        return self



from discord.flags import flag_value, fill_with_flags
# discord.py provides some nice tools for making flags. We have to be
# careful for breaking changes however.

@fill_with_flags()
class EventFlags(Flags):
    @classmethod
    def connections(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_join_server = True
        self.player_leave_server = True
        return self

    @classmethod
    def game_states(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.server_map_change = True
        self.server_match_start = True
        self.server_warmup_end = True
        self.server_match_end = True
        self.team_capture_objective = True
        return self
    
    @classmethod
    def teams(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_change_team = True
        return self
    
    @classmethod
    def squads(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_change_squad = True
        self.squad_create = True
        self.squad_disband = True
        self.squad_change_leader = True
        return self
    
    @classmethod
    def deaths(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_kill = True
        self.player_teamkill = True
        self.player_suicide = True
        return self
    
    @classmethod
    def messages(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_message = True
        return self
    
    @classmethod
    def admin_cam(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_enter_admin_cam = True
        self.player_exit_admin_cam = True
        return self
    
    @classmethod
    def roles(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_change_role = True
        self.player_change_loadout = True
        self.player_level_up = True
        return self

    @classmethod
    def scores(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.player_score_update = True
        return self
    
    @classmethod
    def modifiers(cls: type['EventFlags']) -> 'EventFlags':
        self = cls.none()
        self.rule_violated = True
        self.arty_assigned = True
        self.arty_unassigned = True
        self.start_arty_cooldown = True
        self.cancel_arty_cooldown = True
        self.player_kicked = True
        return self
    
    @flag_value
    def player_join_server(self):
        return 1 << 0

    @flag_value
    def server_map_change(self):
        return 1 << 1

    @flag_value
    def server_match_start(self):
        return 1 << 2

    @flag_value
    def server_warmup_end(self):
        return 1 << 3

    @flag_value
    def server_match_end(self):
        return 1 << 4

    @flag_value
    def squad_create(self):
        return 1 << 5

    @flag_value
    def player_change_team(self):
        return 1 << 6

    @flag_value
    def player_change_squad(self):
        return 1 << 7

    @flag_value
    def squad_change_leader(self):
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
    def squad_disband(self):
        return 1 << 19

    @flag_value
    def team_capture_objective(self):
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
    
    @flag_value
    def player_score_update(self):
        return 1 << 26
    
    @flag_value
    def player_kicked(self):
        return 1 << 27

    def filter_logs(self, logs: Sequence['LogLine']):
        allowed_types = {type_ for type_, allowed in self if allowed}
        for log in logs:
            if log.event_type in allowed_types:
                yield log