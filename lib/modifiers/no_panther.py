import asyncio
from datetime import datetime, timezone

from .base import Modifier
from lib.storage import LogLine
from lib.info.events import on_player_any_kill, PlayerKillEvent, add_condition, add_cooldown, CooldownType
from lib.mappings import WEAPONS, VEHICLES

class NoPantherModifier(Modifier):

    class Config:
        id = "no_panther"
        name = "No Panther"
        emoji = "🚜"
        description = "Panther tanks cannot be used during the match"

    @on_player_any_kill()
    @add_condition(lambda _, event: VEHICLES.get(WEAPONS.get(event.weapon, event.weapon)) == "Panther")
    @add_cooldown(CooldownType.squad, duration=10)
    async def punish_on_panther_usage(self, event: PlayerKillEvent):
        player = event.player

        log = LogLine.from_event(event)
        log.type = "rule_violated"
        log.event_time=datetime.now(tz=timezone.utc)
        log.message = "Used a Panther in combat"
        self.session._logs.append(log)

        reason = "The use of Panthers this match has been disallowed."
        await asyncio.gather(*[
            self.rcon.kill_player(p, reason)
            for p in player.squad.players
        ])

        commander = player.team.leader if player.get('team') else None
        if commander:
            await self.rcon.kill_player(commander, reason)
            await self.rcon.send_direct_message(reason + "\n\nAs a commander, you should not be spawning these tanks.", commander)
        