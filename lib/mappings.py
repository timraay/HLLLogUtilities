import contextlib
import itertools

from hllrcon import (
    AnyLayer,
    AnyWeapon,
    HLLFaction,
    HLLGameMode,
    HLLLayer,
    HLLMap,
    HLLVFaction,
    HLLVGameMode,
    HLLVLayer,
    HLLVMap,
    HLLVWeapon,
    HLLWeapon,
    WeaponType,
)

from lib.games import Game


def get_map_and_mode(layer_name: str) -> tuple[str, str]:
    if " " in layer_name:
        map, mode = layer_name.rsplit(" ", 1)
        map.replace(" NIGHT", "")
    else:
        map, mode = layer_name, "Warfare"

    map_name = MAPS_BY_NAME[map].pretty_name if map in MAPS_BY_NAME else map

    game_mode = None
    with contextlib.suppress(ValueError):
        game_mode = HLLGameMode.by_id(mode)
    with contextlib.suppress(ValueError):
        game_mode = HLLVGameMode.by_id(mode)

    if game_mode:
        game_mode_name = game_mode.id.capitalize()
    else:
        game_mode_name = mode.capitalize()

    return (map_name, game_mode_name)


MAPS_BY_NAME = {m.name: m for m in itertools.chain(HLLVMap.all(), HLLMap.all())}


def parse_layer(layer_name: str, game: Game | None = None) -> AnyLayer:
    if game == Game.HLL:
        return HLLLayer.by_id(layer_name, strict=False)
    elif game == Game.HLLV:
        return HLLVLayer.by_id(layer_name, strict=False)

    with contextlib.suppress(ValueError):
        return HLLLayer.by_id(layer_name)
    with contextlib.suppress(ValueError):
        return HLLVLayer.by_id(layer_name)

    return HLLLayer.by_id(layer_name, strict=False)


ALLIED_FACTIONS = {
    faction
    for faction in itertools.chain(HLLVFaction.all(), HLLFaction.all())
    if faction.is_allied
}

AXIS_FACTIONS = {
    faction
    for faction in itertools.chain(HLLVFaction.all(), HLLFaction.all())
    if faction.is_axis
}


BASIC_CATEGORIES_ALLIES = {
    weapon: weapon.type.value
    for weapon in itertools.chain(HLLVWeapon.all(), HLLWeapon.all())
    if weapon.factions.issubset(ALLIED_FACTIONS)
}

BASIC_CATEGORIES_AXIS = {
    weapon: weapon.type.value
    for weapon in itertools.chain(HLLVWeapon.all(), HLLWeapon.all())
    if weapon.factions.issubset(AXIS_FACTIONS)
}

BASIC_CATEGORIES_SHARED = {
    weapon: weapon.type.value
    for weapon in itertools.chain(HLLVWeapon.all(), HLLWeapon.all())
    if not weapon.factions.issubset(ALLIED_FACTIONS)
    and not weapon.factions.issubset(AXIS_FACTIONS)
}

BASIC_CATEGORIES = {
    **BASIC_CATEGORIES_ALLIES,
    **BASIC_CATEGORIES_AXIS,
    **BASIC_CATEGORIES_SHARED,
}

_NORMALIZED_CATEGORIES = {
    WeaponType.TANK_CANNON: "Tank Cannon",
    WeaponType.TANK_COAXIAL_MG: "Tank Coaxial MG",
    WeaponType.TANK_HULL_MG: "Tank Hull MG",
    WeaponType.AT_GUN: "AT Gun",
    WeaponType.MOUNTED_MG: "Mounted MG",
    WeaponType.ROADKILL: "Roadkill",
    WeaponType.ARTILLERY: "Artillery",
    WeaponType.AT_MINE: "AT Mine",
    WeaponType.AP_MINE: "AP Mine",
    WeaponType.FLAMETHROWER: "Flamethrower",
    WeaponType.RECON_FLARE: "Flare Gun",
}

VEHICLES: dict[AnyWeapon, str] = {}
VEHICLES_ALLIES: dict[AnyWeapon, str] = {}
VEHICLES_AXIS: dict[AnyWeapon, str] = {}
VEHICLE_WEAPONS: dict[AnyWeapon, str] = {}
VEHICLE_WEAPONS_FACTIONLESS: dict[AnyWeapon, str] = {}
VEHICLE_CLASSES: dict[AnyWeapon, str] = {}
for weapon in itertools.chain(HLLVWeapon.all(), HLLWeapon.all()):
    vehicle = weapon.vehicle
    if not vehicle:
        continue

    for faction in itertools.chain(HLLVFaction.all(), HLLFaction.all()):
        if faction in weapon.factions:
            break
    else:
        continue

    weapon_name = _NORMALIZED_CATEGORIES.get(weapon.type, weapon.name)

    VEHICLES[weapon] = vehicle.name
    if weapon in BASIC_CATEGORIES_ALLIES:
        VEHICLES_ALLIES[weapon] = vehicle.name
    if weapon in BASIC_CATEGORIES_AXIS:
        VEHICLES_AXIS[weapon] = vehicle.name

    VEHICLE_WEAPONS[weapon] = f"{faction.short_name} {weapon_name}"
    VEHICLE_WEAPONS_FACTIONLESS[weapon] = weapon_name

    VEHICLE_CLASSES[weapon] = vehicle.type.value

FACTIONLESS: dict[AnyWeapon, str] = {}
for weapon in itertools.chain(HLLVWeapon.all(), HLLWeapon.all()):
    if weapon not in _NORMALIZED_CATEGORIES:
        continue

    weapon_name = _NORMALIZED_CATEGORIES[weapon.type]
    FACTIONLESS[weapon] = weapon_name
