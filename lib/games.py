from enum import StrEnum
from typing import TypeVar, assert_never


class Game(StrEnum):
    HLL = "Hell Let Loose"
    HLLV = "Hell Let Loose: Vietnam"


T = TypeVar("T")


def game_switch(game: Game, hll_value: T, hllv_value: T) -> T:
    match game:
        case Game.HLL:
            return hll_value
        case Game.HLLV:
            return hllv_value
        case _:
            assert_never(game)
