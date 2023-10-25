import asyncio

from .base import Modifier
from lib.info.events import on_activation, on_iteration
from lib.info.models import ActivationEvent, IterationEvent, Player

NO_MEDIC_MESSAGE = (
    "[  HLL LOG UTILITIES  ]\n"
    "Due to a game bug, Medics are not allowed to be used."
)
class NoMedicModifier(Modifier):

    class Config:
        id = "no_medic"
        name = "No Medic"
        emoji = "💉"
        description = "Medic role cannot be used during the match"
        enforce_name_validity = True

    @on_activation()
    async def initialize(self, event: ActivationEvent):
        self.watchlist = set()

    @on_iteration(timeout=25)
    async def handle_role_changes(self, event: IterationEvent):
        coros = list()
        for player in event.root.players:
            if player.role == "Medic" and not player.steamid in self.watchlist:
                # The player currently has a non-allowed role
                self.logger.info('Player %s (%s) has non-allowed role "%s", double-switching...', player.name, player.steamid, player.role)
                coros.append(self.remove_from_squad(player, NO_MEDIC_MESSAGE))
        
        # Execute all punishments at once
        await asyncio.gather(*coros)


    async def remove_from_squad(self, player: Player, message: str = None):
        if player.steamid in self.watchlist:
            # Silently ignore request because it's already being dealt with
            return
        
        self.logger.info("Removing %s (%s) from their squad", player.name, player.steamid)

        # First, we kill the player. If the player is alive, we can show him
        # a nice custom message too!
        was_killed = await self.rcon.kill_player(
            player=player,
            reason=message.replace('"', '\\"')
        )

        if not was_killed:
            # Player is dead already. This means we can perform a seamless
            # double-switch. Nice!
            await self.rcon.move_player_to_team(player)
            await self.rcon.move_player_to_team(player)
            if message:
                await self.rcon.send_direct_message(message=message, target=player)
        
        else:
            # When the player is alive things become a bit harder. Let's wait
            # a bit first, then we double-switch him.

            try:
                # Indicate that this player is being dealt with already to avoid
                # conflicts.
                self.watchlist.add(player.steamid)
                await asyncio.sleep(5)
                await self.rcon.move_player_to_team(player)
                await asyncio.sleep(1)
                await self.rcon.move_player_to_team(player)

            finally:
                # Just making sure it always gets removed
                if player.steamid in self.watchlist:
                    self.watchlist.remove(player.steamid)
        
        # Just to be sure, let's see if the player is actually on the right team
        # after everything.
        await asyncio.sleep(3)
        await self.ensure_correct_team(player, player.team.name)

    async def ensure_correct_team(self, player: Player, expected_team: str):
        playerinfo = await self.rcon.exec_command(f'playerinfo {player.name}')
        raw = dict()
        for line in playerinfo.strip('\n').split("\n"):
            if ": " not in line:
                self.logger.warning("Invalid info line: %s", line)
                continue
            key, val = line.split(": ", 1)
            raw[key.lower()] = val

        if raw['team'].lower() != expected_team.lower():
            self.logger.warning('Expected team of player %s to be %s but got %s, switching...', player.name, expected_team.lower(), raw['team'].lower())
            await self.rcon.move_player_to_team(player)
