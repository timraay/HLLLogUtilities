from __future__ import annotations
import asyncio, hmac, hashlib, json, typing as T
import aiohttp
from datetime import datetime

try:
    # Optional imports: only used when dispatching from HLU models
    from lib.info.models import (
        EventModel,
        PlayerKillEvent,
        PlayerTeamkillEvent,
        PlayerSuicideEvent,
        Player,
        Team as TeamModel,
        Squad as SquadModel,
    )
    import lib.mappings as mappings
except Exception:
    # Keep sink usable standalone if HLU internals are unavailable at import time
    EventModel = object  # type: ignore
    PlayerKillEvent = object  # type: ignore
    PlayerTeamkillEvent = object  # type: ignore
    PlayerSuicideEvent = object  # type: ignore
    Player = object  # type: ignore
    TeamModel = object  # type: ignore
    SquadModel = object  # type: ignore
    mappings = None  # type: ignore

class WebhookSink:
    """
    POSTs selected parsed events to a webhook.
    Config:
      url: http(s) endpoint (e.g. http://overwatch:8080/event)
      secret: shared secret for HMAC-SHA256 in 'X-HLU-Signature'
      include: list[str] event types to send (default: vehicle_destroyed)
    """
    def __init__(self, url: str, secret: str = "", include: T.Iterable[str] | None = None, timeout: float = 5.0):
        self.url = url
        self.secret = secret.encode() if secret else b""
        self.include = set(include or ["vehicle_destroyed"])
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        # Track armor squad kill streaks (team, squad_id) -> count
        self._streaks: dict[tuple[str, str], int] = {}

    async def start(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))

    async def stop(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def handle_event(self, evt: dict):
        t = evt.get("type")
        if t not in self.include or not self._session:
            return
        payload = json.dumps(evt, separators=(",", ":")).encode()
        headers = {}
        if self.secret:
            sig = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()
            headers["X-HLU-Signature"] = sig
        try:
            async with self._session.post(self.url, data=payload, headers=headers) as resp:
                await resp.read()  # drain
        except Exception:
            # Don't break the pipeline on network hiccups
            pass

    # ----------------------------
    # Normalization helpers (HLU)
    # ----------------------------

    @staticmethod
    def _iso_ts(dt: datetime | None) -> str:
        return (dt or datetime.utcnow()).isoformat()

    @staticmethod
    def _norm_team(team: str | TeamModel | None) -> str | None:
        if team is None:
            return None
        if isinstance(team, str):
            if team.lower().startswith("ally"):
                return "ALLIES"
            if team.lower().startswith("axis"):
                return "AXIS"
            return team.upper()
        # lib.info.models.Team has .name like "Allies"/"Axis"
        name = getattr(team, "name", None)
        if isinstance(name, str):
            return "ALLIES" if name.lower().startswith("ally") else ("AXIS" if name.lower().startswith("axis") else name.upper())
        # As a last resort, try enum-like name
        enum_name = getattr(team, "__class__", type("_", (), {})).__name__
        return enum_name.upper() if enum_name else None

    @staticmethod
    def _armor_squad_id(squad: SquadModel | None) -> str | None:
        if not squad:
            return None
        # HLU tracks current squad; prefer the literal name as ID (e.g., "A1")
        sid = getattr(squad, "name", None)
        return sid if isinstance(sid, str) and sid.strip() else None

    @staticmethod
    def _is_armor_squad(squad: SquadModel | None) -> bool:
        if not squad:
            return False
        stype = getattr(squad, "type", None)
        if isinstance(stype, str):
            return stype.lower() in {"armor", "armour", "armored", "armoured"}
        return False

    @staticmethod
    def _vehicle_class_from_name(vehicle_name: str | None) -> str | None:
        if not vehicle_name:
            return None
        cls_map = getattr(mappings, "_VEHICLE_CLASSES", {}) if mappings else {}
        vclass = cls_map.get(vehicle_name)
        if not vclass:
            return None
        # Map HLU classes to normalized variants
        mapping = {
            "Light Tank": "LIGHT",
            "Medium Tank": "MEDIUM",
            "Heavy Tank": "HEAVY",
            "Tank Destroyer": "TD",
        }
        return mapping.get(vclass)

    @staticmethod
    def _normalize_vehicle_class(vclass: str | None) -> str | None:
        if not vclass:
            return None
        v = vclass.upper()
        if v in {"LIGHT", "MEDIUM", "HEAVY", "TD"}:
            return v
        # Try map common aliases
        alias = {
            "LIGHT TANK": "LIGHT",
            "MEDIUM TANK": "MEDIUM",
            "HEAVY TANK": "HEAVY",
            "TANK DESTROYER": "TD",
        }.get(v)
        return alias

    async def emit_vehicle_destroyed(
        self,
        *,
        timestamp: str | None = None,
        killer_name: str | None = None,
        killer_steam_id: str | None = None,
        killer_team: str | TeamModel | None = None,
        killer_squad_id: str | None = None,
        victim_team: str | TeamModel | None = None,
        vehicle_class: str | None = None,
        vehicle_name: str | None = None,
        current_map: str | None = None,
        match_id: str | None = None,
    ):
        # Resolve required fields
        iso_ts = timestamp or self._iso_ts(None)
        vclass = self._normalize_vehicle_class(vehicle_class) or self._vehicle_class_from_name(vehicle_name)
        if vclass not in {"LIGHT", "MEDIUM", "HEAVY", "TD"}:
            return  # tanks only
        # Update streaks for armor squad killers if we can attribute
        k_team_norm = self._norm_team(killer_team)
        if k_team_norm and killer_squad_id:
            key = (k_team_norm, killer_squad_id)
            self._streaks[key] = self._streaks.get(key, 0) + 1
        evt = {
            "type": "vehicle_destroyed",
            "timestamp": iso_ts,
            "killer": {
                "name": killer_name,
                "steam_id": killer_steam_id,
                "team": k_team_norm,
                "squad_id": killer_squad_id,
            },
            "victim_vehicle": {
                "side": self._norm_team(victim_team),
                "class": vclass,
                "name": vehicle_name,
            },
            "map": current_map,
            "match_id": match_id,
        }
        await self.handle_event(evt)

    async def handle_hlu_event(self, event: EventModel, match_id: str | None = None):
        """Accept an HLU EventModel, derive and emit normalized webhook events.

        - Resets internal armor squad tank kill streaks when a squad member dies.
        - Vehicle destroyed emission is expected to be triggered from a dedicated upstream signal;
          if later exposed as a model, add handling here similarly.
        """
        # Map and timestamp
        iso_ts = self._iso_ts(getattr(event, "event_time", None))
        server = getattr(getattr(event, "root", None), "server", None)
        current_map = getattr(server, "map", None)

        # Player deaths in Armor squads: reset internal streaks, do not emit
        if isinstance(event, (PlayerKillEvent, PlayerTeamkillEvent)):
            victim: Player | None = getattr(event, "other", None)
            if victim and self._is_armor_squad(getattr(victim, "squad", None)):
                team_norm = self._norm_team(getattr(getattr(victim, "team", None), "name", None) or getattr(victim, "team", None))
                squad_id = self._armor_squad_id(getattr(victim, "squad", None))
                if team_norm and squad_id:
                    self._streaks[(team_norm, squad_id)] = 0
        elif isinstance(event, PlayerSuicideEvent):
            victim: Player | None = getattr(event, "player", None)
            if victim and self._is_armor_squad(getattr(victim, "squad", None)):
                team_norm = self._norm_team(getattr(getattr(victim, "team", None), "name", None) or getattr(victim, "team", None))
                squad_id = self._armor_squad_id(getattr(victim, "squad", None))
                if team_norm and squad_id:
                    self._streaks[(team_norm, squad_id)] = 0
