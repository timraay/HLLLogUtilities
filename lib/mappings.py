from hllrcon.data import Map, GameMode, Layer, Weapon, WeaponType, Faction, Team

def get_map_and_mode(layer_name: str) -> tuple[str, str]:
    map, mode = layer_name.rsplit(' ', 1)
    map.replace(' NIGHT', '')

    map_name = MAPS_BY_NAME[map].pretty_name if map in MAPS_BY_NAME else map

    try:
        game_mode_name = GameMode.by_id(mode).id.capitalize()
    except ValueError:
        game_mode_name = mode.capitalize()

    return (
        map_name,
        game_mode_name
    )

MAPS_BY_NAME = { m.name: m for m in Map.all() }

def parse_layer(layer_name: str) -> Layer:
    return Layer.by_id(layer_name, strict=False)

ALLIED_FACTIONS = set([
    faction
    for faction in Faction.all()
    if faction.team is Team.ALLIES
])

AXIS_FACTIONS = set([
    faction
    for faction in Faction.all()
    if faction.team is Team.AXIS
])

BASIC_CATEGORIES_ALLIES = {
    weapon: weapon.type.value
    for weapon in Weapon.all()
    if weapon.factions.issubset(ALLIED_FACTIONS)
}

BASIC_CATEGORIES_AXIS = {
    weapon: weapon.type.value
    for weapon in Weapon.all()
    if weapon.factions.issubset(AXIS_FACTIONS)
}

BASIC_CATEGORIES_SHARED = {
    weapon: weapon.type.value
    for weapon in Weapon.all()
    if not weapon.factions.issubset(ALLIED_FACTIONS) and not weapon.factions.issubset(AXIS_FACTIONS)
}

BASIC_CATEGORIES = {
    **BASIC_CATEGORIES_ALLIES,
    **BASIC_CATEGORIES_AXIS,
    **BASIC_CATEGORIES_SHARED
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
    WeaponType.FLARE_GUN: "Flare Gun",
}

VEHICLES: dict[Weapon, str] = {}
VEHICLES_ALLIES: dict[Weapon, str] = {}
VEHICLES_AXIS: dict[Weapon, str] = {}
VEHICLE_WEAPONS: dict[Weapon, str] = {}
VEHICLE_WEAPONS_FACTIONLESS: dict[Weapon, str] = {}
VEHICLE_CLASSES: dict[Weapon, str] = {}
for weapon in Weapon.all():
    vehicle = weapon.vehicle
    if not vehicle:
        continue

    for faction in Faction.all():
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

FACTIONLESS: dict[Weapon, str] = {}
for weapon in Weapon.all():
    if weapon not in _NORMALIZED_CATEGORIES:
        continue

    weapon_name = _NORMALIZED_CATEGORIES[weapon.type]
    FACTIONLESS[weapon] = weapon_name
    
