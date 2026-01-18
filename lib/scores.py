import operator
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel
from typing import Any, Iterable, Mapping, TypeVar, Union, TYPE_CHECKING
import logging
from hllrcon.data import Weapon, WeaponType, Faction

from lib import mappings
from lib.rcon.models import EventTypes
from utils import toTable, side_by_side

IntDictT = TypeVar('IntDictT', bound=Mapping[Any, 'int | PlayerScore | PlayerData'])

if TYPE_CHECKING:
    from lib.storage import LogLine

def combine_dicts(a: IntDictT, b: IntDictT, op=operator.add) -> IntDictT:
    return dict(list(a.items()) + list(b.items()) +
        [(k, op(a[k], b[k])) for k in set(b) & set(a)])  # type: ignore


class EFaction(Enum):
    def __str__(self):
        return self.name
    Allies = "Allies"
    Axis = "Axis"
    Any = "Any"

class PlayerScore(BaseModel):
    combat: int = 0
    offense: int = 0
    defense: int = 0
    support: int = 0

    def __add__(self, other: 'PlayerScore'):
        if not isinstance(other, PlayerScore):
            return NotImplemented
        return PlayerScore(**combine_dicts(self.model_dump(), other.model_dump()))
    def __sub__(self, other: 'PlayerScore'):
        if not isinstance(other, PlayerScore):
            return NotImplemented
        return PlayerScore(**combine_dicts(self.model_dump(), other.model_dump(), op=operator.sub))



class MatchGroup:
    def __init__(self, matches: list = []):
        self.matches: list['MatchData'] = list(matches)
    
    def __len__(self):
        return self.num_matches_played
    def __iter__(self):
        yield from self.matches
    def __bool__(self):
        return True
    
    @classmethod
    def from_logs(cls, logs: list['LogLine']):
        matches = list()
        match_logs = list()
        
        while logs:
            log = logs.pop(0)
            try:
                log_type = EventTypes(log.event_type)
            except ValueError:
                continue

            if log_type == EventTypes.server_match_start:
                if match_logs:
                    match_data = MatchData.from_logs(match_logs)
                    matches.append(match_data)
                    match_logs.clear()

            match_logs.append(log)
        
        match_data = MatchData.from_logs(match_logs)
        matches.append(match_data)

        return cls(matches=matches)
                
    def get_matches_for_player(self, player: Union['PlayerData', str]):
        if not isinstance(player, PlayerData):
            player_data = self.stats.find_player(player)
        if not player_data:
            raise ValueError('Player with Steam ID %s could not be found' % player)
        matches = [match for match in self.matches if player_data in match.players]
        return MatchGroup(matches)

    @property
    def stats(self):
        return DataStore.union(*self.matches)
    
    @property
    def num_matches_played(self):
        return len(self.matches)
    @property
    def num_winners_positive_kdr(self):
        num = 0
        for match in self.matches:
            if match.get_data_for_faction(match.winner).kill_death_ratio >= 1.0:
                num += 1
        return num
    
    @property
    def total_match_length(self):
        return self.stats.duration
    @property
    def avg_match_length(self):
        return (self.total_match_length / self.num_matches_played) if self.num_matches_played else timedelta()
    
    @property
    def shortest_match(self):
        return sorted(self.matches, key=lambda m: m.duration)[0]

    @property
    def winner_kills(self):
        return sum((match.total_allied_kills if match.winner == EFaction.Allies else match.total_axis_kills) for match in self.matches)
    @property
    def loser_kills(self):
        return sum((match.total_allied_kills if match.winner != EFaction.Allies else match.total_axis_kills) for match in self.matches)
    @property
    def winner_deaths(self):
        return sum((match.total_allied_deaths if match.winner == EFaction.Allies else match.total_axis_deaths) for match in self.matches)
    @property
    def loser_deaths(self):
        return sum((match.total_allied_deaths if match.winner != EFaction.Allies else match.total_axis_deaths) for match in self.matches)
    
    def to_dict(self):
        return dict(
            matches=[
                dict(
                    map=match.map,
                    duration=match.duration,
                ) for match in self.matches
            ],
            stats=self.stats.to_dict()
        )


