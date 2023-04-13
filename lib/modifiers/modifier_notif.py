from .base import Modifier
from lib.info.events import on_activation, on_player_join_server, add_condition
from lib.info.models import ActivationEvent, PlayerJoinServerEvent

MODIFIER_NOTIFICATION_MSG = (
    "This server is using a custom ruleset! The following modifiers are"
    " currently active:\n\n{}\n\nFor more information, look up HLL Log"
    " Utilities online."
)

def has_other_modifiers_condition(func):
    return add_condition(lambda modifier, _: modifier.session.modifier_flags)(func)

class ModifierNotifModifier(Modifier):

    class Config:
        id = "_internal"
        name = "Internal HLU Mechanics"
        emoji = "⚙️"
        description = "A collection of functions used internally by HLU"
        hidden = True

    def get_modifier_notif_msg(self):
        modifiers = list()
        for modifier in self.session.modifiers:
            if not modifier.config.hidden:
                modifiers.append(modifier.config.name.upper() + "\n" + modifier.config.description)
        return MODIFIER_NOTIFICATION_MSG.format("\n\n".join(modifiers))

    @on_activation()
    @has_other_modifiers_condition
    async def notify_all_on_activation(self, event: ActivationEvent):
        message = self.get_modifier_notif_msg()
        await self.rcon.send_direct_message(
            message=message,
            target=None
        )
    
    @on_player_join_server()
    @has_other_modifiers_condition
    async def notify_player_on_join(self, event: PlayerJoinServerEvent):
        message = self.get_modifier_notif_msg()
        await self.rcon.send_direct_message(
            message=message,
            target=event.player
        )

