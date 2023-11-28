from .base import Modifier
from lib.info.events import on_player_any_kill
from lib.info.models import PlayerKillEvent
from lib.mappings import WEAPONS, BASIC_CATEGORIES

class BoltActionsOnlyModifier(Modifier):

    class Config:
        id = "bolt_only"
        name = "Bolt-Actions Only"
        emoji = "🪨"
        description = "Disallow certain players from playing squad leader"
        enforce_name_validity = False

    @on_player_any_kill()
    async def handle_kills(self, event: PlayerKillEvent):
        weapon = WEAPONS.get(weapon)
        category = BASIC_CATEGORIES.get(weapon)
        
        if category is None:
            return
        
        if category in {
            "Bolt-Action Rifle",
            "Pistol",
            "Melee",
            "Flamethrower",
            "Grenade",
            "Anti-Tank",
            "Ability",
        }:
            return
        
        if weapon == "Satchel Charge":
            return
        
        if "Roadkill" in weapon:
            return
        
        await self.rcon.kill_player(event.player, reason="You are only allowed to use Bolt Action rifles!")
