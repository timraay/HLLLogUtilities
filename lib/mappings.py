import re
from enum import Enum

MAP_NAMES = {
    "SAINTE-MÈRE-ÉGLISE": "SME",
    "ST MARIE DU MONT": "SMDM",
    "UTAH BEACH": "Utah",
    "PURPLE HEART LANE": "PHL",
    "CARENTAN": "Carentan",
    "HÜRTGEN FOREST": "Hurtgen",
    "HILL 400": "Hill 400",
    "FOY": "Foy",
    "KURSK": "Kursk",
    "STALINGRAD": "Stalingrad",
    "REMAGEN": "Remagen",
    "Kharkov": "Kharkov"
}

LONG_MAP_NAMES = {
    "SAINTE-MÈRE-ÉGLISE": "Sainte-Mère-Église",
    "ST MARIE DU MONT": "St. Marie Du Mont",
    "UTAH BEACH": "Utah Beach",
    "PURPLE HEART LANE": "Purple Heart Lane",
    "CARENTAN": "Carentan",
    "HÜRTGEN FOREST": "Hürtgen Forest",
    "HILL 400": "Hill 400",
    "FOY": "Foy",
    "KURSK": "Kursk",
    "STALINGRAD": "Stalingrad",
    "REMAGEN": "Remagen",
    "KHARKOV": "Kharkov"
}

LONG_MAP_NAMES_BY_ID = {
    "stmereeglise": "Sainte-Mère-Église",
    "stmariedumont": "St. Marie Du Mont",
    "utahbeach": "Utah Beach",
    "purpleheartlane": "Purple Heart Lane",
    "carentan": "Carentan",
    "hurtgenforest": "Hürtgen Forest",
    "hill400": "Hill 400",
    "foy": "Foy",
    "kursk": "Kursk",
    "stalingrad": "Stalingrad",
    "remagen": "Remagen",
    "kharkov": "Kharkov"
}

GAMEMODE_NAMES = {
    "WARFARE": "Warfare",
    "OFFENSIVE": "Offensive"
}

class Gamemode(Enum):
    warfare = "warfare"
    offensive = "offensive"

class Map:
    def __init__(self, name: str, gamemode: Gamemode, attackers: str = None, night: bool = False, v2: bool = False, short: bool = False):
        self.name = str(name)
        self.gamemode = Gamemode(gamemode)
        self._attackers = str(attackers)
        self.night = bool(night)
        self.v2 = bool(v2)
        self.short = bool(short)
    
    @property
    def attackers(self):
        return self._attackers.lower()

    @classmethod
    def load(cls, map: str):
        if "_warfare" in map:
            name, rest = map.split('_warfare', 1)
            return cls(
                name=name,
                gamemode=Gamemode.warfare,
                night="_night" in rest,
                v2="V2" in rest
            )
        elif "_offensive_" in map:
            name, attackers = map.split('_offensive_')
            return cls(
                name=name,
                gamemode=Gamemode.offensive,
                attackers=attackers
            )
        elif "_off_" in map:
            name, attackers = map.split('_off_')
            return cls(
                name=name,
                gamemode=Gamemode.offensive,
                attackers=attackers,
                short=True
            )
        else:
            raise ValueError('Unknown map %s' % map)

    def pretty(self):
        out = LONG_MAP_NAMES_BY_ID.get(self.name, self.name.capitalize())
        if self.gamemode == Gamemode.warfare:
            out += " Warfare"
        elif self.gamemode == Gamemode.offensive:
            out += f" Off. {self.attackers.upper()}"
        if self.night:
            out += " (Night)"
        return out

    def __str__(self):
        if self.gamemode == Gamemode.warfare:
            out = f"{self.name}_warfare"
            if self.v2:
                out += "_V2"
            if self.night:
                out += "_night"
            return out
        elif self.gamemode == Gamemode.offensive:
            if self.short:
                return f"{self.name}_off_{self._attackers}"
            else:
                return f"{self.name}_offensive_{self._attackers}"
        raise ValueError("Map string could not be compiled")
    
    def __repr__(self) -> str:
        return str(self)
    
    def __hash__(self) -> int:
        return hash(self.__str__())
    
    def __eq__(self, other):
        return str(self) == str(other)


