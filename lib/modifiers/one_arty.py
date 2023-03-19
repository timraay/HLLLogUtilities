import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, Union

from .base import Modifier
from lib.info.events import (on_player_kill, on_player_any_kill, on_player_leave_server, on_player_join_server,
    add_condition, add_cooldown, CooldownType, event_listener)
from lib.info.models import ActivationEvent, PlayerKillEvent, PlayerLeaveServerEvent, PlayerJoinServerEvent, Player, Team
from lib.storage import LogLine
from lib.mappings import WEAPONS, BASIC_CATEGORIES

def is_arty(weapon: str, yes_no: bool = True):
    res = BASIC_CATEGORIES.get(WEAPONS.get(weapon, weapon)) == "Artillery"
    return res if yes_no else not res
def is_arty_condition(yes_no: bool = True):
    def decorator(func):
        return add_condition(lambda _, event: is_arty(event.weapon, yes_no=yes_no))(func)
    return decorator

def get_log_payload(player: Player, player2: Player = None):
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
    
    if player2:
        player2_team = player2.get('team')
        payload.update(
            player2_name=player2.name,
            player2_steamid=player2.steamid,
            player2_team=player2_team.name if player2_team else None,
            player2_role=player2.get('role'),
        )

    if team:
        payload['team_name'] = team.name
    if squad:
        payload['squad_name'] = squad.name

    return payload

