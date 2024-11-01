import re
from enum import Enum
import pydantic
import logging
from typing import Union

def get_map_and_mode(layer_name: str):
    map, mode = layer_name.rsplit(' ', 1)
    map.replace(' NIGHT', '')

    return (
        MAPS_BY_NAME[map].prettyname if map in MAPS_BY_NAME else map,
        Gamemode[mode].value.capitalize() if mode in Gamemode._member_names_ else mode
    )

RE_LAYER_NAME = re.compile(r"^(?P<tag>[A-Z]{3,5})_(?P<size>S|L)_(?P<year>\d{4})_(?:(?P<environment>\w+)_)?P_(?P<gamemode>\w+)$")
RE_LEGACY_LAYER_NAME = re.compile(r"^(?P<name>[a-z0-9]+)_(?:(?P<offensive>off(?:ensive)?)_?(?P<attackers>[a-zA-Z]+)|(?P<gamemode>[a-z]+)(?:_V2)?)(?:_(?P<environment>[a-z]+))?$")

def is_steamid(steamid: str):
    return "-" not in steamid

class Gamemode(str, Enum):
    WARFARE = "warfare"
    OFFENSIVE = "offensive"
    CONTROL = "control"
    PHASED = "phased"
    MAJORITY = "majority"

    @classmethod
    def large(cls):
        return (cls.WARFARE, cls.OFFENSIVE,)

    @classmethod
    def small(cls):
        return (cls.CONTROL, cls.PHASED, cls.MAJORITY,)

    def is_small(self):
        return (
            self == Gamemode.CONTROL
            or self == Gamemode.PHASED
            or self == Gamemode.MAJORITY
        )

    def is_large(self):
        return self in Gamemode.large()

    def is_small(self):
        return self in Gamemode.small()

class Team(str, Enum):
    ALLIES = "Allies"
    AXIS = "Axis"

class Environment(str, Enum):
    DAY = "Day"
    OVERCAST = "Overcast"
    DUSK = "Dusk"
    DAWN = "Dawn"
    NIGHT = "Night"
    RAIN = "Rain"

class Faction(Enum):
    class Faction(pydantic.BaseModel):
        name: str
        team: Team

    US = Faction(name="us", team=Team.ALLIES)
    GER = Faction(name="ger", team=Team.AXIS)
    RUS = Faction(name="rus", team=Team.ALLIES)
    GB = Faction(name="gb", team=Team.ALLIES)
    CW = Faction(name="gb", team=Team.ALLIES)

class Map(pydantic.BaseModel):
    id: str
    name: str
    tag: str
    prettyname: str
    shortname: str
    allies: 'Faction'
    axis: 'Faction'

    def __str__(self) -> str:
        return self.id
    
    def __repr__(self) -> str:
        return str(self)
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def __eq__(self, other) -> bool:
        if isinstance(other, (Map, str)):
            return str(self) == str(other)
        return NotImplemented

class Layer(pydantic.BaseModel):
    id: str
    map: Map
    gamemode: Gamemode
    attackers: Union[Team, None] = None
    environment: Environment = Environment.DAY

    def __str__(self) -> str:
        return self.id
    
    def __repr__(self) -> str:
        return str(self)
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def __eq__(self, other) -> bool:
        if isinstance(other, (Layer, str)):
            return str(self) == str(other)
        return NotImplemented
    
    @property
    def attacking_faction(self):
        if self.attackers == Team.ALLIES:
            return self.map.allies
        elif self.attackers == Team.AXIS:
            return self.map.axis
        return None

    def pretty(self):
        out = self.map.prettyname
        if self.gamemode == Gamemode.OFFENSIVE:
            out += " Off."
            if self.attackers:
                out += f" {self.attacking_faction.value.name.upper()}"
        elif self.gamemode.is_small():
            # TODO: Remove once more Skirmish modes release
            out += " Skirmish"
        else:
            out += f" {self.gamemode.value.capitalize()}"
        if self.environment != Environment.DAY:
            out += f" ({self.environment.value})"
        return out

