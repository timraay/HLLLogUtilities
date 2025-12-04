import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, Union
from hllrcon.data import Weapon, WeaponType

from lib.rcon.models import EventTypes, ActivationEvent, PlayerKillEvent, PlayerLeaveServerEvent, PlayerJoinServerEvent, Player, Team

from .base import Modifier
from lib.events import (on_player_kill, on_player_any_kill, on_player_leave_server, on_player_join_server,
    add_condition, add_cooldown, event_listener)
from lib.logs import LogLine
from utils import get_config

ABILITIES_ALLOWED = get_config().getboolean("OneManArty", "AllowCMDAbilities")

def is_arty(weapon_name: str, yes_no: bool = True):
    try:
        weapon = Weapon.by_id(weapon_name)
    except ValueError:
        return not yes_no

    is_arty = weapon.type == WeaponType.ARTILLERY
    if yes_no:
        return is_arty
    else:
        return not (
            is_arty
            or weapon.type in (WeaponType.AP_MINE, WeaponType.AT_MINE, WeaponType.UNKNOWN, WeaponType.ROADKILL)
            or (ABILITIES_ALLOWED and weapon.type == WeaponType.COMMANDER_ABILITY)
        )
def is_arty_condition(yes_no: bool = True):
    def decorator(func):
        return add_condition(lambda _, event: is_arty(event.weapon, yes_no=yes_no))(func)
    return decorator

def get_log_payload(player: Player, player2: Player | None = None):
    squad = player.get_squad() if player else None
    team = player.get_team() if player else None
    payload = dict()

    payload.update(
        player_name=player.name,
        player_id=player.id,
        player_team=team.name if team else None,
        player_role=player.role.name,
    )
    
    if player2:
        player2_team = player2.get_team()
        payload.update(
            player2_name=player2.name,
            player2_id=player2.id,
            player2_team=player2_team.name if player2_team else None,
            player2_role=player2.role.name,
        )

    if team:
        payload['team_name'] = team.name
    if squad:
        payload['squad_name'] = squad.name

    return {k: v for k, v in payload.items() if v is not None}

