from datetime import datetime, timedelta, timezone
import math

from .base import Modifier
from lib.info.events import on_iteration, add_condition
from lib.info.models import IterationEvent
from lib.storage import LogLine
from lib.rcon import get_name_from_steam

REPLACE_SYMBOL = '⊗'
KICK_REASON = (
    "[ KICKED BY HLL LOG UTILITIES ]\n\n"
    "Due to a game bug, your name is incompatible with certain custom functionalities. "
    "Your name must not contain a SPACE or SPECIAL CHARACTER at the position of the " + REPLACE_SYMBOL + " symbol:"
    "\n\n>>>   {}   <<<\n\n"
    "To be able to join, you need to change your name and then restart your game.\n\n"
    "For more information, you can refer to the HLU FAQs.\n"
    "https://github.com/timraay/HLLLogUtilities#FAQ"
)
BAN_REASON = (
    "[ KICKED BY HLL LOG UTILITIES ]\n\n"
    "Due to a game bug, your name is incompatible with certain custom functionalities. "
    "Your name must not contain a SPACE or SPECIAL CHARACTER at the position of the " + REPLACE_SYMBOL + " symbol:"
    "\n\n>>>   {}   <<<\n\n"
    "To be able to join, you need to change your name and then restart your game.\n\n"
    "This ban should expire immediately, not after an hour. Ask a server admin to remove "
    "the ban if this is not the case.\n\n"
    "For more information, you can refer to the HLU FAQs.\n"
    "https://github.com/timraay/HLLLogUtilities#FAQ"
)

def should_enforce(func):
    return add_condition(lambda modifier, _: modifier.session.kick_incompatible_names)(func)

def assign_str(text: str, i: int, char: str):
    text = list(text)
    text[i] = char
    return "".join(text)

class EnforceNameValidityModifier(Modifier):

    class Config:
        id = "enforce_name_validity"
        name = "Enforce Name Validity"
        emoji = "⚙️"
        description = "Kick players whose name prevents detailed information from being gathered"
        hidden = True

    @on_iteration(timeout=30)
    @should_enforce
    async def kick_players_with_invalid_names(self, event: IterationEvent):
        players = event.root.get('players', ())
        for player in players:
            if player.is_incompatible_name:
                print(player.name)
                
                # Find character that has to be replaced
                name = player.name
                full_name = await get_name_from_steam(player.steamid, player.name)
                
                char_i = 19
                for i, char in enumerate(full_name):
                    char_i -= math.ceil(len(char.encode()) / 3) - 1
                    if i + 1 >= char_i:
                        break
                full_name = full_name.encode('ascii', 'replace').decode()

                if name.endswith(' ') and full_name[char_i] != ' ':
                    reason = assign_str(name, -1, REPLACE_SYMBOL)
                else:
                    reason = assign_str(full_name, char_i, REPLACE_SYMBOL)

                # Kick the player
                if name.endswith(' '):
                    await self.rcon.kick_player(
                        player=player,
                        reason=KICK_REASON.format(reason)
                    )
                else:
                    await self.rcon.ban_player(
                        player=player,
                        time=timedelta(hours=1),
                        reason=BAN_REASON.format(reason)
                    )
                    await self.rcon.unban_player(
                        steamid=player.steamid
                    )

                # Log the action
                squad = player.get('squad') if player else None
                team = (squad.get('team') if squad else None) or (player.get('team') if player else None)
                payload = dict()

                player_team = player.get('team', team)
                payload.update(
                    player_name=player.name,
                    player_steamid=player.steamid,
                    player_team=player_team.name if player_team else None,
                    player_role=player.get('role'),
                )
                
                if team:
                    payload['team_name'] = team.name
                if squad:
                    payload['squad_name'] = squad.name

                log = LogLine(
                    type="player_kicked",
                    event_time=datetime.now(tz=timezone.utc),

                    message="Incompatible name `%s`" % reason,
                    **{k: v for k, v in payload.items() if v is not None}
                )
                self.session._logs.append(log)