MAPS = { m.id: m for m in (
    Map(
        id="stmereeglise",
        name="SAINTE-MÈRE-ÉGLISE",
        tag="SME",
        prettyname="St. Mere Eglise",
        shortname="SME",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="stmariedumont",
        name="ST MARIE DU MONT",
        tag="SMDM",
        prettyname="St. Marie Du Mont",
        shortname="SMDM",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="utahbeach",
        name="UTAH BEACH",
        tag="UTA",
        prettyname="Utah Beach",
        shortname="Utah",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="omahabeach",
        name="OMAHA BEACH",
        tag="OMA",
        prettyname="Omaha Beach",
        shortname="Omaha",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="purpleheartlane",
        name="PURPLE HEART LANE",
        tag="PHL",
        prettyname="Purple Heart Lane",
        shortname="PHL",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="carentan",
        name="CARENTAN",
        tag="CAR",
        prettyname="Carentan",
        shortname="Carentan",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="hurtgenforest",
        name="HÜRTGEN FOREST",
        tag="HUR",
        prettyname="Hurtgen Forest",
        shortname="Hurtgen",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="hill400",
        name="HILL 400",
        tag="HIL",
        prettyname="Hill 400",
        shortname="Hill 400",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="foy",
        name="FOY",
        tag="FOY",
        prettyname="Foy",
        shortname="Foy",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="kursk",
        name="KURSK",
        tag="KUR",
        prettyname="Kursk",
        shortname="Kursk",
        allies=Faction.RUS,
        axis=Faction.GER,
    ),
    Map(
        id="stalingrad",
        name="STALINGRAD",
        tag="STA",
        prettyname="Stalingrad",
        shortname="Stalingrad",
        allies=Faction.RUS,
        axis=Faction.GER,
    ),
    Map(
        id="remagen",
        name="REMAGEN",
        tag="REM",
        prettyname="Remagen",
        shortname="Remagen",
        allies=Faction.US,
        axis=Faction.GER,
    ),
    Map(
        id="kharkov",
        name="Kharkov",
        tag="KHA",
        prettyname="Kharkov",
        shortname="Kharkov",
        allies=Faction.RUS,
        axis=Faction.GER,
    ),
    Map(
        id="driel",
        name="DRIEL",
        tag="DRL",
        prettyname="Driel",
        shortname="Driel",
        allies=Faction.GB,
        axis=Faction.GER,
    ),
    Map(
        id="elalamein",
        name="EL ALAMEIN",
        tag="ELA",
        prettyname="El Alamein",
        shortname="Alamein",
        allies=Faction.GB,
        axis=Faction.GER,
    ),
    Map(
        id="mortain",
        name="MORTAIN",
        tag="MOR",
        prettyname="Mortain",
        shortname="Mortain",
        allies=Faction.US,
        axis=Faction.GER,
    )
)}

