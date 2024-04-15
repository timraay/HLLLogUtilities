import asyncio
import aiohttp
from datetime import datetime, timedelta
from functools import wraps
import re
import math

from typing import List, TYPE_CHECKING

from lib.protocol import HLLRconProtocol
from lib.exceptions import HLLConnectionError
from lib.mappings import SQUAD_LEADER_ROLES, TEAM_LEADER_ROLES, INFANTRY_ROLES, TANK_ROLES, RECON_ROLES, is_steamid
from lib.info.models import *
from utils import to_timedelta, ttl_cache, get_config

if TYPE_CHECKING:
    from lib.session import HLLCaptureSession

NUM_WORKERS_PER_INSTANCE = get_config().getint('Session', 'NumRCONWorkers')
STEAM_API_KEY = get_config().get('Session', 'SteamApiKey')
KICK_INCOMPATIBLE_NAMES = get_config().getboolean('Session', 'KickIncompatibleNames')

def target_to_players(target: Union[Player, Squad, Team, None]) -> Union[List[Player], None]:
    if not target:
        return None
    elif isinstance(target, Player):
        return [target]
    elif target.has('players'):
        return [player for player in target.players if player]
    raise ValueError(f'{target.__class__.__name__} is not a valid target')

@ttl_cache(100, 60*60*2) # 2 hours
async def get_name_from_steam(steamid: str, __name: str = None) -> str:
    if not STEAM_API_KEY:
        raise RuntimeError("Steam Api Key not set")
    
    params = dict(
        key=STEAM_API_KEY,
        steamids=steamid,
        format='json'
    )
    async with aiohttp.ClientSession() as session:
        res = await session.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/", params=params)
        data = await res.json()
        return data['response']['players'][0]['personaname']


# --- Wrappers to help manage the connection
def start_method(func):
    @wraps(func)
    async def wrapper(self: 'HLLRcon', *args, force=False, **kwargs):
        if self.connected:
            if force:
                await self.stop(force=True)
            else:
                return
        
        self.logger.info('Starting RCON...')
        res = await asyncio.wait_for(func(self, *args, **kwargs), timeout=10)
        self.logger.info('Started RCON!')
        
        self._connected = True
        return res

    return wrapper
def stop_method(func):
    @wraps(func)
    async def wrapper(self: 'HLLRcon', force, *args, **kwargs):
        if not self.connected and not force:
            return
        
        self.logger.info('Stopping RCON...')

        self._connected = False
        res = await func(self, *args, **kwargs)
        
        self.logger.info('Stopped RCON!')
        return res
        
    return wrapper
def update_method(func):
    @wraps(func)
    async def wrapper(self: 'HLLRcon', *args, **kwargs):

        async def reconnect():
            try:
                await self.start(force=True)
                self.logger.info('Reconnected %r!', self)
            except Exception:
                self.logger.exception('Failed to reconnect %r. Missed %s consecutive gathers.', self, self._missed_gathers + 1)

        if not self.connected:
            if self._missed_gathers < 20 or self._missed_gathers % 20 == 0:
                self.logger.info('Trying to reconnect %r', self)
                await reconnect()

        if self.connected:
            try:
                res = await asyncio.wait_for(func(self, *args, **kwargs), timeout=10)
            except Exception:
                self._missed_gathers += 1
                self.logger.exception('Missed %s consecutive updates for %r, %s attempts left', self._missed_gathers, self, 20-self._missed_gathers)
                if self._missed_gathers in (4, 8, 12, 16, 20) or self._missed_gathers % 20 == 0:
                    await reconnect()
            else:
                self._missed_gathers = 0
                return res

        else:
            self._missed_gathers += 1

    return wrapper

