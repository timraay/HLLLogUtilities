from .base import Modifier
from .no_panther import NoPantherModifier
from .one_arty import OneArtyModifier

from typing import TYPE_CHECKING, Tuple, Type, Union

if TYPE_CHECKING:
    from lib.session import HLLCaptureSession

__all__ = (
    'ALL_MODIFIERS',
    'get_modifier',
    'Modifier',
    'ModifierFlags',
)

ALL_MODIFIERS: Tuple[Type[Modifier], ...] = (
    NoPantherModifier,
    OneArtyModifier,
)


from lib.info.types import Flags
from discord.flags import flag_value, fill_with_flags

@fill_with_flags()
class ModifierFlags(Flags):

    @flag_value
    def no_panther(self):
        return 1 << 0

    @flag_value
    def one_arty(self):
        return 1 << 1

    def get_modifier_types(self):
        for modifier_id, enabled in self:
            if enabled:
                yield next((m for m in ALL_MODIFIERS if m.config.id == modifier_id), None)