def get_map_and_mode(layer_name: str):
    map, mode = layer_name.rsplit(' ', 1)
    return LONG_MAP_NAMES.get(map, map), GAMEMODE_NAMES.get(mode, mode)

SQUAD_LEADER_ROLES = {"Officer", "TankCommander", "Spotter"}
TEAM_LEADER_ROLES = {"ArmyCommander"}

INFANTRY_ROLES = {"Officer", "Assault", "AutomaticRifleman", "Medic", "Support",
                  "HeavyMachineGunner", "AntiTank", "Engineer", "Rifleman"}
TANK_ROLES = {"TankCommander", "Crewman"}
RECON_ROLES = {"Spotter", "Sniper"}

WEAPONS = {
    "Garand": "M1 Garand",
    "G43": "G43",
    "STG44": "STG44",
    "MP40": "MP40",
    "MG42": "MG42",
    "Thompson": "M1A1 Thompson",
    "M1918A2_BAR": "M1918A2 BAR",
    "Kar98": "Kar98k",
    "M1919": "M1919 Browning",
    "Kar98_Sniper": "Kar98k (8x)",
    "M1903": "M1903 Springfield (4x)",
    "M1_Carbine": "M1 Carbine",
    "MK2_Grenade": "US Grenade",
    "M43": "GER Grenade",
    "Rifle_SVT40": "SVT40",
    "SMG_PPSH41": "PPSh-41",
    "SMG_M3_GreaseGun": "M3 Grease Gun",
    "Rifle_Mosin_M9130": "Mosin Nagant M1930",
    "Satchel_3KG": "US Satchel Charge",
    "Bazooka": "Bazooka",
    "MG34": "MG34",
    "LMG_DP27": "DP-27",
    "P38": "Walther P38",
    "Rifle_SVT40_Sniper": "SVT40 (4x)",
    "Panzershreck": "Panzershreck",
    "Rifle_Mosin_M38": "Mosin Nagant M38",
    "M1911": "Colt M1911",
    "Satchel_M37": "GER Satchel Charge",
    "M2": "US AP Mine",
    "SMine": "GER AP Mine",
    "Luger": "Luger P08",
    "Grenade_Frag_RDG42": "RUS Grenade",
    "M1A1": "US AT Mine",
    "Tellermine43": "GER AT Mine",
    "Rifle_Mosin_M1891": "Mosin Nagant M1891",
    "Spade_GER": "GER Melee",
    "Knife_US": "US Melee",
    "Mine_POMZ": "RUS AP Mine",
    "M24_Grenade": "GER Grenade",
    "Mine_TM35": "RUS AT Mine",
    "TokarevTT33": "Tokarev TT33",
    "Pistol_M1895": "Nagant M1895",
    "ATRifle_PTRS41": "PTRS-41",
    "TrenchGun": "M97 Trench Gun",
    "None": "Artillery",

    "M1 GARAND": "M1 Garand",
    "M1 CARBINE": "M1 Carbine",
    "M1A1 THOMPSON": "M1A1 Thompson",
    "M3 GREASE GUN": "M3 Grease Gun",
    "M1918A2 BAR": "M1918A2 BAR",
    "BROWNING M1919": "M1919 Browning",
    "M1903 SPRINGFIELD": "M1903 Springfield (4x)",
    "M97 TRENCH GUN": "M97 Trench Gun",
    "COLT M1911": "Colt M1911",
    "M3 KNIFE": "US Melee",
    "SATCHEL": "Satchel Charge",
    "MK2 GRENADE": "US Grenade",
    "M2 FLAMETHROWER": "US Flamethrower",
    "BAZOOKA": "Bazooka",
    "M2 AP MINE": "US AP Mine",
    "M1A1 AT MINE": "US AT Mine",
    "57MM CANNON [M1 57mm]": "US AT Gun",
    "155MM HOWITZER [M114]": "US Artillery",
    "M8 Greyhound": "US Roadkill [M8 Greyhound]",
    "Stuart M5A1": "US Roadkill [Stuart M5A1]",
    "Sherman M4A1": "US Roadkill [Sherman M4]",
    "Sherman M4A3(75)W": "US Roadkill [Sherman M4A3 75w]",
    "Sherman M4A3E2": "US Roadkill [Sherman 75mm]",
    "Sherman M4A3E2(76)": "US Roadkill [Sherman 76mm]",
    "GMC CCKW 353 (Supply)": "US Roadkill [US Supply Truck]",
    "GMC CCKW 353 (Transport)": "US Roadkill [US Transport Truck]",
    "M3 Half-track": "US Roadkill [US Half-track]",
    "Jeep Willys": "US Roadkill [US Jeep]",
    "M6 37mm [M8 Greyhound]": "US Tank Cannon [M8 Greyhound]",
    "COAXIAL M1919 [M8 Greyhound]": "US Tank Coaxial [M8 Greyhound]",
    "37MM CANNON [Stuart M5A1]": "US Tank Cannon [Stuart M5A1]",
    "COAXIAL M1919 [Stuart M5A1]": "US Tank Coaxial [Stuart M5A1]",
    "HULL M1919 [Stuart M5A1]": "US Tank Hull MG [Stuart M5A1]",
    "75MM CANNON [Sherman M4A1]": "US Tank Cannon [Sherman M4]",
    "COAXIAL M1919 [Sherman M4A1]": "US Tank Coaxial [Sherman M4]",
    "HULL M1919 [Sherman M4A1]": "US Tank Hull MG [Sherman M4]",
    "75MM CANNON [Sherman M4A3(75)W]": "US Tank Cannon [Sherman M4A3 75w]",
    "COAXIAL M1919 [Sherman M4A3(75)W]": "US Tank Coaxial [Sherman M4A3 75w]",
    "HULL M1919 [Sherman M4A3(75)W]": "US Tank Hull MG [Sherman M4A3 75w]",
    "75MM M3 GUN [Sherman M4A3E2]": "US Tank Cannon [Sherman 75mm]",
    "COAXIAL M1919 [Sherman M4A3E2]": "US Tank Coaxial [Sherman 75mm]",
    "HULL M1919 [Sherman M4A3E2]": "US Tank Hull MG [Sherman 75mm]",
    "76MM M1 GUN [Sherman M4A3E2(76)]": "US Tank Cannon [Sherman 76mm]",
    "COAXIAL M1919 [Sherman M4A3E2(76)]": "US Tank Coaxial [Sherman 76mm]",
    "HULL M1919 [Sherman M4A3E2(76)]": "US Tank Hull MG [Sherman 76mm]",
    "M2 Browning [M3 Half-track]": "US Half-track MG [US Half-track]",
    "KARABINER 98K": "Kar98k",
    "GEWEHR 43": "G43",
    "STG44": "STG44",
    "FG42": "FG42",
    "MP40": "MP40",
    "MG34": "MG34",
    "MG42": "MG42",
    "FLAMMENWERFER 41": "GER Flamethrower",
    "KARABINER 98K x8": "Kar98k (8x)",
    "FG42 x4": "FG42 (4x)",
    "LUGER P08": "Luger P08",
    "WALTHER P38": "Walther P38",
    "FELDSPATEN": "GER Melee",
    "M24 STIELHANDGRANATE": "GER Grenade",
    "M43 STIELHANDGRANATE": "GER Grenade",
    "PANZERSCHRECK": "Panzerschreck",
    "S-MINE": "GER AP Mine",
    "TELLERMINE 43": "GER AT Mine",
    "75MM CANNON [PAK 40]": "GER AT Gun",
    "150MM HOWITZER [sFH 18]": "GER Artillery",
    "Sd.Kfz.234 Puma": "GER Roadkill [Puma]",
    "Sd.Kfz.121 Luchs": "GER Roadkill [Luchs]",
    "Sd.Kfz.161 Panzer IV": "GER Roadkill [Panzer IV]",
    "Sd.Kfz.171 Panther": "GER Roadkill [Panther]",
    "Sd.Kfz.181 Tiger 1": "GER Roadkill [Tiger 1]",
    "Opel Blitz (Supply)": "GER Roadkill [GER Supply Truck]",
    "Opel Blitz (Transport)": "GER Roadkill [GER Transport Truck]",
    "Sd.Kfz 251 Half-track": "GER Roadkill [GER Half-track]",
    "Kubelwagen": "GER Roadkill [GER Jeep]",
    "50mm KwK 39/1 [Sd.Kfz.234 Puma]": "GER Tank Cannon [Puma]",
    "COAXIAL MG34 [Sd.Kfz.234 Puma]": "GER Tank Coaxial [Puma]",
    "20MM KWK 30 [Sd.Kfz.121 Luchs]": "GER Tank Cannon [Luchs]",
    "COAXIAL MG34 [Sd.Kfz.121 Luchs]": "GER Tank Coaxial [Luchs]",
    "75MM CANNON [Sd.Kfz.161 Panzer IV]": "GER Tank Cannon [Panzer IV]",
    "COAXIAL MG34 [Sd.Kfz.161 Panzer IV]": "GER Tank Coaxial [Panzer IV]",
    "HULL MG34 [Sd.Kfz.161 Panzer IV]": "GER Tank Hull MG [Panzer IV]",
    "75MM CANNON [Sd.Kfz.171 Panther]": "GER Tank Cannon [Panther]",
    "COAXIAL MG34 [Sd.Kfz.171 Panther]": "GER Tank Coaxial [Panther]",
    "HULL MG34 [Sd.Kfz.171 Panther]": "GER Tank Hull MG [Panther]",
    "88 KWK 36 L/56 [Sd.Kfz.181 Tiger 1]": "GER Tank Cannon [Tiger 1]",
    "COAXIAL MG34 [Sd.Kfz.181 Tiger 1]": "GER Tank Coaxial [Tiger 1]",
    "HULL MG34 [Sd.Kfz.181 Tiger 1]": "GER Tank Hull MG [Tiger 1]",
    "MG 42 [Sd.Kfz 251 Half-track]": "GER Half-track MG [GER Half-track]",
    "MOSIN NAGANT 1891": "Mosin-Nagant 1891",
    "MOSIN NAGANT 91/30": "Mosin-Nagant 91/30",
    "MOSIN NAGANT M38": "Mosin-Nagant M38",
    "SVT40": "SVT40",
    "PPSH 41": "PPSh-41",
    "PPSH 41 W/DRUM": "PPSh-41 Drum",
    "DP-27": "DP-27",
    "SCOPED MOSIN NAGANT 91/30": "Mosin-Nagant 91/30 (4x)",
    "SCOPED SVT40": "SVT40 (4x)",
    "NAGANT M1895": "Nagant M1895",
    "TOKAREV TT33": "Tokarev TT33",
    "MPL-50 SPADE": "RUS Melee",
    "SATCHEL CHARGE": "Satchel Charge",
    "RG-42 GRENADE": "RUS Grenade",
    "MOLOTOV": "Molotov",
    "PTRS-41": "PTRS-41",
    "POMZ AP MINE": "RUS AP Mine",
    "TM-35 AT MINE": "RUS AT Mine",
    "57MM CANNON [ZiS-2]": "RUS AT Gun",
    "122MM HOWITZER [M1938 (M-30)]": "RUS Artillery",
    "BA-10": "RUS Roadkill [BA-10]",
    "T70": "RUS Roadkill [T70]",
    "T34/76": "RUS Roadkill [T34/76]",
    "IS-1": "RUS Roadkill [IS-1]",
    "ZIS-5 (Supply)": "RUS Roadkill [RUS Supply Truck]",
    "ZIS-5 (Transport)": "RUS Roadkill [RUS Transport Truck]",
    "M3 Half-track": "RUS Roadkill [RUS Half-track]",
    "GAZ-67": "RUS Roadkill [RUS Jeep]",
    "19-K 45MM [BA-10]": "RUS Tank Cannon [BA-10]",
    "COAXIAL DT [BA-10]": "RUS Tank Coaxial [BA-10]",
    "45MM M1937 [T70]": "RUS Tank Cannon [T70]",
    "COAXIAL DT [T70]": "RUS Tank Coaxial [T70]",
    "76MM ZiS-5 [T34/76]": "RUS Tank Cannon [T34/76]",
    "COAXIAL DT [T34/76]": "RUS Tank Coaxial [T34/76]",
    "HULL DT [T34/76]": "RUS Tank Hull MG [T34/76]",
    "D-5T 85MM [IS-1]": "RUS Tank Cannon [IS-1]",
    "COAXIAL DT [IS-1]": "RUS Tank Coaxial [IS-1]",
    "HULL DT [IS-1]": "RUS Tank Hull MG [IS-1]",
    # "M2 Browning [M3 Half-track]": "RUS Half-track MG [RUS Halftrack]",
    "UNKNOWN": "Unknown",
    "BOMBING RUN": "Bombing Run",
    "STRAFING RUN": "Strafing Run",
    "PRECISION STRIKE": "Precision Strike",
    "Unknown": "Katyusha Barrage",
    "FLARE GUN": "Flare Gun"
}

