from .base import Modifier
from .modifier_notif import ModifierNotifModifier
from .no_panther import NoPantherModifier
from .one_arty import OneArtyModifier

from typing import Tuple, Type

__all__ = (
    'ALL_MODIFIERS',
    'Modifier',
    'ModifierFlags',

    'ModifierNotifModifier',
    'NoPantherModifier',
    'OneArtyModifier',
)

ALL_MODIFIERS: Tuple[Type[Modifier], ...] = (
    ModifierNotifModifier,
    NoPantherModifier,
    OneArtyModifier,
)

INTERNAL_MODIFIERS: Tuple[Type[Modifier], ...] = tuple(
    modifier for modifier in ALL_MODIFIERS
    if modifier.config.hidden
)


from lib.flags import Flags
from discord.flags import flag_value, fill_with_flags

@fill_with_flags()
class ModifierFlags(Flags):

    @flag_value
    def no_panther(self):
        return 1 << 0

    @flag_value
    def one_arty(self):
        return 1 << 1

    # @flag_value
    # def no_medic(self):
    #     return 1 << 2

    def get_modifier_types(self):
        for modifier_id, enabled in self:
            if enabled:
                modifier = next((m for m in ALL_MODIFIERS if m.config.id == modifier_id), None)
                if modifier:
                    yield modifier