class HLLRcon:
    def __init__(self, session: 'HLLCaptureSession'):
        self.session = session
        self.workers: List['HLLRconWorker'] = list()
        self.queue = asyncio.Queue()
        self._missed_gathers = 0

    @property
    def loop(self):
        return self.session.loop
    @property
    def credentials(self):
        return self.session.credentials
    @property
    def logger(self):
        return self.session.logger
    
    @property
    def connected(self):
        return self.workers and all(worker.connected for worker in self.workers)
    
    @start_method
    async def start(self):
        for worker in self.workers:
            await worker.stop()
            self.logger.warn('Stopped leftover worker %r, possibly the source was not properly stopped.', worker)
        
        self.workers = list()
        for i in range(NUM_WORKERS_PER_INSTANCE):
            num = i + 1
            worker = HLLRconWorker(parent=self, name=f"Worker #{num}")
            self.workers.append(worker)

        worker = self.workers[0]
        await worker.start()
        self.logger.info('Started worker %s', worker.name)

        results = await asyncio.gather(
            *[worker.start() for worker in self.workers[1:]],
            return_exceptions=True
        )
        for i, result in enumerate(results, start=1):
            worker = self.workers[i]
            if isinstance(result, Exception):
                self.logger.error('Failed to start worker %s: %s: %s', worker.name, type(result).__name__, result)
            else:
                self.logger.info('Started worker %s', worker.name)
            self.workers.append(worker)
        
        self._state = "in_progress"
        self._map = None
        self._end_warmup_handle = None
        self._logs_seen_time = datetime.now(tz=timezone.utc)
        self._logs_last_recorded = None
        self._player_deaths = dict()
        self._player_suicide_handles = dict()
        self._player_suicide_queue = set()

    @stop_method
    async def stop(self):
        num = 0
        while self.workers:
            num += 1
            worker = self.workers.pop(0)
            await worker.stop()
            self.logger.info('Stopped worker %s', worker.name)

    @update_method
    async def update(self):
        self._info = InfoHopper()
        await self._fetch_server_info()
        self.info = self._info
        return self.info

    async def reconnect(self):
        to_reconnect = [worker for worker in self.workers if not worker.connected]
        if to_reconnect:
            await asyncio.gather(*[worker._create_connection() for worker in to_reconnect])
            return True


    async def _fetch_server_info(self):
        data = dict()
        res = await asyncio.gather(
            # self.__fetch_persistent_server_info(),
            # self.__fetch_server_settings(),
            self.__fetch_current_server_info(),
            # self.__fetch_player_roles(),
            self.exec_command('showlog 1', multipart=True)
        )
        logs = res.pop(-1)
        for d in res:
            if isinstance(d, dict):
                data.update(d)

        map = data['map']
        if map == "Loading ''" or map.startswith("Untitled"):
            map = self._map
        elif self._map and map != self._map:
            self._info.events.add(ServerMapChangedEvent(self._info, old=self._map.replace('_RESTART', ''), new=map.replace('_RESTART', '')))
        self._info.events.add(ServerMapChangedEvent)
        clean_map = map.replace('_RESTART', '')

        # rotation = [m for m in data['rotation'] if m]
        
        server = Server(self._info,
            # name = data['name'],
            map = clean_map,
            next_map = data['next_map'].replace('_RESTART', ''),
            # settings = ServerSettings(self._info,
            #     rotation = rotation,
            #     max_players = int(data['slots'].split('/')[0]),
            #     max_queue_length = int(data['maxqueuedplayers']),
            #     max_vip_slots = int(data['numvipslots']),
            #     idle_kick_time = idle_kick_time,
            #     idle_kick_enabled = bool(idle_kick_time),
            #     ping_threshold = ping_threshold,
            #     ping_threshold_enabled = bool(ping_threshold),
            #     team_switch_cooldown = team_switch_cooldown,
            #     team_switch_cooldown_enabled = bool(team_switch_cooldown),
            #     auto_balance_threshold = int(data['autobalancethreshold']),
            #     auto_balance_enabled = True if data['autobalanceenabled'] == "on" else False,
            #     # vote_kick_threshold = data['votekickthreshold']
            #     vote_kick_enabled = True if data['votekickenabled'] == "on" else False,
            #     chat_filter = data['profanity'],
            #     chat_filter_enabled = True,
            # )
        )
        self._info.set_server(server)

        # self._info.add_players(*[Player(self._info, is_vip=p["steamid"] in self._vips, **p) for p in data['players']])
        self._info.add_players(*[Player(self._info, **p) for p in data['players']])
        self._info.add_squads(*[Squad(self._info, **sq) for sq in data['squads']])
        self._info.add_teams(
            Team(self._info, id=1, name="Allies", squads=Link('squads', {'team': {'id': 1}}, multiple=True), players=Link('players', {'team': {'id': 1}}, multiple=True)),
            Team(self._info, id=2, name="Axis",   squads=Link('squads', {'team': {'id': 2}}, multiple=True), players=Link('players', {'team': {'id': 2}}, multiple=True)),
        )

        for squad in self._info.squads:
            players = squad.players
            
            leader = None
            for player in players:
                if player.role in SQUAD_LEADER_ROLES:
                    leader = player.create_link()
                    break
            squad.leader = leader

            type_ = "infantry"
            for player in players:
                if player.role == "Rifleman":
                    continue
                elif player.role in INFANTRY_ROLES:
                    type_ = "infantry"
                elif player.role in TANK_ROLES:
                    type_ = "armor"
                elif player.role in RECON_ROLES:
                    type_ = "recon"
                else:
                    continue
                break
            squad.type = type_
        
        for team in self._info.teams:
            players = team.players
            leader = None
            for player in players:
                if player.role in TEAM_LEADER_ROLES:
                    leader = player.create_link()
                    break
            team.leader = leader

            if team.id == 1:
                team.score = int(data['team1_score'])
            elif team.id == 2:
                team.score = int(data['team2_score'])
        
        self.__parse_logs(logs)
        self._info.server.state = self._state
        self._map = map            
    
    async def exec_command(self, cmd, **kwargs) -> Union[str, list]:
        fut = self.loop.create_future()
        cmd_pack = (fut, cmd, kwargs, 2)
        self.queue.put_nowait(cmd_pack)
        res = await fut
        self.logger.debug('`%s` -> `%s`', cmd, str(res)[:200].replace('\n', '\\n')+'...' if len(str(res)) > 200 else str(res).replace('\n', '\\n'))
        return res


    @ttl_cache(1, 60*30) # 30 minutes
    async def __fetch_persistent_server_info(self):
        types = ['name', 'slots', 'maxqueuedplayers', 'numvipslots']
        data = await asyncio.gather(*[self.exec_command('get '+t) for t in types])
        return dict(zip(types, data))

    @ttl_cache(1, 60*4) # 4 minutes
    async def __fetch_server_settings(self):
        types = ['idletime', 'highping', 'teamswitchcooldown', 'autobalanceenabled', 'autobalancethreshold', 'votekickenabled', 'votekickthreshold']
        data = await asyncio.gather(
            *[self.exec_command('get '+t) for t in types],
            self.exec_command('get profanity', unpack_array=True)
        )
        return dict(zip(types+['profanity'], data))

    async def __fetch_current_server_info(self):
        playerids, gamestate = await asyncio.gather(
            # self.exec_command("rotlist"),
            self.exec_command("get playerids", unpack_array=True),
            self.exec_command("get gamestate")
        )
        # rotation = rotation.split('\n')

        players = list()
        squads_allies = dict()
        squads_axis = dict()

        playerids_normal = dict()
        playerids_problematic = dict()
        for playerid in playerids:
            """
            HLL truncates names on the 20th character. If that 20th character happens to be a space, the truncated
            name can no longer be used to find players via RCON. Since the playerinfo command does not accept
            steam IDs and we don't have any way of knowing the full name, the best we can do is skip the playerinfo
            command completely, and work with what we've got. #9

            Each character can be up to 3 bytes. If it is more, a character will be treated as multiple. Thus, a
            truncated name doesn't have to be 20 characters long, and can end with an incomplete character, which
            is then replaced simply with a question mark. In such a case, the playerinfo command will also fail.
            """
            name, steamid = playerid.rsplit(' : ', 1)
            problematic = False

            if name.endswith(' '):
                problematic = True
            elif name.endswith('?') and STEAM_API_KEY:
                if is_steamid(steamid):
                    full_name = await get_name_from_steam(steamid, name)
                    chars = 0
                    for char in full_name:
                        char_size = math.ceil(len(char.encode()) / 3)
                        chars += char_size

                        if char_size > 1 and chars > 20:
                            problematic = True

                        if chars >= 20:
                            break

            if problematic:
                playerids_problematic[steamid] = name
            else:
                playerids_normal[steamid] = name

        playerinfos = await asyncio.gather(*[self.exec_command('playerinfo %s' % playerid, can_fail=True) for playerid in playerids_normal.values()])
        for playerinfo in playerinfos:
            if not playerinfo:
                # The command (most likely) failed
                continue

            raw = dict()
            data = dict(
                team=None,
                unit=None,
                loadout=None
            )

            # Unpack response into a dict
            for line in playerinfo.strip('\n').split("\n"):
                if ": " not in line:
                    self.logger.warning("Invalid info line: %s", line)
                    continue
                key, val = line.split(": ", 1)
                raw[key.lower()] = val if val != "None" or key == "Name" else None
            
            """
            Name: T17 Scott
            steamID64: 01234567890123456
            Team: Allies            # "None" when not in team
            Role: Officer           
            Unit: 0 - Able          # Absent when not in unit
            Loadout: NCO            # Absent when not in team
            Kills: 0 - Deaths: 0
            Score: C 50, O 0, D 40, S 10
            Level: 34
            """

            try:
                name = data["name"] = raw["name"]
                steamid = data["steamid"] = raw["steamid64"]
                data["team"] = None
                data["squad"] = None
                data["role"] = raw.get("role", None)
                data["loadout"] = raw.get("loadout", None)

                team = raw.get("team")
                if team:
                    team_id = 1 if team == "Allies" else 2
                    data["team"] = Link("teams", {'id': team_id})
                
                    squad = raw.get("unit")
                    if squad:
                        squad_id, squad_name = squad.split(' - ', 1)
                        squad_id = int(squad_id)
                        data['squad'] = Link("squads", {'id': squad_id, 'team': {'id': team_id}})
                        
                        if team_id == 1:
                            squads_allies[squad_id] = squad_name
                        else:
                            squads_axis[squad_id] = squad_name
                
                data["kills"], data["deaths"] = raw.get("kills").split(' - Deaths: ') if raw.get("kills") else (0, 0)
                data["level"] = raw.get("level", None)

                scores = dict([score.split(" ", 1) for score in raw.get("score", "C 0, O 0, D 0, S 0").split(", ")])
                map_score = {"C": "combat", "O": "offense", "D": "defense", "S": "support"}
                data["score"] = {v: scores.get(k, 0) for k, v in map_score.items()}
                data["score"]["hopper"] = self._info

                players.append(data)
            except:
                self.logger.error("Couldn't unpack player data: %s", raw)
                raise

        for steamid, name in playerids_problematic.items():
            data = dict(
                name=name,
                steamid=steamid,
                is_incompatible_name=True
            )
            players.append(data)

        squads = list()
        # Compile teams and squads based off of the player info we have
        for i, squadids in enumerate([squads_allies, squads_axis]):
            team_id = i + 1
            for squad_id, squad_name in squadids.items():
                squads.append(dict(
                    id=squad_id,
                    name=squad_name,
                    team=Link("teams", {'id': team_id}),
                    players=Link("players", {'squad': {'id': squad_id}, 'team': {'id': team_id}}, multiple=True)
                ))

        """
        Players: Allied: 0 - Axis: 1
        Score: Allied: 2 - Axis: 2
        Remaining Time: 0:11:51
        Map: foy_warfare
        Next Map: stmariedumont_warfare
        """
        gamestate_data = dict(zip(
            ["team1_score", "team2_score", "time_h", "time_m", "time_s", "map", "next_map"],
            re.match(
                r"Players: Allied: \d+ - Axis: \d+\nScore: Allied: (\d+) - Axis: (\d+)\nRemaining Time: (\d+):(\d+):(\d+)\nMap: (.*)\nNext Map: (.*)",
                gamestate
            ).groups()
        ))

        return dict(
            # rotation=rotation,
            players=players,
            squads=squads,
            **gamestate_data
        )
    
    @ttl_cache(1, 10) # 10 seconds
    async def __fetch_bans(self):
        tempbans, permabans = await asyncio.gather(
            self.exec_command('get tempbans', unpack_array=True),
            self.exec_command('get permabans', unpack_array=True)
        )
        templogs = {ban.split(' : ', 1)[0]: ban for ban in tempbans}
        permalogs = {ban.split(' : ', 1)[0]: ban for ban in permabans}
        return templogs, permalogs
        
    @ttl_cache(1, 60*11) # 11 minutes
    async def __fetch_player_roles(self):
        # Not used: 'tempbans', 'permabans', 'admingroups', 'adminids'
        data = await self.exec_command('get vipids', unpack_array=True, multipart=True)
        self._vips = [entry.split(' ', 1)[0] for entry in data if entry]

    def __parse_logs(self, logs: str):
        if logs != 'EMPTY':
            logs = re.split(r"^\[.+? \((\d+)\)\] ", logs, flags=re.M)
            logs = zip(logs[1::2], logs[2::2])
            skip = True
            time = None

            for timestamp, log in logs:
                """
                [10:00:00 hours (1639106251)] CONNECTED A Player Name (12345678901234567)
                [10:00:00 hours (1639122640)] DISCONNECTED A Player Name (12345678901234567)
                [10:00:00 hours (1639143555)] KILL: A Player Name(Axis/12345678901234567) -> (WTH) A Player name(Allies/12345678901234567) with MP40
                [10:00:00 hours (1639144073)] TEAM KILL: A Player Name(Allies/12345678901234567) -> A Player Name(Allies/12345678901234567) with M1 GARAND
                [30:00 min (1639144118)] CHAT[Team][A Player Name(Allies/12345678901234567)]: Please build garrisons!
                [30:00 min (1639145775)] CHAT[Unit][A Player Name(Axis/12345678901234567)]: comms working?
                [15.03 sec (1639148961)] Player [A Player Name (12345678901234567)] Entered Admin Camera
                [15.03 sec (1639148961)] Player [A Player Name (12345678901234567)] Left Admin Camera
                [15.03 sec (1639148961)] BAN: [A Player Name] has been banned. [BANNED FOR 2 HOURS BY THE ADMINISTRATOR!]
                [15.03 sec (1639148961)] KICK: [A Player Name] has been kicked. [BANNED FOR 2 HOURS BY THE ADMINISTRATOR!]
                [15.03 sec (1639148961)] MESSAGE: player [A Player Name(12345678901234567)], content [Stop teamkilling, you donkey!]
                [805 ms (1639148969)] MATCH START SAINTE-MÈRE-ÉGLISE WARFARE
                [805 ms (1639148969)] MATCH ENDED `SAINTE-MÈRE-ÉGLISE WARFARE` ALLIED (2 - 3) AXIS 
                """
                try:
                    timestamp = int(timestamp)
                    time = datetime.fromtimestamp(timestamp).astimezone(timezone.utc)
                    log = log.rstrip('\n')

                    if skip:
                        # Avoid duplicates
                        if self._logs_seen_time > time:
                            continue
                        elif self._logs_seen_time == time:
                            if self._logs_last_recorded == log:
                                skip = False
                            continue
                    skip = False

                    if log.startswith('KILL') or log.startswith('TEAM KILL'):
                        p1_name, p1_team, p1_steamid, p2_name, p2_team, p2_steamid, weapon = re.search(
                            r"KILL: (.+)\((Allies|Axis)\/(\d{17}|[\da-f-]{36})\) -> (.+)\((Allies|Axis)\/(\d{17}|[\da-f-]{36})\) with (.+)", log).groups()
                        e_cls = PlayerTeamkillEvent if log.startswith('TEAM KILL') else PlayerKillEvent
                        self._info.events.add(e_cls(self._info,
                            event_time=time,
                            player=Link('players', {'steamid': p1_steamid}),
                            other=Link('players', {'steamid': p2_steamid}),
                            weapon=weapon
                        ))

                        # Count the amount of deaths of a player
                        player = self._info.find_players(single=True, steamid=p2_steamid)
                        if player:
                            deaths = self._player_deaths.setdefault(player, 0)
                            self._player_deaths[player] = deaths + 1
                            # self.logger.info('{: <25} {} -> {}'.format(player.name, deaths, deaths + 1))
                        else:
                            self.logger.warning('Could not find player %s %s', p2_steamid, p2_name)

                    elif log.startswith('CHAT'):
                        channel, name, team, steamid, message = re.match(r"CHAT\[(Team|Unit)\]\[(.+)\((Allies|Axis)\/(\d{17}|[\da-f-]{36})\)\]: (.+)", log).groups()
                        player = self._info.find_players(single=True, steamid=steamid)
                        self._info.events.add(PlayerMessageEvent(self._info,
                            event_time=time,
                            player=player.create_link(),
                            message=message,
                            channel=player.team.create_link() if channel == 'Team' else player.squad.create_link()
                        ))

                    elif log.startswith('Player'):
                        name, steamid, action = re.match(r"Player \[(.+) \((\d{17}|[\da-f-]{36})\)\] (Left|Entered) Admin Camera", log).groups()
                        player = Link('players', {'steamid': steamid})
                        if action == "Entered":
                            self._info.events.add(PlayerEnterAdminCamEvent(self._info, event_time=time, player=player))
                        elif action == "Left":
                            self._info.events.add(PlayerExitAdminCamEvent(self._info, event_time=time, player=player))

                    elif log.startswith('MATCH START'):
                        map_name = log[12:].strip()
                        self._info.events.add(
                            ServerMatchStartedEvent(self._info, event_time=time, map=map_name)
                        )
                        self._state = "warmup"
                        if isinstance(self._end_warmup_handle, asyncio.TimerHandle):
                            self._end_warmup_handle.cancel()
                        self._end_warmup_handle = self.loop.call_later(180, self.__enter_playing_state)

                    elif log.startswith('MATCH ENDED'):
                        map_name, score = re.match(r'MATCH ENDED `(.+)` ALLIED \((.+)\) AXIS', log).groups()
                        self._info.events.add(
                            ServerMatchEndedEvent(self._info, event_time=time, map=map_name, score=score)
                        )
                        self._state = "end_of_round"

                        # Cancel the timer responsible for triggering the Warmup Ended event
                        if isinstance(self._end_warmup_handle, asyncio.TimerHandle):
                            self._end_warmup_handle.cancel()
                        self._end_warmup_handle = None

                        # Log the scores of all online players
                        for player in self._info.players:
                            if player.has('score'):
                                self._info.events.add(
                                    PlayerScoreUpdateEvent(self._info, event_time=time, player=player.create_link())
                                )

                    elif log.split(' ', 1)[0] in {'CONNECTED', 'DISCONNECTED', 'TEAMSWITCH', 'KICK:', 'BAN:', 'VOTESYS:', 'MESSAGE:'}:
                        # Suppress error logs
                        pass

                except:
                    self.logger.exception("Failed to parse log line: [... (%s)] %s", timestamp, log)

            if time:
                self._logs_seen_time = time
                self._logs_last_recorded = log


        # -- Warmup ended events
        if self._end_warmup_handle is True:
            self._info.events.add(
                ServerWarmupEndedEvent(self._info, event_time=self._logs_seen_time)
            )
            self._state = "in_progress"
            self._end_warmup_handle = None


        # -- Player suicide events
        for player in self._info.players:
            if not player.has('deaths'):
                continue

            # By comparing the player's deaths as per the playerinfo response with the
            # amount of kill logs we received, we can track player suicides. This is
            # slightly easier said than done however, as we need to account for a slight
            # delay between the playerinfo response updating and receiving the kill log.

            # The number of deaths expected as per the kill logs
            expected_deaths = self._player_deaths.get(player)

            if player not in self._player_suicide_handles:
            
                if (expected_deaths is not None) and (player.deaths - expected_deaths == 1):
                    # The player may have redeployed. Let's wait a bit and check again.
                    handle = self.loop.call_later(7.0, self.__check_player_suicide, player)
                    self._player_suicide_handles[player] = handle

                else:
                    # Everything looks fine.
                    if (expected_deaths is not None) and (player.deaths != 0) and (player.deaths != expected_deaths):
                        # Okay, maybe not entirely.
                        self.logger.warning('Mismatch for %s: Has %s but expected %s', player.name, player.deaths, expected_deaths)
                    # Update our expected value
                    self._player_deaths[player] = player.deaths

        # Remove any expected values for players that have gone offline. This is important to
        # prevent memory usage from building up.
        self._player_deaths = {p: v for p, v in self._player_deaths.items()
                                if (p in self._info.players) or (p in self._player_suicide_handles)}

        for player in self._player_suicide_queue:
            self._info.events.add(
                PlayerSuicideEvent(self._info, event_time=self._logs_seen_time, player=player.create_link(with_fallback=True))
            )
        self._player_suicide_queue.clear()
        
    def __enter_playing_state(self):
        self._end_warmup_handle = True
    
    def __check_player_suicide(self, player: Player):
        try:
            expected_deaths = self._player_deaths.get(player)
            if expected_deaths is None:
                self.logger.warning('Expected death amount of player %s is unknown', player.name)
            elif (player.deaths - expected_deaths) == 1:
                self._player_suicide_queue.add(player)
            else:
                pass
        finally:
            self._player_suicide_handles.pop(player, None)
            self._player_deaths[player] = player.deaths
            
                            

    async def kick_player(self, player: Player, reason: str = ""):
        await self.exec_command(f'kick "{player.name}" "{reason}"')

    async def ban_player(self, player: Player, time: Union[None, timedelta, datetime] = None, reason: str = ""):
        time = to_timedelta(time)
        if time:
            hours = int(time.total_seconds() / (60*60))
            if not hours: hours = 1
            await self.exec_command(f'tempban {player.steamid} {hours} "{reason}" "HLU"')
        else:
            await self.exec_command(f'permaban {player.steamid} "{reason}" "HLU"')

    async def unban_player(self, steamid: str):
        temps, perms = await self.__fetch_bans()

        temp_ban_log = temps.get(steamid)
        perm_ban_log = perms.get(steamid)
        if temp_ban_log:
            await self.exec_command(f'pardontempban {steamid}')
        elif perm_ban_log:
            await self.exec_command(f'pardonpermaban {steamid}')
        else:
            # Just try to remove a temp ban and pray it works
            await self.exec_command(f'pardontempban {steamid}')
    
    async def kill_player(self, player: Player, reason: str = "") -> bool:
        return await self.exec_command(f'punish "{player.name}" "{reason}"', can_fail=True)
 
    async def move_player_to_team(self, player: Player, reason: str = ""):
        if reason:
            await self.exec_command(f'punish "{player.name}" {reason}', can_fail=True)
        await self.exec_command(f'switchteamnow {player.name}')
    
    async def send_broadcast_message(self, message: str):
        await self.exec_command(f'broadcast {message}')
    
    async def send_direct_message(self, message: str, target: Union[Player, Squad, Team, None]):
        players = target_to_players(target)
        if players is None:
            players = self.info.players

        if len(players) == 1:
            player = players[0]
            await self.exec_command(f'message "{player.steamid}" {message}')
        elif len(players) > 1:
            await asyncio.gather(*[
                self.exec_command(f'message "{player.steamid}" {message}')
                for player in players
            ], return_exceptions=True)
    
    async def add_map_to_rotation(self, map: str):
        await self.exec_command(f'rotadd {map}')
    
    async def remove_map_from_rotation(self, map: str):
        await self.exec_command(f'rotdel {map}')
    
    async def set_map_rotation(self, maps: list):
        old = {map.lower() for map in self.info.server.settings.rotation}
        new = {str(map).lower() for map in maps}
        for map in new:
            if map not in old:
                await self.add_map_to_rotation(map)
        for map in old:
            if map not in new:
                await self.remove_map_from_rotation(map)
    
    async def change_map(self, map: str):
        await self.exec_command(f'map {map}')


    async def set_max_queue_size(self, amount: int):
        await self.exec_command(f'setmaxqueuedplayers {amount}')
    
    async def set_num_vip_slots(self, amount: int):
        await self.exec_command(f'setnumvipslots {amount}')
    
    async def set_server_description(self, message: str):
        await self.exec_command(f'say {message}')
    
    async def set_idle_kick_time(self, time: Union[None, timedelta]):
        time = int(to_timedelta(time).total_seconds() / 60)
        await self.exec_command(f'setkickidletime {time}')

    async def set_latency_kick_threshold(self, threshold: int):
        await self.exec_command(f'setmaxping {threshold}')

    async def set_max_team_imbalance(self, threshold: int):
        if threshold is not None and int(threshold) >= 0:
            if not self.info.server.settings.auto_balance_enabled:
                await self.exec_command(f'setautobalanceenabled on')
            await self.exec_command(f'setautobalancethreshold {threshold}')
        else:
            await self.exec_command(f'setautobalanceenabled off')
   
    async def set_team_switch_cooldown(self, time: Union[None, timedelta]):
        time = int(to_timedelta(time).total_seconds() / 60)
        await self.exec_command(f'setteamswitchcooldown {time}')

    async def set_vote_kick_enabled(self, bool_: bool):
        await self.exec_command(f'setvotekickenabled {"on" if bool_ else "off"}')

    async def set_chat_filter(self, words: Sequence):
        words = set(word.lower() for word in words)
        current = self.info.server.settings.chat_filter
        to_ban = words - current
        to_unban = current - words
        await self.exec_command(f'banprofanity {",".join(to_ban)}')
        await self.exec_command(f'unbanprofanity {",".join(to_unban)}')


    async def add_vip(self, player: Player):
        await self.exec_command(f'vipadd {player.steamid} {player.name}')
    
    async def add_permissions(self, player: Player, *permissions: str):
        for perm in permissions:
            await self.exec_command(f'adminadd {player.steamid} {perm} {player.name}')

    async def revoke_vip(self, player: Player):
        await self.exec_command(f'vipdel {player.steamid}')
    
    async def revoke_permissions(self, player: Player, *permissions: str):
        await self.exec_command(f'admindel {player.steamid}')