class DataStore:
    """A storage to collect and access various stats
    from players.
    """
    def __init__(self, duration: timedelta, players: Iterable["PlayerData"]):
        self.duration = duration
        self.players = list(players)
    
    @classmethod
    def union(cls, *data):
        res = cls(timedelta(), list())
        for match in data:
            res += match
        return res

    @property
    def total_kills(self):
        return sum(p.kills for p in self.players)
    @property
    def total_teamkills(self):
        return sum(p.teamkills for p in self.players)
    @property
    def total_deaths(self):
        return sum(p.deaths for p in self.players)
    @property
    def total_suicides(self):
        return sum(p.suicides for p in self.players)
    @property
    def total_score(self):
        return sum((p.score for p in self.players), start=PlayerScore())
    @property
    def total_time_played(self):
        return timedelta(seconds=sum(p.seconds_played for p in self.players))
    @property
    def total_time_alive(self):
        return timedelta(seconds=sum(p.seconds_alive for p in self.players))
    
    @property
    def kill_death_ratio(self):
        return self.total_kills / self.total_deaths
    
    @property
    def total_allied_kills(self):
        return sum(p.allied_kills for p in self.players)
    @property
    def total_axis_kills(self):
        return sum(p.axis_kills for p in self.players)
    @property
    def total_allied_deaths(self):
        return sum(p.allied_deaths for p in self.players)
    @property
    def total_axis_deaths(self):
        return sum(p.axis_deaths for p in self.players)
    @property
    def total_allied_score(self) -> 'PlayerScore':
        return sum((p.allied_score for p in self.players), start=PlayerScore())
    @property
    def total_axis_score(self) -> 'PlayerScore':
        return sum((p.axis_score for p in self.players), start=PlayerScore())
    @property
    def total_allied_time_played(self):
        return timedelta(seconds=sum(p.allied_seconds_played for p in self.players))
    @property
    def total_axis_time_played(self):
        return timedelta(seconds=sum(p.axis_seconds_played for p in self.players))
    @property
    def total_allied_time_alive(self):
        return timedelta(seconds=sum(p.allied_seconds_alive for p in self.players))
    @property
    def total_axis_time_alive(self):
        return timedelta(seconds=sum(p.axis_seconds_alive for p in self.players))

    @property
    def avg_kills(self):
        return self.total_kills / len(self.players)
    @property
    def avg_teamkills(self):
        return self.total_teamkills / len(self.players)
    @property
    def avg_deaths(self):
        return self.total_deaths / len(self.players)
    @property
    def avg_time_played(self):
        return self.total_time_played / len(self.players)
    @property
    def avg_kills_per_min(self):
        return self.total_kills * 60 / self.duration.total_seconds()
    @property
    def avg_deaths_per_min(self):
        return self.total_deaths * 60 / self.duration.total_seconds()

    @staticmethod
    def map_weapons(weapons: dict[Weapon, int], *mappings: dict[Weapon, str], skip_unmapped=False) -> dict[str, int]:
        if not mappings:
            return {
                weapon.name: value
                for weapon, value in weapons.items()
            }

        new_map = {old: new for d in mappings[::-1] for old, new in d.items()}

        res: dict[str, int] = {}
        for weapon, value in weapons.items():
            if weapon in new_map:
                weapon_name = new_map[weapon]
            elif skip_unmapped:
                continue
            else:
                weapon_name = weapon.name

            if weapon_name in res:
                res[weapon_name] += value
            else:
                res[weapon_name] = value

        return res

    def weapons_killed_with(self, *mappings: dict[Weapon, str], skip_unmapped=False) -> dict[str, int]:
        all_weapons: dict[Weapon, int] = {}
        for player in self.players:
            all_weapons = combine_dicts(all_weapons, player.weapons)
        return self.map_weapons(all_weapons, *mappings, skip_unmapped=skip_unmapped)
    def weapons_died_to(self, *mappings, skip_unmapped=False) -> dict[str, int]:
        all_weapons: dict[Weapon, int] = {}
        for player in self.players:
            all_weapons = combine_dicts(all_weapons, player.causes)
        return self.map_weapons(all_weapons, *mappings, skip_unmapped=skip_unmapped)
    def weapons_teamkilled_with(self, *mappings, skip_unmapped=False) -> dict[str, int]:
        weapons_killed_with: dict[Weapon, int] = {}
        for player in self.players:
            weapons_killed_with = combine_dicts(weapons_killed_with, player.weapons)

        weapons_died_to: dict[Weapon, int] = {}
        for player in self.players:
            weapons_died_to = combine_dicts(weapons_died_to, player.weapons)

        all_weapons: dict[Weapon, int] = {
            name: amount for name, amount
            in combine_dicts(weapons_died_to, weapons_killed_with, operator.sub).items()
            if amount > 0
        }
        return self.map_weapons(all_weapons, *mappings, skip_unmapped=skip_unmapped)
    
    @property
    def deaths_per_min(self) -> float:
        return round(self.total_deaths * 60 / self.duration.total_seconds(), 2)

    def find_player(self, player_id: str) -> 'PlayerData | None':
        return next((player for player in self.players if player.player_id == player_id), None)

    def __add__(self, other: 'DataStore') -> 'DataStore':
        if not isinstance(other, DataStore):
            return NotImplemented
        
        duration = self.duration + other.duration
        players = combine_dicts({p.player_id: p for p in self.players}, {p.player_id: p for p in other.players})
        return DataStore(duration, players.values())
    
    def __radd__(self, other):
        return self + other
    
    def to_text(self, single_match: bool = False):
        data = sorted(
            filter(
                lambda player: player.player_id,
                self.players
            ),
            key=lambda player: player.kills_per_minute * 1000000 - player.deaths,
            reverse=True
        )
    
        headers = ['RANK', 'NAME', 'KILLS', 'DEATHS', 'K/D', 'TKS', 'SUIC', 'STREAK', 'WEAPON', 'VICTIM', 'NEMESIS', 'COMB', 'OFF', 'DEF', 'SUPP', 'PLAYTIME'] if single_match else \
            ['RANK', 'STEAMID', 'PLAYED', 'NAME', 'KILLS', 'DEATHS', 'K/D', 'TKS', 'SUIC', 'STREAK', 'WEAPON', 'VICTIM', 'NEMESIS', 'COMB', 'OFF', 'DEF', 'SUPP', 'PLAYTIME', 'K/MIN']

        if single_match:
            output = "{: <5} {: <25} {: <6} {: <6} {: <5} {: <5} {: <5} {: <6} {: <27} {: <25} {: <25} {: <4} {: <4} {: <4} {: <4} {}".format(*headers)
        else:
            output = "{: <6} {: <13} {: <6}  {: <25} {: <6} {: <6} {: <5} {: <5} {: <5} {: <6} {: <27} {: <25} {: <25} {: <4} {: <4} {: <4} {: <4} {: <9} {}".format(*headers)
        for i, player in enumerate(data):
            output = output + '\n' + player.to_string(i+1, single_match)
        
        return output
    
    def to_csv(self, single_match: bool = False):
        data = sorted(
            filter(
                lambda player: player.player_id,
                self.players
            ),
            key=lambda player: player.kills_per_minute * 1000000 - player.deaths,
            reverse=True
        )
    
        if single_match:
            output = ",".join([
                'rank', 'player_id', 'name', 'kills', 'deaths', 'teamkills', 'suicides', 'top_killstreak', 'top_weapon_name',
                'top_weapon_kills', 'top_victim_name', 'top_victim_kills', 'top_nemesis_name', 'top_nemesis_deaths', 'combat_score',
                'offense_score', 'defense_score', 'support_score', 'seconds_played'
            ])
        else:
            output = ",".join([
                'rank', 'player_id', 'name', 'matches_played', 'kills', 'deaths', 'teamkills', 'suicides', 'top_killstreak',
                'top_weapon_name', 'top_weapon_kills', 'top_victim_name', 'top_victim_kills', 'top_nemesis_name', 'top_nemesis_deaths',
                'combat_score', 'offense_score', 'defense_score', 'support_score', 'seconds_played'
            ])

        for i, player in enumerate(data):
            output = output + '\n' + player.to_csv(i+1, single_match)
        
        return output

    def to_dict(self) -> dict[str, Any]:
        return dict(
            duration=self.duration.total_seconds(),
            players=[player.to_dict() for player in self.players]
        )