LAYERS = {l.id: l for l in (
    Layer(
        id="stmereeglise_warfare",
        map=MAPS["stmereeglise"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="stmereeglise_warfare_night",
        map=MAPS["stmereeglise"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="stmereeglise_offensive_us",
        map=MAPS["stmereeglise"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="stmereeglise_offensive_ger",
        map=MAPS["stmereeglise"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="SME_S_1944_Day_P_Skirmish",
        map=MAPS["stmereeglise"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DAY,
    ),
    Layer(
        id="SME_S_1944_Morning_P_Skirmish",
        map=MAPS["stmereeglise"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DAWN,
    ),
    Layer(
        id="SME_S_1944_Night_P_Skirmish",
        map=MAPS["stmereeglise"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="stmariedumont_warfare",
        map=MAPS["stmariedumont"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="stmariedumont_warfare_night",
        map=MAPS["stmariedumont"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="SMDM_S_1944_Day_P_Skirmish",
        map=MAPS["stmariedumont"],
        gamemode=Gamemode.CONTROL,
    ),
    Layer(
        id="SMDM_S_1944_Night_P_Skirmish",
        map=MAPS["stmariedumont"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.NIGHT
    ),
    Layer(
        id="SMDM_S_1944_Rain_P_Skirmish",
        map=MAPS["stmariedumont"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.RAIN
    ),
    Layer(
        id="stmariedumont_off_us",
        map=MAPS["stmariedumont"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="stmariedumont_off_ger",
        map=MAPS["stmariedumont"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="utahbeach_warfare",
        map=MAPS["utahbeach"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="utahbeach_warfare_night",
        map=MAPS["utahbeach"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="utahbeach_offensive_us",
        map=MAPS["utahbeach"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="utahbeach_offensive_ger",
        map=MAPS["utahbeach"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="omahabeach_warfare",
        map=MAPS["omahabeach"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="omahabeach_warfare_night",
        map=MAPS["omahabeach"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="omahabeach_offensive_us",
        map=MAPS["omahabeach"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="omahabeach_offensive_ger",
        map=MAPS["omahabeach"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="PHL_L_1944_Warfare",
        map=MAPS["purpleheartlane"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.RAIN
    ),
    Layer(
        id="PHL_L_1944_Warfare_Night",
        map=MAPS["purpleheartlane"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="PHL_L_1944_OffensiveUS",
        map=MAPS["purpleheartlane"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="PHL_L_1944_OffensiveGER",
        map=MAPS["purpleheartlane"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="carentan_warfare",
        map=MAPS["carentan"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="carentan_warfare_night",
        map=MAPS["carentan"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="carentan_offensive_us",
        map=MAPS["carentan"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="carentan_offensive_ger",
        map=MAPS["carentan"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="CAR_S_1944_Day_P_Skirmish",
        map=MAPS["carentan"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DAY,
    ),
    Layer(
        id="CAR_S_1944_Rain_P_Skirmish",
        map=MAPS["carentan"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.RAIN,
    ),
    Layer(
        id="CAR_S_1944_Dusk_P_Skirmish",
        map=MAPS["carentan"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DUSK,
    ),
    Layer(
        id="hurtgenforest_warfare_V2",
        map=MAPS["hurtgenforest"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="hurtgenforest_warfare_V2_night",
        map=MAPS["hurtgenforest"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="hurtgenforest_offensive_US",
        map=MAPS["hurtgenforest"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="hurtgenforest_offensive_ger",
        map=MAPS["hurtgenforest"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="hill400_warfare",
        map=MAPS["hill400"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="hill400_warfare_night",
        map=MAPS["hill400"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="hill400_offensive_US",
        map=MAPS["hill400"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="hill400_offensive_ger",
        map=MAPS["hill400"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="foy_warfare",
        map=MAPS["foy"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="foy_warfare_night",
        map=MAPS["foy"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="foy_offensive_us",
        map=MAPS["foy"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="foy_offensive_ger",
        map=MAPS["foy"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="kursk_warfare",
        map=MAPS["kursk"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="kursk_warfare_night",
        map=MAPS["kursk"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="kursk_offensive_rus",
        map=MAPS["kursk"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="kursk_offensive_ger",
        map=MAPS["kursk"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="stalingrad_warfare",
        map=MAPS["stalingrad"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="stalingrad_warfare_night",
        map=MAPS["stalingrad"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="stalingrad_offensive_rus",
        map=MAPS["stalingrad"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="stalingrad_offensive_ger",
        map=MAPS["stalingrad"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="remagen_warfare",
        map=MAPS["remagen"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="remagen_warfare_night",
        map=MAPS["remagen"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="remagen_offensive_us",
        map=MAPS["remagen"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="remagen_offensive_ger",
        map=MAPS["remagen"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="kharkov_warfare",
        map=MAPS["kharkov"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="kharkov_warfare_night",
        map=MAPS["kharkov"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="kharkov_offensive_rus",
        map=MAPS["kharkov"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="kharkov_offensive_ger",
        map=MAPS["kharkov"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="driel_warfare",
        map=MAPS["driel"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="driel_warfare_night",
        map=MAPS["driel"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="driel_offensive_us",
        map=MAPS["driel"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="driel_offensive_ger",
        map=MAPS["driel"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="DRL_S_1944_P_Skirmish",
        map=MAPS["driel"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DAWN,
    ),
    Layer(
        id="DRL_S_1944_Night_P_Skirmish",
        map=MAPS["driel"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.NIGHT,
    ),
    Layer(
        id="DRL_S_1944_Day_P_Skirmish",
        map=MAPS["driel"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DAY,
    ),
    Layer(
        id="elalamein_warfare",
        map=MAPS["elalamein"],
        gamemode=Gamemode.WARFARE,
    ),
    Layer(
        id="elalamein_warfare_night",
        map=MAPS["elalamein"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.DUSK,
    ),
    Layer(
        id="elalamein_offensive_CW",
        map=MAPS["elalamein"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES
    ),
    Layer(
        id="elalamein_offensive_ger",
        map=MAPS["elalamein"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS
    ),
    Layer(
        id="ELA_S_1942_P_Skirmish",
        map=MAPS["elalamein"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DAY,
    ),
    Layer(
        id="ELA_S_1942_Night_P_Skirmish",
        map=MAPS["elalamein"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DUSK,
    ),
    Layer(
        id="mortain_warfare_day",
        map=MAPS["mortain"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.DAY,
    ),
    Layer(
        id="mortain_warfare_overcast",
        map=MAPS["mortain"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.OVERCAST,
    ),
    Layer(
        id="mortain_warfare_evening",
        map=MAPS["mortain"],
        gamemode=Gamemode.WARFARE,
        environment=Environment.DUSK,
    ),
    Layer(
        id="mortain_offensiveUS_day",
        map=MAPS["mortain"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES,
        environment=Environment.DAY,
    ),
    Layer(
        id="mortain_offensiveUS_overcast",
        map=MAPS["mortain"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES,
        environment=Environment.OVERCAST,
    ),
    Layer(
        id="mortain_offensiveUS_evening",
        map=MAPS["mortain"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.ALLIES,
        environment=Environment.DUSK,
    ),
    Layer(
        id="mortain_offensiveger_day",
        map=MAPS["mortain"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS,
        environment=Environment.DAY,
    ),
    Layer(
        id="mortain_offensiveger_overcast",
        map=MAPS["mortain"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS,
        environment=Environment.OVERCAST,
    ),
    Layer(
        id="mortain_offensiveger_evening",
        map=MAPS["mortain"],
        gamemode=Gamemode.OFFENSIVE,
        attackers=Team.AXIS,
        environment=Environment.DUSK,
    ),
    Layer(
        id="mortain_skirmish_day",
        map=MAPS["mortain"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DAY,
    ),
    Layer(
        id="mortain_skirmish_overcast",
        map=MAPS["mortain"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.OVERCAST,
    ),
    Layer(
        id="mortain_skirmish_evening",
        map=MAPS["mortain"],
        gamemode=Gamemode.CONTROL,
        environment=Environment.DUSK,
    ),
)}

MAPS_BY_NAME = { m.name: m for m in MAPS.values() }

def parse_layer(layer_name: str):
    layer = LAYERS.get(layer_name)
    if layer:
        return layer
    
    logging.warning("Unknown layer %s", layer_name)

    layer_match = RE_LAYER_NAME.match(layer_name)
    if not layer_match:
        return _parse_legacy_layer(layer_name)
    
    layer_data = layer_match.groupdict()

    tag = layer_data["tag"]
    map_ = None
    for m in MAPS.values():
        if m.tag == tag:
            map_ = m
            break
    if map_ is None:
        map_ = Map(
            id=tag.lower(),
            name=tag,
            tag=tag,
            prettyname=tag.capitalize(),
            shortname=tag,
            allies=Faction.US,
            axis=Faction.GER,
        )

    if layer_data["gamemode"] == "Skirmish":
        gamemode = Gamemode.CONTROL
    else:
        try:
            gamemode = Gamemode[layer_data["gamemode"].upper()]
        except KeyError:
            gamemode = Gamemode.WARFARE
        
    if gamemode == Gamemode.OFFENSIVE:
        attackers = Team.ALLIES
    else:
        attackers = None        
    
    if layer_data["environment"]:
        try:
            environment = Environment[layer_data["environment"].upper()]
        except KeyError:
            environment = Environment.DAY
    else:
        environment = Environment.DAY

    return Layer(
        id=layer_name,
        map=map_,
        gamemode=gamemode,
        attackers=attackers,
        environment=environment,
    )

def _parse_legacy_layer(layer_name: str):
    layer_match = RE_LEGACY_LAYER_NAME.match(layer_name)
    if not layer_match:
        raise ValueError("Unparsable layer '%s'" % layer_name)
    
    layer_data = layer_match.groupdict()
    
    name = layer_data["name"]
    map_ = MAPS.get(layer_data["name"])
    if not map_:
        map_ = Map(
            id=name,
            name=name.capitalize(),
            tag=name.upper(),
            prettyname=name.capitalize(),
            shortname=name.capitalize(),
            allies=Faction.US,
            axis=Faction.GER,
        )

    result = Layer(
        id=layer_name,
        map=map_,
        gamemode=Gamemode.WARFARE
    )

    if layer_data["offensive"]:
        result.gamemode = Gamemode.OFFENSIVE
        try:
            result.attackers = Faction[layer_data["attackers"].upper()].value.team
        except KeyError:
            pass

    elif layer_data["gamemode"]:
        try:
            result.gamemode = Gamemode[layer_data["gamemode"].upper()]
        except KeyError:
            pass
    
    environment = layer_data["environment"]
    if environment:
        try:
            result.environment = Environment[environment.upper()]
        except KeyError:
            pass
    
    return result


SQUAD_LEADER_ROLES = {"Officer", "TankCommander", "Spotter"}
TEAM_LEADER_ROLES = {"ArmyCommander"}

INFANTRY_ROLES = {"Officer", "Assault", "AutomaticRifleman", "Medic", "Support",
                  "HeavyMachineGunner", "AntiTank", "Engineer", "Rifleman"}
TANK_ROLES = {"TankCommander", "Crewman"}
RECON_ROLES = {"Spotter", "Sniper"}

WEAPONS = {
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
    # "M3 Half-track": "RUS Roadkill [RUS Half-track]",
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
    # "M2 Browning [M3 Half-track]": "RUS Half-track MG [RUS Half-track]",

    "SMLE No.1 Mk III": "SMLE Mk III",
    "Rifle No.5 Mk I": "Jungle Carbine",
    "Rifle No.4 Mk I": "No.4 Rifle Mk I",
    "Sten Gun Mk.II": "Sten Mk II",
    "Sten Gun Mk.V": "Sten Mk V",
    "Lanchester": "Lanchester",
    "M1928A1 THOMPSON": "M1928A1 Thompson",
    "Bren Gun": "Bren Gun",
    "Lewis Gun": "Lewis Gun",
    "FLAMETHROWER": "GB Flamethrower",
    "Lee-Enfield Pattern 1914 Sniper": "P14 Enfield (8x)",
    "Webley MK VI": "Webley Mk IV",
    "Fairbairn–Sykes": "GB Melee",
    "Satchel": "Satchel Charge",
    "Mills Bomb": "GB Grenade",
    "PIAT": "PIAT",
    "Boys Anti-tank Rifle": "Boys AT Rifle",
    "A.P. Shrapnel Mine Mk II": "GB AP Mine",
    "A.T. Mine G.S. Mk V": "GB AT Mine",
    "QF 6-POUNDER [QF 6-Pounder]": "GB AT Gun",
    "QF 25-POUNDER [QF 25-Pounder]": "GB Artillery",
    "Daimler": "GB Roadkill [Daimler]",
    "Tetrarch": "GB Roadkill [Tetrarch]",
    "M3 Stuart Honey": "GB Roadkill [Stuart Honey]",
    "Cromwell": "GB Roadkill [Cromwell]",
    "Crusader": "GB Roadkill [Crusader]",
    "Firefly": "GB Roadkill [Firefly]",
    "Churchill Mk.III": "GB Roadkill [Churchill Mk III]",
    "Churchill Mk.VII": "GB Roadkill [Churchill Mk VII]",
    "Bedford OYD (Supply)": "GB Roadkill [GB Supply Truck]",
    "Bedford OYD (Transport)": "GB Roadkill [GB Transport Truck]",
    # "M3 Half-track": "GB Roadkill [GB Half-track]",
    # "Jeep Willys": "GB Roadkill [GB Jeep]",
    "QF 2-POUNDER [Daimler]": "GB Tank Cannon [Daimler]",
    "COAXIAL BESA [Daimler]": "GB Tank Coaxial [Daimler]",
    "QF 2-POUNDER [Tetrarch]": "GB Tank Cannon [Tetrarch]",
    "COAXIAL BESA [Tetrarch]": "GB Tank Coaxial [Tetrarch]",
    "37MM CANNON [M3 Stuart Honey]": "GB Tank Cannon [Stuart Honey]",
    "COAXIAL M1919 [M3 Stuart Honey]": "GB Tank Coaxial [Stuart Honey]",
    "HULL M1919 [M3 Stuart Honey]": "GB Tank Hull MG [Stuart Honey]",
    "QF 75MM [Cromwell]": "GB Tank Cannon [Cromwell]",
    "COAXIAL BESA [Cromwell]": "GB Tank Coaxial [Cromwell]",
    "HULL BESA [Cromwell]": "GB Tank Hull MG [Cromwell]",
    "OQF 57MM [Crusader Mk.III]": "GB Tank Cannon [Crusader]",
    "COAXIAL BESA [Crusader Mk.III]": "GB Tank Coaxial [Crusader]",
    "QF 17-POUNDER [Firefly]": "GB Tank Cannon [Firefly]",
    "COAXIAL M1919 [Firefly]": "GB Tank Coaxial [Firefly]",
    "OQF 57MM [Churchill Mk.III]": "GB Tank Cannon [Churchill Mk III]",
    "COAXIAL BESA 7.92mm [Churchill Mk.III]": "GB Tank Coaxial [Churchill Mk III]",
    "HULL BESA 7.92mm [Churchill Mk.III]": "GB Tank Hull MG [Churchill Mk III]",
    "OQF 75MM [Churchill Mk.VII]": "GB Tank Cannon [Churchill Mk VII]",
    "COAXIAL BESA 7.92mm [Churchill Mk.VII]": "GB Tank Coaxial [Churchill Mk VII]",
    "HULL BESA 7.92mm [Churchill Mk.VII]": "GB Tank Hull MG [Churchill Mk VII]",
    # "M2 Browning [M3 Half-track]": "GB Half-track MG [GB Half-track]",

    "UNKNOWN": "Unknown",
    "BOMBING RUN": "Bombing Run",
    "STRAFING RUN": "Strafing Run",
    "PRECISION STRIKE": "Precision Strike",
    "Unknown": "Katyusha Barrage",
    "FLARE GUN": "Flare Gun"
}

BASIC_CATEGORIES_ALLIES = {value: cat for cat, values in {
    "Submachine Gun": [ "M1A1 Thompson", "M3 Grease Gun", "PPSh-41", "PPSh-41 Drum", "Sten Mk II", "Sten Mk V", "Lanchester", "M1928A1 Thompson" ],
    "Semi-Auto Rifle": [ "M1 Garand", "M1 Carbine", "SVT40" ],
    "Bolt-Action Rifle": [ "Mosin-Nagant 1891", "Mosin-Nagant 91/30", "Mosin-Nagant M38", "SMLE Mk III", "Jungle Carbine", "No.4 Rifle Mk 1" ],
    "Assault Rifle": [ "M1918A2 BAR", "M97 Trench Gun", "Bren Gun" ],
    "Sniper Rifle": [ "M1903 Springfield (4x)", "Mosin-Nagant 91/30 (4x)", "SVT40 (4x)", "P14 Enfield (8x)", "No.4 Rifle Mk I (8x)" ],
    "Machine Gun": [ "M1919 Browning", "DP-27", "Lewis Gun" ],
    "Pistol": [ "Colt M1911", "Nagant M1895", "Tokarev TT33", "Webley MK IV" ],
    "Melee": ["US Melee", "RUS Melee", "GB Melee" ],
    "Flamethrower": [ "US Flamethrower", "GB Flamethrower" ],
    "Artillery": ["US Artillery", "RUS Artillery", "GB Artillery" ],
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
        "US Tank Cannon [Sherman M4A3 75w]",
        "US Tank Coaxial [Sherman M4A3 75w]",
        "US Tank Hull MG [Sherman M4A3 75w]",
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
        "GB Roadkill [Daimler]",
        "GB Roadkill [Tetrarch]",
        "GB Roadkill [Stuart Honey]",
        "GB Roadkill [Cromwell]",
        "GB Roadkill [Crusader]",
        "GB Roadkill [Firefly]",
        "GB Roadkill [Churchill Mk III]",
        "GB Roadkill [Churchill Mk VII]",
        "GB Roadkill [GB Supply Truck]",
        "GB Roadkill [GB Transport Truck]",
        "GB Roadkill [GB Half-track]",
        "GB Roadkill [GB Jeep]",
        "GB Tank Cannon [Daimler]",
        "GB Tank Coaxial [Daimler]",
        "GB Tank Cannon [Tetrarch]",
        "GB Tank Coaxial [Tetrarch]",
        "GB Tank Cannon [Stuart Honey]",
        "GB Tank Coaxial [Stuart Honey]",
        "GB Tank Hull MG [Stuart Honey]",
        "GB Tank Cannon [Cromwell]",
        "GB Tank Coaxial [Cromwell]",
        "GB Tank Hull MG [Cromwell]",
        "GB Tank Cannon [Crusader]",
        "GB Tank Coaxial [Crusader]",
        "GB Tank Cannon [Firefly]",
        "GB Tank Coaxial [Firefly]",
        "GB Tank Cannon [Churchill Mk III]",
        "GB Tank Coaxial [Churchill Mk III]",
        "GB Tank Hull MG [Churchill Mk III]",
        "GB Tank Cannon [Churchill Mk VII]",
        "GB Tank Coaxial [Churchill Mk VII]",
        "GB Tank Hull MG [Churchill Mk VII]",
        "GB Half-track MG [GB Half-track]",
    ],
    "Grenade": [
        "US Grenade", "RUS Grenade", "GB Grenade",
        "US AP Mine", "RUS AP Mine", "GB AP Mine",
        "Molotov"
    ],
    "Anti-Tank": [
        "US AT Gun", "RUS AT Gun", "GB AT Gun",
        "US AT Mine", "RUS AT Mine", "GB AT Mine",
        "Bazooka", "PTRS-41", "PIAT", "Boys AT Rifle", "Gammon Bomb"
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

BASIC_CATEGORIES_SHARED = {value: cat for cat, values in {
    "Ability": [ "Bombing Run", "Strafing Run", "Precision Strike" ],
}.items() for value in values}

BASIC_CATEGORIES = {
    **BASIC_CATEGORIES_ALLIES,
    **BASIC_CATEGORIES_AXIS,
    **BASIC_CATEGORIES_SHARED
}

_VEHICLE_CLASSES = {vehicle: _class for _class, vehicles in {
    "Jeep": [ "US Jeep", "GER Jeep", "RUS Jeep" ],
    "Truck": [ "US Supply Truck", "US Transport Truck", "GER Supply Truck", "GER Transport Truck", "RUS Supply Truck", "RUS Transport Truck", "GB Supply Truck", "GB Transport Truck" ],
    "Half-track": [ "US Half-track", "GER Half-track" ],
    "Recon Vehicle": [ "M8 Greyhound", "Puma", "BA-10", "Daimler" ],
    "Light Tank": [ "Stuart M5A1", "Luchs", "T70", "Tetrarch", "Stuart Honey" ],
    "Medium Tank": [ "Sherman M4", "Sherman M4A3 75w", "Panzer IV", "T34/76", "Cromwell", "Crusader" ],
    "Heavy Tank": [ "Sherman 75mm", "Sherman 76mm", "Panther", "Tiger 1", "IS-1", "Firefly", "Churchill Mk III", "Churchill Mk VII" ]
}.items() for vehicle in vehicles}

VEHICLES = dict()
VEHICLES_ALLIES = dict()
VEHICLES_AXIS = dict()
VEHICLE_WEAPONS = dict()
VEHICLE_WEAPONS_FACTIONLESS = dict()
VEHICLE_CLASSES = dict()
for weapon in WEAPONS.values():
    match = re.match(r"((US|GER|RUS|GB) (.+)) \[(.+)\]$", weapon)
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
    match = re.match(r"(US|GER|RUS|GB) (.+)$", weapon)
    if match:
        FACTIONLESS[weapon] = match.group(2)