class HLLRconWorker:
    def __init__(self, parent: 'HLLRcon', name: str):
        self.parent = parent
        self.name = name
        self.task = None
        self.protocol: HLLRconProtocol = None
    
    @property
    def loop(self):
        return self.parent.loop
    @property
    def queue(self):
        return self.parent.queue
    @property
    def credentials(self):
        return self.parent.credentials
    @property
    def logger(self):
        return self.parent.logger

    async def start(self):
        await self._create_connection()
        self.task = self.loop.create_task(self._worker())
    
    async def stop(self):
        if self.task:
            self.task.cancel()
        if self.connected:
            self.protocol._transport.close()
            self.protocol._transport = None
        self.protocol = None
        self.task = None
    
    @property
    def connected(self):
        return bool(self.protocol and self.protocol._transport)

    async def reconnect(self):
        self.logger.warning("Reconnecting worker %s", self.name)
        if self.connected:
            self.protocol._transport.close()
        await self._create_connection()

    async def _create_connection(self):
        protocol = await create_plain_transport(
            host=self.credentials.address,
            port=self.credentials.port,
            password=self.credentials.password,
            loop=self.loop,
            logger=self.logger,
        )

        if self.protocol and self.protocol._transport:
            self.protocol._transport.close()
        self.protocol = protocol

    async def _worker(self):
        while True:
            fut, cmd, kwargs, atp = await self.queue.get()
            
            try:
                if not self.connected:
                    await self.reconnect()

                res = await self.protocol.execute(cmd, **kwargs)
                if not fut.done():
                    fut.set_result(res)
                
            except Exception as exc:
                if atp > 1:
                    self.logger.exception("Retrying \"%s\"", cmd)
                    cmd_pack = (fut, cmd, kwargs, atp-1)
                    self.queue.put_nowait(cmd_pack)
                else:
                    self.logger.exception("Failed execution of \"%s\"", cmd)
                    if not fut.done():
                        fut.set_exception(exc)
            
            self.queue.task_done()


async def create_plain_transport(host: str, port: int, password: str, loop: asyncio.AbstractEventLoop = None, logger = None):
    loop = loop or asyncio.get_event_loop()
    protocol_factory = lambda: HLLRconProtocol(loop=loop, timeout=10, logger=logger)

    try:
        _, protocol = await asyncio.wait_for(
            loop.create_connection(protocol_factory, host=host, port=port),
            timeout=15
        )
    except asyncio.TimeoutError:
        raise HLLConnectionError("Address %s could not be resolved" % host)
    except ConnectionRefusedError:
        raise HLLConnectionError("The server refused connection over port %s" % port)

    await protocol.authenticate(password)

    return protocol