class MatchData(DataStore):
    """A particular type of DataStore that represents an in-game match
    """
    def __init__(self, players: Iterable["PlayerData"], duration: timedelta,
            map: str | None = None, team1_score: int = 0, team2_score: int = 0):

        self.map = map
        self.team1_score = int(team1_score)
        self.team2_score = int(team2_score)

        DataStore.__init__(self, duration, players)
    
    @classmethod
    def from_logs(cls, logs: list['LogLine']):
        if not logs:
            return cls(
                players=[],
                duration=timedelta()
            )

        data: dict[str, 'PlayerData'] = {}
        logs_start, logs_end = sorted((logs[0].event_time, logs[-1].event_time))
        if logs_start != logs[0].event_time: # Logs are reversed
            logs.reverse()

        match_ended = None
        map_name = None
        for log in logs:
            log_type = EventTypes(log.event_type)

            # Look for map name
            if log_type == EventTypes.server_map_change:
                if match_ended:
                    assert log.old is not None
                    map_name = mappings.parse_layer(log.old).pretty_name
                else:
                    assert log.new is not None
                    map_name = mappings.parse_layer(log.new).pretty_name
                continue

            if log_type == EventTypes.server_match_start:
                assert log.new is not None
                if not map_name:
                    map_name = " ".join(mappings.get_map_and_mode(log.new))
                continue

            elif log_type == EventTypes.server_match_end:
                assert log.new is not None
                if not map_name:
                    map_name = " ".join(mappings.get_map_and_mode(log.new))
                match_ended = log
                continue

            elif log_type not in {
                EventTypes.player_kill,
                EventTypes.player_teamkill,
                EventTypes.player_suicide,
                EventTypes.player_join_server,
                EventTypes.player_leave_server,
                EventTypes.player_change_team,
            }:
                continue

            # Get or create killer and victim data
            if log.player_id in data.keys():
                assert log.player_id is not None
                killer_data = data[log.player_id]
            else:
                assert log.player_id is not None
                assert log.player_name is not None
                killer_data = PlayerData(log.player_id, log.player_name, logs_start, logs_end)
                data[log.player_id] = killer_data
            
            if log.player2_id in data.keys():
                assert log.player2_id is not None
                victim_data = data[log.player2_id]
            elif log.player2_id:
                assert log.player2_id is not None
                assert log.player2_name is not None
                victim_data = PlayerData(log.player2_id, log.player2_name, logs_start, logs_end)
                data[log.player2_id] = victim_data
            else:
                victim_data = None
            
            killer_faction = EFaction(log.player_team) if log.player_team else EFaction.Any
            victim_faction = EFaction(log.player2_team) if log.player2_team else EFaction.Any

            if log.weapon:
                try:
                    weapon = Weapon.by_id(log.weapon)
                except ValueError:
                    weapon = Weapon(
                        id=log.weapon,
                        name=log.weapon,
                        type=WeaponType.UNKNOWN,
                        factions=set(Faction.all())
                    )
            else:
                weapon = None
            
            # Update player score
            if log.player_combat_score is not None:
                killer_data.update_score(log)

            # Process event
            if log_type == EventTypes.player_kill:
                assert victim_data is not None
                assert weapon is not None
                killer_data.update_faction(killer_faction)
                victim_data.update_faction(victim_faction)
                killer_data.kill(victim_data, weapon, killer_faction)
                victim_data.death(killer_data, weapon, victim_faction)

            elif log_type == EventTypes.player_teamkill:
                assert victim_data is not None
                assert weapon is not None
                killer_data.update_faction(killer_faction)
                victim_data.update_faction(victim_faction)
                killer_data.teamkill(victim_data, weapon, killer_faction)
                victim_data.death(killer_data, weapon, victim_faction)

            elif log_type == EventTypes.player_suicide:
                killer_data.update_faction(killer_faction)
                killer_data.suicide(killer_faction)

            elif log_type == EventTypes.player_join_server:
                killer_data.join(log.event_time)
            elif log_type == EventTypes.player_leave_server:
                killer_data.leave(log.event_time)

            # Update player faction
            elif log_type == EventTypes.player_change_team:
                if all([log.old, log.new]):
                    killer_data.update_faction(EFaction.Any)
                elif log.new:
                    killer_data.update_faction(EFaction(log.new))

        duration = logs_end - logs_start

        if match_ended:
            assert match_ended.message is not None
            return cls(
                players=data.values(),
                duration=duration,
                map=map_name,
                team1_score=int(match_ended.message.split(' - ')[0]),
                team2_score=int(match_ended.message.split(' - ')[1]),
            )
        else:
            return cls(
                players=data.values(),
                duration=duration,
                map=map_name,
            )

    @property
    def winner(self):
        if self.team1_score > self.team2_score:
            return EFaction.Allies
        elif self.team1_score < self.team2_score:
            return EFaction.Axis
        else:
            return EFaction.Any
    @property
    def loser(self):
        if self.team1_score < self.team2_score:
            return EFaction.Allies
        elif self.team1_score > self.team2_score:
            return EFaction.Axis
        else:
            return EFaction.Any
    
    def get_data_for_faction(self, faction: 'EFaction', include_unknown: bool = False):
        faction = EFaction(faction)
        if include_unknown:
            return DataStore(self.duration, [player for player in self.players if player.faction == faction or player.faction == EFaction.Any or player.faction is None])
        else:
            return DataStore(self.duration, [player for player in self.players if player.faction == faction])
    
    def to_text(self):
        return super().to_text(single_match=True)
    
    def to_csv(self):
        return super().to_csv(single_match=True)

    def to_dict(self) -> dict[str, Any]:
        out = dict(
            map=self.map,
            team1=dict(
                faction="Allies",
                score=self.team1_score
            ),
            team2=dict(
                faction="Axis",
                score=self.team2_score
            )
        )
        out.update(super().to_dict())
        return out

