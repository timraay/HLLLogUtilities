import asyncio

from .base import Modifier
from lib.events import on_iteration
from lib.rcon.models import IterationEvent, Player

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
        self.player_ids: set[str] = set()
        self.last_seen = None

    @on_iteration()
    async def notify_players_of_active_mods(self, event: IterationEvent):
        has_modifiers = bool(self.session.modifier_flags)
        send_update = self.last_seen is not None and self.last_seen != self.session.modifier_flags

        players_new: list[Player] = list()
        players_update: list[Player] = list()
        for player in event.snapshot.players:
            if player.id not in self.player_ids:
                players_new.append(player)
            elif send_update:
                players_update.append(player)

        
        if players_new and has_modifiers:
            rcon = self.get_rcon()
            message = self.get_modifier_notif_msg()
            await asyncio.gather(*[
                rcon.client.message_player(
                    message=message,
                    player_id=player.id,
                ) for player in players_new
            ])

        if players_update:
            rcon = self.get_rcon()
            message = self.get_modifier_notif_msg(update=True)
            await asyncio.gather(*[
                rcon.client.message_player(
                    message=message,
                    player_id=player.id,
                ) for player in players_update
            ])
        
        self.player_ids = {player.id for player in event.snapshot.players}
        self.last_seen = self.session.modifier_flags.copy()
