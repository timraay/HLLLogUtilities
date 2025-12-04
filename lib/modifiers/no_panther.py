import asyncio
from datetime import datetime, timezone

from .base import Modifier
from lib.events import on_player_any_kill, add_condition, add_cooldown
from lib.rcon.models import PlayerKillEvent
from hllrcon.data import Weapon, Vehicle

class NoPantherModifier(Modifier):

    class Config:
        id = "no_panther"
        name = "No Panther"
        emoji = "🚜"
        description = "Panther tanks cannot be used during the match"
        enforce_name_validity = True

    @on_player_any_kill()
    @add_condition(lambda _, event: Weapon.by_id(event.weapon_id).vehicle == Vehicle.SD_KFZ_171_PANTHER)
    @add_cooldown("player_id", duration=10)
    async def punish_on_panther_usage(self, event: PlayerKillEvent):
        player = event.get_player()

        log = event.to_log_line()
        log.event_type = "rule_violated"
        log.event_time = datetime.now(tz=timezone.utc)
        log.message = "Used a Panther in combat"
        self.session._logs.append(log)

        if player:
            rcon = self.get_rcon()
            reason = "The use of Panthers this match has been disallowed."

            if squad := player.get_squad():
                await asyncio.gather(*[
                    rcon.client.kill_player(player_id=p.id, message=reason)
                    for p in squad.get_players()
                ])

            if (team := player.get_team()) and (commander := team.get_commander()):
                await rcon.client.kill_player(commander.id, reason)
                await rcon.client.message_player(commander.id, reason + "\n\nAs a commander, you should not be spawning these tanks.")