class PlayerData:
    def __init__(self, player_id: str, name: str, match_start: datetime | None, match_end: datetime | None):
        self.player_id: str = player_id
        self.names: dict[str, int] = {name: 1}
        self._faction: EFaction = EFaction.Any
        self.faction: EFaction | None = None
        self.kills: int = 0
        self.deaths: int = 0
        self.allied_kills: int = 0
        self.axis_kills: int = 0
        self.allied_deaths: int = 0
        self.axis_deaths: int = 0
        self.weapons: dict[Weapon, int] = {}
        self.causes: dict[Weapon, int] = {}
        self.teamkills: int = 0
        self.suicides: int = 0
        self._curr_streak: int = 0
        self.killstreak: int = 0
        self._curr_deathstreak: int = 0
        self.deathstreak: int = 0
        self._victims: dict["PlayerData", int] = {}
        self._nemeses: dict["PlayerData", int] = {}
        self._last_seen_score: PlayerScore = PlayerScore()
        self.allied_score: PlayerScore = PlayerScore()
        self.axis_score: PlayerScore = PlayerScore()
        self.score: PlayerScore = PlayerScore()
        self._seconds_played: int = 0
        self._last_seen_playtime: int = 0
        self._sess_start: datetime | None = match_start
        self._match_end: datetime | None = match_end
        self.allied_seconds_played: int = 0
        self.axis_seconds_played: int = 0
        self.num_matches_played: int = 1
    
    def __add__(self, other):
        if not isinstance(other, PlayerData):
            return NotImplemented
        
        res = PlayerData(self.player_id, self.name, None, self._match_end)

        for attr in ('kills', 'deaths', 'allied_kills', 'axis_kills', 'allied_deaths',
                     'axis_deaths', 'teamkills', 'suicides', 'allied_score', 'axis_score',
                     'score', 'allied_seconds_played', 'axis_seconds_played', 'num_matches_played'):
            res.__setattr__(attr, self.__getattribute__(attr) + other.__getattribute__(attr))
        
        for attr in ('weapons', 'causes'):
            _new_attr = combine_dicts(self.__getattribute__(attr), other.__getattribute__(attr))
            res.__setattr__(attr, _new_attr if _new_attr else {'None': 0})
        
        for attr in ('_victims', '_nemeses'):
            _new_attr = combine_dicts(self.__getattribute__(attr), other.__getattribute__(attr))
            res.__setattr__(attr, _new_attr if _new_attr is not None else {})
        
        res._seconds_played = self.seconds_played + other.seconds_played
        res.killstreak = max(self.killstreak, other.killstreak)
        res.deathstreak = max(self.deathstreak, other.deathstreak)
        res.names = combine_dicts(self.names, other.names)

        res.faction = self.faction
        res.update_faction(other._faction)
        
        return res

    def __radd__(self, other):
        return self + other
    
    def __hash__(self):
        return hash(self.player_id)
    def __eq__(self, other):
        return self.player_id == other.player_id if isinstance(other, PlayerData) else NotImplemented

    def update_faction(self, faction: EFaction):
        if self.faction is None:
            self.faction = faction
        elif self.faction == EFaction.Any:
            pass
        elif self.faction != faction:
            self.faction = EFaction.Any
        
        if faction != EFaction.Any:

            if self._faction == EFaction.Allies:
                self.allied_seconds_played += self.seconds_played - self._last_seen_playtime
                self._last_seen_playtime = self.seconds_played
            
            elif self._faction == EFaction.Axis:
                self.axis_seconds_played += self.seconds_played - self._last_seen_playtime
                self._last_seen_playtime = self.seconds_played
            
            self._faction = faction
        
        return self.faction
    
    def update_score(self, log: 'LogLine'):
        faction = self._faction
        if faction == EFaction.Any and log.player_team:
            faction = EFaction(log.player_team)

        assert log.player_combat_score is not None
        assert log.player_offense_score is not None
        assert log.player_defense_score is not None
        assert log.player_support_score is not None

        score = PlayerScore(
            combat=log.player_combat_score,
            offense=log.player_offense_score,
            defense=log.player_defense_score,
            support=log.player_support_score
        )
        score_diff = score - self._last_seen_score

        if faction == EFaction.Allies:
            self.allied_score += score_diff
        elif faction == EFaction.Axis:
            self.axis_score += score_diff

        self._faction = faction
        self.score += score_diff
        self._last_seen_score = score

    def kill(self, victim: "PlayerData", weapon: Weapon, faction: EFaction):
        self.kills += 1
        if faction == EFaction.Allies:
            self.allied_kills += 1
        elif faction == EFaction.Axis:
            self.axis_kills += 1
        
        # Prefered weapon
        try:
            self.weapons[weapon] += 1
        except KeyError:
            self.weapons[weapon] = 1

        # Killstreak
        self._curr_streak += 1
        if self._curr_streak > self.killstreak:
            self.killstreak = self._curr_streak
        # Deathstreak
        self._curr_deathstreak = 0

        # Victims
        try:
            self._victims[victim] += 1
        except KeyError:
            self._victims[victim] = 1

    def teamkill(self, victim: "PlayerData", weapon: Weapon, faction: EFaction):
        self.teamkills += 1

        # Victims
        try:
            self._victims[victim] += 1
        except KeyError:
            self._victims[victim] = 1

    def death(self, nemesis: "PlayerData", weapon: Weapon, faction: EFaction | None = None):
        self.deaths += 1
        if faction == EFaction.Allies:
            self.allied_deaths += 1
        elif faction == EFaction.Axis:
            self.axis_deaths += 1

        # Cause of death
        try:
            self.causes[weapon] += 1
        except KeyError:
            self.causes[weapon] = 1

        # Killstreak
        self._curr_streak = 0
        # Deathstreak
        self._curr_deathstreak += 1
        if self._curr_deathstreak > self.deathstreak:
            self.deathstreak = self._curr_deathstreak

        # Nemeses
        try:
            self._nemeses[nemesis] += 1
        except KeyError:
            self._nemeses[nemesis] = 1
    
    def suicide(self, faction: EFaction):
        self.deaths += 1
        self.suicides += 1
        if faction == EFaction.Allies:
            self.allied_deaths += 1
        elif faction == EFaction.Axis:
            self.axis_deaths += 1

        # Killstreak
        self._curr_streak = 0
        # Deathstreak
        self._curr_deathstreak += 1
        if self._curr_deathstreak > self.deathstreak:
            self.deathstreak = self._curr_deathstreak

    def join(self, time: datetime):
        self._sess_start = time
    def leave(self, time: datetime):
        if not self._sess_start:
            logging.warning('Player left but was already offline: %s', self.to_dict())
        else:
            self._seconds_played += int((time - self._sess_start).total_seconds())
        self._sess_start = None
        self._last_seen_score = PlayerScore()
    
    @property
    def name(self) -> str:
        return max(self.names, key=lambda x: self.names.get(x, 0))

    @property
    def victims(self) -> dict[str, int]:
        return {p.name: a for p, a in self._victims.items()}
    @property
    def nemeses(self) -> dict[str, int]:
        return {p.name: a for p, a in self._nemeses.items()}

    @property
    def kill_death_ratio(self) -> float:
        return round(self.kills/self.deaths, 2) if self.deaths else float(self.kills)
    @property
    def kills_per_match(self) -> float:
        return round(self.kills/self.num_matches_played, 2)
    @property
    def kills_per_minute(self) -> float:
        return round(self.kills / (self.seconds_played / 60), 2) if self.seconds_played else self.kills

    @property
    def weapon(self) -> Weapon | None:
        return max(self.weapons, key=lambda x: self.weapons[x]) if self.weapons else None
    @property
    def cause(self) -> Weapon | None:
        return max(self.causes, key=lambda x: self.causes[x]) if self.causes else None
    @property
    def victim(self) -> str | None:
        return max(self.victims, key=lambda x: self.victims[x]) if self.victims else None
    @property
    def nemesis(self) -> str | None:
        return max(self.nemeses, key=lambda x: self.nemeses[x]) if self.nemeses else None

    @property
    def seconds_played(self) -> int:
        return int(
            self._seconds_played + (self._match_end - self._sess_start).total_seconds()
            if self._sess_start and self._match_end
            else self._seconds_played
        )    
    
    @property
    def seconds_alive(self) -> int:
        return min(self.seconds_played, (1 + (self.score.offense + self.score.defense) // 20) * 60)
    @property
    def allied_seconds_alive(self) -> int:
        return (1 + (self.allied_score.offense + self.allied_score.defense) // 20) * 60
    @property
    def axis_seconds_alive(self) -> int:
        return (1 + (self.axis_score.offense + self.axis_score.defense) // 20) * 60

    def to_string(self, rank: int, single_match=True) -> str:
        weapon = mappings.FACTIONLESS.get(self.weapon, self.weapon.name) if self.weapon else "None"
        weapons = DataStore.map_weapons(self.weapons, mappings.VEHICLE_WEAPONS_FACTIONLESS, mappings.FACTIONLESS)
        victim = self.victim
        nemesis = self.nemesis
        playtime = self.seconds_played
        seconds = playtime % 60
        minutes = int(playtime / 60) % 60
        hours = int(playtime / 3600)
        if single_match:
            return "#{: <4} {: <25} {: <6} {: <6} {: <5} {: <5} {: <5} {: <6} {: <28}{: <25} {: <25} {: <4} {: <4} {: <4} {: <4} {}".format(
                rank,
                self.name,
                self.kills,
                self.deaths,
                self.kill_death_ratio,
                self.teamkills,
                self.suicides,
                self.killstreak,
                f"{weapon}({weapons.get(weapon, 0)})",
                f"{victim}({self.victims[victim]})" if victim else "None(0)",
                f"{nemesis}({self.nemeses[nemesis]})" if nemesis else "None(0)",
                self.score.combat,
                self.score.offense,
                self.score.defense,
                self.score.support,
                "{:0>2}:{:0>2}:{:0>2}".format(hours, minutes, seconds),
            )
        else:
            return "#{: <5} {: <17} {: >2}  {: <25} {: <6} {: <6} {: <5} {: <5} {: <5} {: <6} {: <28}{: <25} {: <25} {: <4} {: <4} {: <4} {: <4} {: <9} {}".format(
                rank,
                self.player_id,
                self.num_matches_played,
                self.name,
                self.kills,
                self.deaths,
                self.kill_death_ratio,
                self.teamkills,
                self.suicides,
                self.killstreak,
                f"{weapon}({weapons.get(weapon, 0)})",
                f"{victim}({self.victims[victim]})" if victim else "None(0)",
                f"{nemesis}({self.nemeses[nemesis]})" if nemesis else "None(0)",
                self.score.combat,
                self.score.offense,
                self.score.defense,
                self.score.support,
                "{:0>2}:{:0>2}:{:0>2}".format(hours, minutes, seconds),
                self.kills_per_minute
            )

    def to_csv(self, rank: int, single_match=True):
        weapon = mappings.FACTIONLESS.get(self.weapon, self.weapon.name) if self.weapon else "None"
        weapons = DataStore.map_weapons(self.weapons, mappings.VEHICLE_WEAPONS_FACTIONLESS, mappings.FACTIONLESS)
        victim = self.victim
        nemesis = self.nemesis

        if single_match:
            values = (
                rank,
                self.player_id,
                self.name,
                self.kills,
                self.deaths,
                self.teamkills,
                self.suicides,
                self.killstreak,
                weapon,
                weapons.get(weapon, 0),
                victim,
                self.victims[victim] if victim else 0,
                nemesis,
                self.nemeses[nemesis] if nemesis else 0,
                self.score.combat,
                self.score.offense,
                self.score.defense,
                self.score.support,
                self.seconds_played,
            )
        else:
            values = (
                rank,
                self.player_id,
                self.name,
                self.num_matches_played,
                self.kills,
                self.deaths,
                self.teamkills,
                self.suicides,
                self.killstreak,
                weapon,
                weapons.get(weapon, 0),
                victim,
                self.victims[victim] if victim else 0,
                nemesis,
                self.nemeses[nemesis] if nemesis else 0,
                self.score.combat,
                self.score.offense,
                self.score.defense,
                self.score.support,
                self.seconds_played,
            )

        return ",".join([
            '"' + (str(val).replace('"', '""') if val is not None else '') + '"'
             for val in values
        ])

    def to_dict(self):
        return dict(
            name=self.name,
            player_id=self.player_id,
            kills=self.kills,
            deaths=self.deaths,
            teamkills=self.teamkills,
            max_killstreak=self.killstreak,
            max_deathstreak=self.deathstreak,
            weapons_used={k.id: v for k, v in sorted(self.weapons.items(), key=lambda x: x[1], reverse=True)},
            weapons_died_to={k.id: v for k, v in sorted(self.causes.items(), key=lambda x: x[1], reverse=True)},
            victims={k: v for k, v in sorted(self.victims.items(), key=lambda x: x[1], reverse=True) if k != 'None'},
            nemeses={k: v for k, v in sorted(self.nemeses.items(), key=lambda x: x[1], reverse=True) if k != 'None'},
            combat_score=self.score.combat,
            offense_score=self.score.offense,
            defense_score=self.score.defense,
            support_score=self.score.support,
            num_matches_played=self.num_matches_played,
            seconds_played=self.seconds_played,
            seconds_alive=self.seconds_alive
        )


def _get_weapon_stats(stats: DataStore):
    def get_weapons_table(*mappings, skip_unmapped=False, title=None, show_tks=False):
        table: list[list[str | int]] = [["WEAPON", "KILLS", "RATE"]]
        weapons = stats.weapons_killed_with(*mappings, skip_unmapped=skip_unmapped)
        total_kills = sum(weapons.values())
        for weapon, kills in sorted(weapons.items(), reverse=True, key=lambda i: i[1]):
            table.append([weapon, kills, str(round(kills * 100 / (total_kills or 1), 2)) + "%"])
        if show_tks and stats.total_kills + stats.total_teamkills == stats.total_deaths:
            tks = stats.weapons_teamkilled_with(*mappings, skip_unmapped=skip_unmapped)
            table[0].append("TKS")
            for row in table[1:]:
                row.append(tks.get(str(row[0]), 0))
        return toTable(table, title=title)

    weaponsTable = get_weapons_table(mappings.VEHICLE_WEAPONS_FACTIONLESS, mappings.FACTIONLESS, show_tks=True)

    weaponsBasicAlliesTable = get_weapons_table(mappings.BASIC_CATEGORIES_ALLIES, skip_unmapped=True, title="WEAPONS USED BY ALLIES")
    weaponsBasicAxisTable = get_weapons_table(mappings.BASIC_CATEGORIES_AXIS, skip_unmapped=True, title="WEAPONS USED BY AXIS")

    table: list[list[str | int]] = [["WEAPON", "ALLIES", "AXIS", "TOTAL", "RATE"]]
    weapons_allies = stats.weapons_killed_with(mappings.BASIC_CATEGORIES_ALLIES, skip_unmapped=True)
    weapons_axis = stats.weapons_killed_with(mappings.BASIC_CATEGORIES_AXIS, skip_unmapped=True)
    weapons = combine_dicts(weapons_allies, weapons_axis)
    total_kills = sum(weapons.values())
    for weapon, kills in sorted(weapons.items(), reverse=True, key=lambda i: i[1]):
        allied_kills = weapons_allies.get(weapon, 0)
        axis_kills = weapons_axis.get(weapon, 0)
        table.append([weapon, allied_kills, axis_kills, kills, str(round(kills * 100 / (total_kills or 1), 2)) + "%"])
    weaponsBasicTable = toTable(table, title="FACTIONS SIDE TO SIDE")

    vehiclesTable = get_weapons_table(mappings.VEHICLE_CLASSES, skip_unmapped=True, title="VEHICLES USED")
    vehiclesAlliesTable = get_weapons_table(mappings.VEHICLES_ALLIES, skip_unmapped=True, title="ALLIED VEHICLES")
    vehiclesAxisTable = get_weapons_table(mappings.VEHICLES_AXIS, skip_unmapped=True, title="AXIS VEHICLES")

    return side_by_side(
        weaponsTable,
        "\n\n\n".join([weaponsBasicAlliesTable, weaponsBasicAxisTable, weaponsBasicTable]),
        "\n\n\n".join([vehiclesTable, vehiclesAlliesTable, vehiclesAxisTable]),
    spacing=18)

def create_scoreboard(data: Union['MatchData', 'MatchGroup']):
    if isinstance(data, MatchGroup):
        stats = data.stats
        output = [
            f"Matches played: {data.num_matches_played}",
        ]
    else:
        stats = data
        output = [
            f"Map: {stats.map or 'Unknown'}",
            f"Score: ALLIES ({stats.team1_score} - {stats.team2_score}) AXIS",
        ]

    output += [
        f"Duration: {int(stats.duration.total_seconds() / 60 + 0.5)} minutes",
        "",
        f"Players: {len(list(filter(lambda p: p.player_id, stats.players)))}",
        f"Deaths: {stats.total_deaths}",
        f"  Kills: {stats.total_kills}",
        f"  Teamkills: {stats.total_teamkills}",
        f"  Suicides: {stats.total_suicides}",
    ]

    total_allied_score = stats.total_allied_score
    total_axis_score = stats.total_axis_score
    table = [
        ['FACTION', 'KILLS', 'DEATHS', 'KDR', 'COMBAT', 'OFFENSE', 'DEFENSE', 'SUPPORT', 'ALIVE'],

        [   
            'Allies', stats.total_allied_kills, stats.total_allied_deaths, round(stats.total_allied_kills / (stats.total_allied_deaths or 1), 2),
            total_allied_score.combat, total_allied_score.offense, total_allied_score.defense, total_allied_score.support,
            f"{round(100 * stats.total_allied_time_alive / (stats.total_allied_time_played or stats.total_allied_time_alive), 1)}%"
        ],
        
        [
            'Axis', stats.total_axis_kills, stats.total_axis_deaths, round(stats.total_axis_kills / (stats.total_axis_deaths or 1), 2),
            total_axis_score.combat, total_axis_score.offense, total_axis_score.defense, total_axis_score.support,
            f"{round(100 * stats.total_axis_time_alive / (stats.total_axis_time_played or stats.total_axis_time_alive), 1)}%"
        ],
    ]

    output += [
        "",
        toTable(table),
        "",
        stats.to_text(),
        "",
        "",
        _get_weapon_stats(stats)
    ]

    return '\n'.join(output)