class OneArtyModifier(Modifier):

    class Config:
        id = "one_arty"
        name = "One-man arty"
        emoji = "💥"
        description = "Only one player per team may use artillery"

    @event_listener(['activation', 'server_map_changed'])
    async def initialize(self, event: ActivationEvent):
        self.dap: Dict[int, Union[str, None]] = {1: None, 2: None}
        self.expire_tasks: Dict[int, Union[asyncio.Task, None]] = {1: None, 2: None}

    def is_dap(self, player: Player):
        return player.team and (self.dap[player.team.id] == player.steamid)
    def find_dap(self, team: Team):
        return team.root.find_players(single=True, steamid=self.dap[team.id])
    def get_dap_team_id(self, player: Player):
        for team_id, dap in self.dap.items():
            if dap == player.steamid:
                return team_id
        return None

    async def punish_ten_people(self, player: Player, reason: str):
        dap = self.find_dap(player.team)
        all_players = [p for p in player.team.players
            if p.steamid != player.steamid and not (dap and p.steamid == dap.steamid)]
        players = random.choices(all_players, k=min(8, len(all_players)))
        if dap:
            players.append(dap)

        extended_reason = (
            "One member of your team has violated One Arty rules. To compensate the enemy, random "
            "players on your team, including yourself, were killed.\n\nThe rule in question is as follows:\n"
        ) + reason

        res = await asyncio.gather(
            self.rcon.send_direct_message(message=reason, target=player),
            self.rcon.kill_player(player, reason=reason),
            *[
                self.rcon.kill_player(p, reason=extended_reason)
                for p in players
            ],
            return_exceptions=True
        )

        players.insert(0, player)
        punished = list()
        for i, success in enumerate(res[1:]):

            if success == True:
                punished.append(players[i])

            elif isinstance(success, Exception):
                player = players[i]
                self.logger.exception("Failed to punish %s (%s): %s - %s",
                    player.name, player.steamid, type(success).__name__, success)
                
        self.logger.info("Punished %s/%s players: %s",
            len(punished), len(players), ", ".join([f"{player.name} ({player.steamid})" for player in punished]))

        return punished

    # --- Assign DAPs

    @on_player_any_kill()
    @is_arty_condition(True)
    @add_condition(lambda mod, event: not mod.dap[event.player.team.id])
    @add_cooldown(CooldownType.player, duration=10)
    async def assign_players_to_arty(self, event: PlayerKillEvent):
        player = event.player
        team_id = player.team.id

        self.dap[team_id] = player.steamid

        log = LogLine(
            type="arty_assigned",
            event_time=datetime.now(tz=timezone.utc),

            weapon=event.weapon,
            message=f"Assigned to {player.team.name} artillery",
            **get_log_payload(player)
        )
        self.session._logs.append(log)

        message = (
            "You have become your team's designated artillery player! You must"
            "adhere to a few rules:\n\n- You must not leave or swap between guns"
            "\n- You may not use any firearms\n- You may not be killed by enemies"
        )
        await self.rcon.send_direct_message(target=player, message=message)

        commander = self.session.info.find_teams(single=True, id=player.team.id).leader
        if commander:
            message = f"{event.player.name} has become your team's designated artillery player!"
            await self.rcon.send_direct_message(message=message, target=commander)

    @on_player_any_kill()
    @is_arty_condition(True)
    @add_condition(lambda mod, event: mod.dap[event.player.team.id] and not mod.is_dap(event.player))
    @add_cooldown(CooldownType.player, duration=30)
    async def punish_second_arty_player(self, event: PlayerKillEvent):
        player = event.player
        other = event.other

        if dap := self.find_dap(player.team):
            reason = f"Only one player on your team, {dap.name}, may use artillery."
        else:
            reason = "Only one player on your team may use artillery."

        await self.punish_ten_people(player, reason=reason)

        log = LogLine(
            type="rule_violated",
            event_time=datetime.now(tz=timezone.utc),

            weapon=event.weapon,
            message="Killed the enemy artillery player",
            **get_log_payload(player, other)
        )
        self.session._logs.append(log)
    
    # --- Expiring DAPs on disconnect    

    @on_player_leave_server()
    async def start_expiration_on_dap_disconnect(self, event: PlayerLeaveServerEvent):
        player = event.player
        team_id = self.get_dap_team_id(player)
        if team_id and not self.expire_tasks[team_id]:
            await self.expire_dap_after_cooldown(player, team_id)

            team = event.root.find_teams(single=True, id=team_id)
            payload = get_log_payload(player)
            payload["team_name"] = team.name
            
            log = LogLine(
                type="start_arty_cooldown",
                event_time=datetime.now(tz=timezone.utc),

                message="Will be unassigned as arty player in 5 minutes",
                **payload
            )
            self.session._logs.append(log)

    @on_player_join_server()
    async def cancel_expiration_on_dap_reconnect(self, event: PlayerJoinServerEvent):
        player = event.player
        team_id = self.get_dap_team_id(player)
        if team_id:
            if self.expire_tasks[team_id]:
                self.expire_tasks[team_id].cancel()
            self.expire_tasks[team_id] = None

            team = event.root.find_teams(single=True, id=team_id)
            payload = get_log_payload(player)
            payload["team_name"] = team.name
            
            log = LogLine(
                type="cancel_arty_cooldown",
                event_time=datetime.now(tz=timezone.utc),

                message="Reconnected in time and stays on arty",
                **payload
            )
            self.session._logs.append(log)

    async def expire_dap_after_cooldown(self, player: Player, team_id: int):
        try:
            await asyncio.sleep(60*5)
            self.dap[team_id] = None

            team = self.session.info.find_teams(single=True, id=team_id)
            payload = get_log_payload(player)
            payload["team_name"] = team.name

            log = LogLine(
                type="arty_unassigned",
                event_time=datetime.now(tz=timezone.utc),

                message=f"Unassigned {player.team.name} from artillery due to being offline",
                **payload
            )
            self.session._logs.append(log)

            commander = team.leader
            if commander:
                message = "Your artillery player has been offline for 5 minutes. His role is now free for someone else to take."
                await self.rcon.send_direct_message(message=message, target=commander)
                
        finally:
            self.expire_tasks[team_id] = None
    
    # --- Punish killing the DAP

    @on_player_kill()
    async def punish_killing_a_dap(self, event: PlayerKillEvent):
        player = event.player
        other = event.other
        if self.is_dap(other):
            reason = "You are not allowed to kill the enemy's designated artillery player!"
            await self.punish_ten_people(player, reason=reason)

            log = LogLine(
                type="rule_violated",
                event_time=datetime.now(tz=timezone.utc),

                weapon=event.weapon,
                message="Killed the enemy artillery player",
                **get_log_payload(player, other)
            )
            self.session._logs.append(log)
    
    # --- Punish the use of firearms as a DAP
    
    @on_player_kill()
    @is_arty_condition(False)
    async def punish_firearm_usage_as_dap(self, event: PlayerKillEvent):
        player = event.player
        if self.is_dap(player):
            reason = "As an artillery player you are not allowed to use any firearms!"
            await self.punish_ten_people(player, reason=reason)

            log = LogLine(
                type="rule_violated",
                event_time=datetime.now(tz=timezone.utc),

                weapon=event.weapon,
                message="Used a firearm as an artillery player",
                **get_log_payload(player, event.other)
            )
            self.session._logs.append(log)
    