BASIC_CATEGORIES_ALLIES = {value: cat for cat, values in {
    "Submachine Gun": [ "M1A1 Thompson", "M3 Grease Gun", "PPSh-41", "PPSh-41 Drum" ],
    "Semi-Auto Rifle": [ "M1 Garand", "M1 Carbine", "SVT40" ],
    "Bolt-Action Rifle": [ "Mosin-Nagant 1891", "Mosin-Nagant 91/30", "Mosin-Nagant M38" ],
    "Assault Rifle": [ "M1918A2 BAR", "M97 Trench Gun" ],
    "Sniper Rifle": [ "M1903 Springfield (4x)", "Mosin-Nagant 91/30 (4x)", "SVT40 (4x)" ],
    "Machine Gun": [ "M1919 Browning", "DP-27" ],
    "Pistol": [ "Colt M1911", "Nagant M1895", "Tokarev TT33" ],
    "Melee": ["US Melee", "RUS Melee"],
    "Flamethrower": [ "US Flamethrower" ],
    "Artillery": ["US Artillery", "RUS Artillery"],
    "Vehicle": [
        "US Roadkill [M8 Greyhound]",
        "US Roadkill [Stuart M5A1]",
        "US Roadkill [Sherman M4]",
        "US Roadkill [Sherman M4A3 75w]",
        "US Roadkill [Sherman 75mm]",
        "US Roadkill [Sherman 76mm]",
        "US Roadkill [US Supply Truck]",
        "US Roadkill [US Transport Truck]",
        "US Roadkill [US Half-track]",
        "US Roadkill [US Jeep]",
        "US Tank Cannon [M8 Greyhound]",
        "US Tank Coaxial [M8 Greyhound]",
        "US Tank Cannon [Stuart M5A1]",
        "US Tank Coaxial [Stuart M5A1]",
        "US Tank Hull MG [Stuart M5A1]",
        "US Tank Cannon [Sherman M4]",
        "US Tank Coaxial [Sherman M4]",
        "US Tank Hull MG [Sherman M4]",
        "US Tank Cannon [Sherman 75mm]",
        "US Tank Coaxial [Sherman 75mm]",
        "US Tank Hull MG [Sherman 75mm]",
        "US Tank Cannon [Sherman 76mm]",
        "US Tank Coaxial [Sherman 76mm]",
        "US Tank Hull MG [Sherman 76mm]",
        "US Half-track MG [US Half-track]",
        "RUS Roadkill [BA-10]",
        "RUS Roadkill [T70]",
        "RUS Roadkill [T34/76]",
        "RUS Roadkill [IS-1]",
        "RUS Roadkill [RUS Supply Truck]",
        "RUS Roadkill [RUS Transport Truck]",
        "RUS Roadkill [RUS Half-track]",
        "RUS Roadkill [RUS Jeep]",
        "RUS Tank Cannon [BA-10]",
        "RUS Tank Coaxial [BA-10]",
        "RUS Tank Cannon [T70]",
        "RUS Tank Coaxial [T70]",
        "RUS Tank Cannon [T34/76]",
        "RUS Tank Coaxial [T34/76]",
        "RUS Tank Hull MG [T34/76]",
        "RUS Tank Cannon [IS-1]",
        "RUS Tank Coaxial [IS-1]",
        "RUS Tank Hull MG [IS-1]",
        "RUS Half-track MG [RUS Half-track]",
    ],
    "Grenade": [
        "US Grenade", "RUS Grenade",
        "US AP Mine", "RUS AP Mine",
        "Molotov"
    ],
    "Anti-Tank": [
        "US AT Gun", "RUS AT Gun",
        "US AT Mine", "RUS AT Mine",
        "Bazooka", "PTRS-41",
    ],
}.items() for value in values}

