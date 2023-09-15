import asyncio

from .base import Modifier
from lib.info.events import on_iteration, add_condition
from lib.info.models import IterationEvent

MODIFIER_NOTIFICATION_MSG = (
    "[  HLL LOG UTILITIES  ]\n"
    "{0}\n\n"
    "---------------------------------------------------"
    "\n\n{1}\n\n"
    "---------------------------------------------------"
)

MODIFIERS_REMOVED_MSG = (
    "[  HLL LOG UTILITIES  ]\n"
    "An Admin has disabled all active modifiers."
)

class ModifierNotifModifier(Modifier):

    class Config:
        id = "modifier_notif"
        name = "Modifier Notifications"
        emoji = "⚙️"
        description = "Notify players of active modifiers"
        hidden = True

    def get_modifier_notif_msg(self, update=False):
        if update:
            title = "An Admin has updated the current ruleset! The following modifiers are now active:"
        else:
            title = "This server is using a custom ruleset! The following modifiers are currently active:"

        modifiers = list()
        for modifier in self.session.modifiers:
            if not modifier.config.hidden:
                modifiers.append(modifier.config.name.upper() + "\n" + modifier.config.description)

        if modifiers:
            return MODIFIER_NOTIFICATION_MSG.format(title, "\n\n".join(modifiers))
        else:
            return MODIFIERS_REMOVED_MSG

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.steamids = set()
        self.last_seen = None

    @on_iteration()
    async def notify_players_of_active_mods(self, event: IterationEvent):
        has_modifiers = bool(self.session.modifier_flags)
        send_update = self.last_seen is not None and self.last_seen != self.session.modifier_flags

        all_players = event.root.get('players', ())
        players_new = list()
        players_update = list()
        for player in all_players:
            if player.steamid not in self.steamids:
                players_new.append(player)
            elif send_update:
                players_update.append(player)

        
        if players_new and has_modifiers:
            message = self.get_modifier_notif_msg()
            await asyncio.gather(*[
                self.rcon.send_direct_message(
                    message=message,
                    target=player
                ) for player in players_new
            ])

        if players_update:
            message = self.get_modifier_notif_msg(update=True)
            await asyncio.gather(*[
                self.rcon.send_direct_message(
                    message=message,
                    target=player
                ) for player in players_update
            ])
        
        self.steamids = {player.steamid for player in all_players}
        self.last_seen = self.session.modifier_flags.copy()