class OneArtyModifier(Modifier):

    class Config:
        id = "one_arty"
        name = "One-man arty"
        emoji = "💥"
        description = "Only one player per team may use artillery"
        enforce_name_validity = True

    @event_listener([EventTypes.activation, EventTypes.server_match_start])
    async def initialize(self, event: ActivationEvent):
        self.dap: Dict[int, Union[str, None]] = {1: None, 2: None}
        self.expire_tasks: Dict[int, Union[asyncio.Task, None]] = {1: None, 2: None}

    def is_dap(self, player: Player | None):
        if player is None or player.team_id is None:
            return False
        return self.dap[player.team_id] == player.id
    def find_dap(self, team: Team | None):
        if not team:
            return None
        player_id = self.dap[team.id]
        for player in team.get_players():
            if player.id == player_id:
                return player
        return None
    def get_dap_team_id(self, player: Player):
        for team_id, dap in self.dap.items():
            if dap == player.id:
                return team_id
        return None

    async def punish_ten_people(self, player: Player, reason: str):
        team = player.get_team()
        if team is None:
            return
        
        dap = self.find_dap(team)
        all_players = [
            p for p in team.get_players()
            if p.id != player.id and not (dap and p.id == dap.id)
        ]
        players = random.choices(all_players, k=min(8, len(all_players)))
        if dap and dap.id != player.id:
            players.append(dap)

        extended_reason = (
            "One member of your team has violated One Arty rules. To compensate the enemy, random "
            "players on your team, including yourself, were killed.\n\nThe rule in question is as follows:\n"
        ) + reason

        rcon = self.get_rcon()
        res = await asyncio.gather(
            rcon.client.message_player(player_id=player.id, message=reason),
            rcon.client.kill_player(player_id=player.id, message=reason),
            *[
                rcon.client.kill_player(player_id=p.id, message=extended_reason)
                for p in players
            ],
            return_exceptions=True
        )

        players.insert(0, player)
        punished: list[Player] = []
        for i, success in enumerate(res[1:]):

            if success is True:
                punished.append(players[i])

            elif isinstance(success, Exception):
                player = players[i]
                self.logger.exception("Failed to punish %s (%s): %s - %s",
                    player.name, player.id, type(success).__name__, success)
                
        self.logger.info("Punished %s/%s players: %s",
            len(punished), len(players), ", ".join([f"{player.name} ({player.id})" for player in punished]))

        return punished

    # --- Assign DAPs

    @on_player_any_kill()
    @is_arty_condition(True)
    @add_condition(lambda mod, event: not mod.dap[event.get_player().team_id])
    @add_cooldown("player_id", duration=10)
    async def assign_players_to_arty(self, event: PlayerKillEvent):
        player = event.get_player()
        assert player is not None

        team = player.get_team()
        assert team is not None

        self.dap[team.id] = player.id

        log = LogLine(
            event_type="arty_assigned",
            event_time=datetime.now(tz=timezone.utc),

            weapon=event.weapon,
            message=f"Assigned to {team.name} artillery",
            **get_log_payload(player)
        )
        self.session._logs.append(log)

        message = (
            "You have become your team's designated artillery player! You must"
            " adhere to a few rules:\n\n- You must not leave or swap between guns"
            "\n- You may not use any firearms\n- You may not be killed by enemies"
        )
        await self.get_rcon().client.message_player(player_id=player.id, message=message)

        commander = event.snapshot.teams[team.id - 1].get_commander()
        if commander:
            message = f"{player.name} has become your team's designated artillery player!"
            await self.get_rcon().client.message_player(player_id=commander.id, message=message)

    @on_player_any_kill()
    @is_arty_condition(True)
    @add_condition(lambda mod, event: mod.dap[event.get_player().team_id] and not mod.is_dap(event.get_player()))
    @add_cooldown("player_id", duration=30)
    async def punish_second_arty_player(self, event: PlayerKillEvent):
        player = event.get_player()
        victim = event.get_victim()
        assert player is not None

        if dap := self.find_dap(player.get_team()):
            reason = f"Only one player on your team, {dap.name}, may use artillery."
        else:
            reason = "Only one player on your team may use artillery."

        await self.punish_ten_people(player, reason=reason)

        log = LogLine(
            event_type="rule_violated",
            event_time=datetime.now(tz=timezone.utc),

            weapon=event.weapon,
            message="Killed the enemy artillery player",
            **get_log_payload(player, victim)
        )
        self.session._logs.append(log)
    
    # --- Expiring DAPs on disconnect    

    @on_player_leave_server()
    async def start_expiration_on_dap_disconnect(self, event: PlayerLeaveServerEvent):
        player = event.get_player()
        assert player is not None
        team_id = self.get_dap_team_id(player)
        if team_id and not self.expire_tasks[team_id]:
            asyncio.create_task(self.expire_dap_after_cooldown(player, team_id))

            team = event.snapshot.teams[team_id - 1]
            payload = get_log_payload(player)
            payload["team_name"] = team.name
            
            log = LogLine(
                event_type="start_arty_cooldown",
                event_time=datetime.now(tz=timezone.utc),

                message="Will be unassigned as arty player in 5 minutes",
                **payload
            )
            self.session._logs.append(log)

    @on_player_join_server()
    async def cancel_expiration_on_dap_reconnect(self, event: PlayerJoinServerEvent):
        player = event.get_player()
        assert player is not None

        team_id = self.get_dap_team_id(player)
        if team_id:
            if task := self.expire_tasks[team_id]:
                task.cancel()
            self.expire_tasks[team_id] = None

            team = event.snapshot.teams[team_id - 1]
            payload = get_log_payload(player)
            payload["team_name"] = team.name
            
            log = LogLine(
                event_type="cancel_arty_cooldown",
                event_time=datetime.now(tz=timezone.utc),

                message="Reconnected in time and stays on arty",
                **payload
            )
            self.session._logs.append(log)

    async def expire_dap_after_cooldown(self, player: Player, team_id: int):
        try:
            await asyncio.sleep(60*5)
            self.dap[team_id] = None

            team = self.session.snapshot.teams[team_id - 1]
            payload = get_log_payload(player)
            payload["team_name"] = team.name

            log = LogLine(
                event_type="arty_unassigned",
                event_time=datetime.now(tz=timezone.utc),

                message="Unassigned from arty due to being offline",
                **payload
            )
            self.session._logs.append(log)

            commander = team.get_commander()
            if commander:
                message = "Your artillery player has been offline for 5 minutes. His role is now free for someone else to take."
                await self.get_rcon().client.message_player(player_id=commander.id, message=message)
        
        except Exception:
            self.logger.exception("Failed to properly unassign arty player after cooldown")
                
        finally:
            self.expire_tasks[team_id] = None
            self.dap[team_id] = None
    
    # --- Punish killing the DAP

    @on_player_kill()
    async def punish_killing_a_dap(self, event: PlayerKillEvent):
        player = event.get_player()
        victim = event.get_victim()
        assert player is not None

        if self.is_dap(victim):
            reason = "You are not allowed to kill the enemy's designated artillery player!"
            await self.punish_ten_people(player, reason=reason)

            log = LogLine(
                event_type="rule_violated",
                event_time=datetime.now(tz=timezone.utc),

                weapon=event.weapon,
                message="Killed the enemy artillery player",
                **get_log_payload(player, victim)
            )
            self.session._logs.append(log)
    
    # --- Punish the use of firearms as a DAP
    
    @on_player_kill()
    @is_arty_condition(False)
    async def punish_firearm_usage_as_dap(self, event: PlayerKillEvent):
        player = event.get_player()
        if self.is_dap(player):
            assert player is not None

            reason = "As an artillery player you are not allowed to use any firearms!"
            await self.punish_ten_people(player, reason=reason)

            log = LogLine(
                event_type="rule_violated",
                event_time=datetime.now(tz=timezone.utc),

                weapon=event.weapon,
                message="Used a firearm as an artillery player",
                **get_log_payload(player, event.get_victim())
            )
            self.session._logs.append(log)
    