BASIC_CATEGORIES_AXIS = {value: cat for cat, values in {
    "Submachine Gun": [ "MP40" ],
    "Semi-Auto Rifle": [ "G43" ],
    "Bolt-Action Rifle": [ "Kar98k" ],
    "Assault Rifle": [ "STG44", "FG42" ],
    "Sniper Rifle": [ "Kar98k (8x)", "FG42 (4x)" ],
    "Machine Gun": [ "MG34", "MG42" ],
    "Pistol": [ "Luger P08", "Walther P38" ],
    "Flamethrower": [ "GER Flamethrower" ],
    "Melee": [ "GER Melee" ],
    "Artillery": [ "GER Artillery" ],
    "Vehicle": [
        "GER Roadkill [Puma]",
        "GER Roadkill [Luchs]",
        "GER Roadkill [Panzer IV]",
        "GER Roadkill [Panther]",
        "GER Roadkill [Tiger 1]",
        "GER Roadkill [GER Supply Truck]",
        "GER Roadkill [GER Transport Truck]",
        "GER Roadkill [GER Half-track]",
        "GER Roadkill [GER Jeep]",
        "GER Tank Cannon [Puma]",
        "GER Tank Coaxial [Puma]",
        "GER Tank Cannon [Luchs]",
        "GER Tank Coaxial [Luchs]",
        "GER Tank Cannon [Panzer IV]",
        "GER Tank Coaxial [Panzer IV]",
        "GER Tank Hull MG [Panzer IV]",
        "GER Tank Cannon [Panther]",
        "GER Tank Coaxial [Panther]",
        "GER Tank Hull MG [Panther]",
        "GER Tank Cannon [Tiger 1]",
        "GER Tank Coaxial [Tiger 1]",
        "GER Tank Hull MG [Tiger 1]",
        "GER Half-track MG [GER Half-track]",
    ],
    "Grenade": [ "GER Grenade", "GER AP Mine" ],
    "Anti-Tank": [ "GER AT Gun", "GER AT Mine", "Panzerschreck" ],
}.items() for value in values}

