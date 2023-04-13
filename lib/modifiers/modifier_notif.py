import asyncio

from .base import Modifier
from lib.info.events import on_iteration, add_condition
from lib.info.models import IterationEvent

MODIFIER_NOTIFICATION_MSG = (
    "[  HLL LOG UTILITIES  ]\n"
    "This server is using a custom ruleset! The following modifiers are currently active:\n\n"
    "---------------------------------------------------"
    "\n\n{}\n\n"
    "---------------------------------------------------"
)

def has_other_modifiers_condition(func):
    return add_condition(lambda modifier, _: modifier.session.modifier_flags)(func)

class ModifierNotifModifier(Modifier):

    class Config:
        id = "modifier_notif"
        name = "Modifier Notifications"
        emoji = "⚙️"
        description = "Notify players of active modifiers"
        hidden = True

    def get_modifier_notif_msg(self):
        modifiers = list()
        for modifier in self.session.modifiers:
            if not modifier.config.hidden:
                modifiers.append(modifier.config.name.upper() + "\n" + modifier.config.description)
        return MODIFIER_NOTIFICATION_MSG.format("\n\n".join(modifiers))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.steamids = set()

    @on_iteration()
    @has_other_modifiers_condition
    async def notify_players_of_active_mods(self, event: IterationEvent):
        all_players = event.root.get('players', ())
        players = list()
        for player in all_players:
            if player.steamid not in self.steamids:
                players.append(player)
        
        if players:
            message = self.get_modifier_notif_msg()
            await asyncio.gather(*[
                self.rcon.send_direct_message(
                    message=message,
                    target=player
                ) for player in players
            ])
        
        self.steamids = {player.steamid for player in all_players}
