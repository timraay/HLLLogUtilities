from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self, Sequence
from pypika import Query, Column

if TYPE_CHECKING:
    from lib.rcon.models import EventModel, EventTypes, Player, Squad, Team

class LogLine(BaseModel):
    event_time: datetime
    event_type: str
    player_name: str | None = None
    player_steamid: str | None = None
    player_team: str | None = None
    player_role: str | None = None
    player_combat_score: int | None = None
    player_offense_score: int | None = None
    player_defense_score: int | None = None
    player_support_score: int | None = None
    player2_name: str | None = None
    player2_steamid: str | None = None
    player2_team: str | None = None
    player2_role: str | None = None
    weapon: str | None = None
    old: str | None = None
    new: str | None = None
    team_name: str | None = None
    squad_name: str | None = None
    message: str | None = None

    @field_validator('player_team', 'player2_team', 'team_name')
    def validate_team(cls, v):
        if v is not None and v not in {'Allies', 'Axis'}:
            raise ValueError("%s is not a valid team name" % v)
        return v
    
    @staticmethod
    def _get_create_query(table_name: str, _explicit_fields: Sequence[str] | None = None):
        if _explicit_fields:
            field_names = list(_explicit_fields)
        else:
            field_names = list(LogLine.model_fields.keys())

        # I really need to look into a better way to do this at some point
        exceptions = dict(
            player_combat_score='INTEGER',
            player_offense_score='INTEGER',
            player_defense_score='INTEGER',
            player_support_score='INTEGER',
        )
        query = Query.create_table(table_name).columns(*[
            Column(field_name, exceptions.get(field_name, 'TEXT')) for field_name in field_names
        ])
        return str(query)


class LogLineBuilder:
    def __init__(self, event_time: datetime, event_type: 'EventTypes') -> None:
        self.payload: dict[str, Any] = {
            'event_time': event_time,
            'event_type': event_type.name,
        }
    
    @classmethod
    def from_event(cls, event: 'EventModel'):
        return cls(
            event_time=event.event_time,
            event_type=event.get_type()
        )

    def set_player(self, player: 'Player | None', *, include_score: bool = False) -> Self:
        if player:
            self.payload.update({
                'player_name': player.name,
                'player_steamid': player.id,
                'player_role': player.name,
            })
            if team := player.get_team():
                self.payload['player_team'] = team.name
            if include_score:
                self.payload.update({
                    'player_combat_score': player.score.combat,
                    'player_offense_score': player.score.offense,
                    'player_defense_score': player.score.defense,
                    'player_support_score': player.score.support,
                })
        else:
            self.payload.update({
                'player_name': None,
                'player_steamid': None,
                'player_role': None,
                'player_team': None,
                'player_combat_score': None,
                'player_offense_score': None,
                'player_defense_score': None,
                'player_support_score': None,
            })
        return self
    
    def set_player2(self, player: 'Player | None') -> Self:
        if player:
            self.payload.update({
                'player2_name': player.name,
                'player2_steamid': player.id,
                'player2_role': player.name,
            })
            if team := player.get_team():
                self.payload['player2_team'] = team.name
        else:
            self.payload.update({
                'player2_name': None,
                'player2_steamid': None,
                'player2_role': None,
                'player2_team': None,
            })
        return self

    def set_team(self, team: 'Team | None') -> Self:
        self.payload['team_name'] = team.name if team else None
        return self
    
    def set_squad(self, squad: 'Squad | None') -> Self:
        if squad:
            self.payload['squad_name'] = squad.name if squad else None
            self.set_team(squad.get_team())
        else:
            self.payload['squad_name'] = None
            self.payload['team_name'] = None
        return self

    def set_weapon(self, weapon: str | None) -> Self:
        self.payload['weapon'] = weapon
        return self

    def set_message(self, message: str | None) -> Self:
        self.payload['message'] = message
        return self

    def set_old_and_new(self, old: str | None, new: str | None) -> Self:
        self.payload['old'] = old
        self.payload['new'] = new
        return self

    def to_log_line(self) -> LogLine:
        return LogLine(**self.payload)