BASIC_CATEGORIES = {**BASIC_CATEGORIES_ALLIES, **BASIC_CATEGORIES_AXIS}

_VEHICLE_CLASSES = {vehicle: _class for _class, vehicles in {
    "Jeep": ["US Jeep", "GER Jeep", "RUS Jeep"],
    "Half-track": ["US Half-track", "GER Half-track", "RUS Half-track"],
    "Recon Vehicle": [ "M8 Greyhound", "Puma", "BA-10" ],
    "Light Tank": [ "Stuart M5A1", "Luchs", "T70" ],
    "Medium Tank": [ "Sherman M4", "Sherman M4A3 75w", "Panzer IV", "T34/76" ],
    "Heavy Tank": [ "Sherman 75mm", "Sherman 76mm", "Panther", "Tiger 1", "IS-1" ]
}.items() for vehicle in vehicles}

VEHICLES = dict()
VEHICLES_ALLIES = dict()
VEHICLES_AXIS = dict()
VEHICLE_WEAPONS = dict()
VEHICLE_WEAPONS_FACTIONLESS = dict()
VEHICLE_CLASSES = dict()
for weapon in WEAPONS.values():
    match = re.match(r"((US|GER|RUS) (.+)) \[(.+)\]$", weapon)
    if match:
        vic_weapon, vic_faction, vic_weapon_factionless, vic_name = match.groups()
        
        VEHICLES[weapon] = vic_name
        if weapon in BASIC_CATEGORIES_ALLIES:
            VEHICLES_ALLIES[weapon] = vic_name
        if weapon in BASIC_CATEGORIES_AXIS:
            VEHICLES_AXIS[weapon] = vic_name

        VEHICLE_WEAPONS[weapon] = vic_weapon
        VEHICLE_WEAPONS_FACTIONLESS[weapon] = vic_weapon_factionless

        if vic_name in _VEHICLE_CLASSES:
            VEHICLE_CLASSES[weapon] = _VEHICLE_CLASSES[vic_name]

FACTIONLESS = dict()
for weapon in WEAPONS.values():
    match = re.match(r"(US|GER|RUS) (.+)$", weapon)
    if match:
        FACTIONLESS[weapon] = match.group(2)


GER_LOCALIZED = {
    "ANTIPERSONENMINE POMZ": "POMZ AP MINE",
    "DT (RUMPF) [T34/76]": "HULL DT [T34/76]",
    "SPRENGLADUNG": "SATCHEL CHARGE",
    "RG-42 GRANATE": "RG-42 GRENADE",
    "Sd.Kfz. 121 Luchs": "Sd.Kfz.121 Luchs",
    "MOSIN-NAGANT 91/30": "MOSIN NAGANT 91/30",
    "76 MM ZiS-5 [T34/76]": "76MM ZiS-5 [T34/76]",
    "122-MM-HAUBITZE [M1938 (M-30)]": "122MM HOWITZER [M1938 (M-30)]",
    "MG34 (KOAXIAL) [Sd.Kfz. 234 Puma]": "COAXIAL MG34 [Sd.Kfz.234 Puma]",
    "75-MM-GESCHÜTZ [Sd.Kfz. 171 Panther]": "75MM CANNON [Sd.Kfz.171 Panther]",
    "Sd.Kfz. 234 Puma": "Sd.Kfz.234 Puma",
    "SVT40 (ZIELF.)": "SCOPED SVT40",
    "TIEFFLIEGERANGRIFF": "STRAFING RUN",
    "DT (KOAXIAL) [T34/76]": "COAXIAL DT [T34/76]",
    "MOSIN-NAGANT 91/30 (ZIELF.)": "SCOPED MOSIN NAGANT 91/30",
    "ZIS-5 (Nachschub)": "ZIS-5 (Supply)",
    "DT (RUMPF) [IS-1]": "HULL DT [T34/76]",
    "MOSIN-NAGANT M38": "MOSIN NAGANT M38",
    "19-K 45 MM [BA-10]": "19-K 45MM [BA-10]",
    "KWK 30 (20 MM) [Sd.Kfz. 121 Luchs]": "20MM KWK 30 [Sd.Kfz.121 Luchs]",
    "ZIS-5 (Transporter)": "ZIS-5 (Transport)",
    "75-MM-GESCHÜTZ [PAK 40]": "75MM CANNON [PAK 40]",
    "75-MM-GESCHÜTZ [Sd.Kfz. 161 Panzer IV]": "75MM CANNON [Sd.Kfz.161 Panzer IV]",
    "MOSIN-NAGANT 1891": "MOSIN NAGANT 1891",
    "MG34 (RUMPF) [Sd.Kfz. 171 Panther]": "HULL MG34 [Sd.Kfz.171 Panther]",
    "150-MM-HAUBITZE [sFH 18]": "150MM HOWITZER [sFH 18]",
    "BOMBENANGRIFF": "BOMBING RUN",
    "D-5T 85 MM [IS-1]": "D-5T 85MM [IS-1]",
    "PPSH 41 (TROMMEL)": "PPSH 41 W/DRUM",
    "50 mm KwK 39/1 [Sd.Kfz. 234 Puma]": "50mm KwK 39/1 [Sd.Kfz.234 Puma]",
    "MG34 (KOAXIAL) [Sd.Kfz. 171 Panther]": "COAXIAL MG34 [Sd.Kfz.171 Panther]",
    "DT (KOAXIAL) [IS-1]": "COAXIAL DT [IS-1]",
    "MG34 (KOAXIAL) [Sd.Kfz. 121 Luchs]": "COAXIAL MG34 [Sd.Kfz.121 Luchs]",
    "PRÄZISIONSSCHLAG": "PRECISION STRIKE"
}