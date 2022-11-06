import asyncio
from datetime import datetime, timedelta
from functools import wraps
import re

from typing import List, TYPE_CHECKING

from lib.protocol import HLLRconProtocol
from lib.exceptions import HLLConnectionError
from lib.info_types import *
from utils import to_timedelta, ttl_cache, get_config

if TYPE_CHECKING:
    from lib.session import HLLCaptureSession

NUM_WORKERS_PER_INSTANCE = get_config().getint('Session', 'NumRCONWorkers')

SQUAD_LEADER_ROLES = {"Officer", "TankCommander", "Spotter"}
TEAM_LEADER_ROLES = {"ArmyCommander"}

INFANTRY_ROLES = {"Officer", "Assault", "AutomaticRifleman", "Medic", "Support",
                  "HeavyMachineGunner", "AntiTank", "Engineer", "Rifleman"}
TANK_ROLES = {"TankCommander", "Crewman"}
RECON_ROLES = {"Spotter", "Sniper"}


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
            except:
                self.logger.exception('Failed to reconnect %r. Missed %s consecutive gathers.', self, self._missed_gathers + 1)

        if not self.connected:
            if self._missed_gathers < 20 or self._missed_gathers % 20 == 0:
                self.logger.info('Trying to reconnect %r', self)
                await reconnect()

        if self.connected:
            try:
                res = await asyncio.wait_for(func(self, *args, **kwargs), timeout=10)
            except:
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
            try:
                worker = HLLRconWorker(parent=self, name=f"Worker #{num}")
                await worker.start()
                self.logger.info('Started worker %s', worker.name)
            except:
                if i == 0:
                    raise
                else:
                    self.logger.exception('Failed to start worker #%s, skipping...', num)
            self.workers.append(worker)
        
        self._state = "in_progress"
        self._map = None
        self._end_warmup_handle = None
        self._logs_seen_time = datetime.now()
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
        self.info = InfoHopper()
        await self._fetch_server_info()
        return self.info


    async def _fetch_server_info(self):
        data = dict()
        res = await asyncio.gather(
            self.__fetch_persistent_server_info(),
            self.__fetch_server_settings(),
            self.__fetch_current_server_info(),
            self.__fetch_player_roles(),
            self.exec_command('showlog 1', multipart=True)
        )
        logs = res.pop(-1)
        for d in res:
            if isinstance(d, dict):
                data.update(d)

        map = data['map']
        if map == "Loading ''":
            map = self._map
        elif self._map and map != self._map:
            self.info.events.add(ServerMapChangedEvent(self.info, old=self._map.replace('_RESTART', ''), new=map.replace('_RESTART', '')))
        self.info.events.add(ServerMapChangedEvent)
        clean_map = map.replace('_RESTART', '')

        rotation = [m for m in data['rotation'] if m]
        
        server = Server(self.info,
            name = data['name'],
            map = clean_map,
            settings = ServerSettings(self.info,
                rotation = rotation,
                max_players = int(data['slots'].split('/')[0]),
                max_queue_length = int(data['maxqueuedplayers']),
                max_vip_slots = int(data['numvipslots']),
                idle_kick_time = timedelta(minutes=int(data['idletime'])),
                max_allowed_ping = int(data['highping']),
                team_switch_cooldown = timedelta(minutes=int(data['teamswitchcooldown'])),
                auto_balance = int(data['autobalancethreshold']) if data['autobalanceenabled'] == "on" else False,
                #vote_kick = timedelta(minutes=int(data['votekickthreshold'])) if data['votekickenabled'] == "on" else False,
                chat_filter = data['profanity']
            )
        )
        self.info.set_server(server)

        self.info.add_players(*[Player(self.info, is_vip=p["steamid"] in self._vips, **p)
                                for p in data['players']])
        self.info.add_squads(*[Squad(self.info, **sq) for sq in data['squads']])
        self.info.add_teams(
            Team(self.info, id=1, name="Allies", squads=Link('squads', {'team': {'id': 1}}, multiple=True), players=Link('players', {'team': {'id': 1}}, multiple=True)),
            Team(self.info, id=2, name="Axis",   squads=Link('squads', {'team': {'id': 2}}, multiple=True), players=Link('players', {'team': {'id': 2}}, multiple=True)),
        )

        if clean_map in rotation:
            next_i = rotation.index(clean_map) + 1
            next_map = rotation[next_i] if next_i < len(rotation) else rotation[0]
            self.info.server.next_map = next_map

        for squad in self.info.squads:
            players = squad.players
            
            leader = None
            for player in players:
                if player.role in SQUAD_LEADER_ROLES:
                    leader = player.create_link()
                    break
            squad.leader = leader

            type_ = "infantry"
            for player in players:
                if player.role in INFANTRY_ROLES:
                    type_ = "infantry"
                elif player.role in TANK_ROLES:
                    type_ = "tank"
                elif player.role in RECON_ROLES:
                    type_ = "recon"
                else:
                    continue
                break
            squad.type = type_
        
        for team in self.info.teams:
            players = team.players
            leader = None
            for player in players:
                if player.role in TEAM_LEADER_ROLES:
                    leader = player.create_link()
                    break
            team.leader = leader
        
        self.__parse_logs(logs)
        self.info.server.state = self._state
        self._map = map            
    
    async def exec_command(self, cmd, **kwargs) -> Union[str, list]:
        fut = self.loop.create_future()
        cmd_pack = (fut, cmd, kwargs)
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
        map, rotation, playerids = await asyncio.gather(
            self.exec_command("get map"),
            self.exec_command("rotlist"),
            self.exec_command("get players", unpack_array=True)
        )
        rotation = rotation.split('\n')

        players = list()
        squads_allies = dict()
        squads_axis = dict()

        playerinfos = await asyncio.gather(*[self.exec_command('playerinfo %s' % playerid, can_fail=True) for playerid in playerids])
        for num_info, playerinfo in enumerate(playerinfos):
            if not playerinfo:
                continue
            raw = dict()
            data = dict(
                team=None,
                unit=None,
                loadout=None
            )

            for line in playerinfo.strip('\n').split("\n"):
                if ": " not in line:
                    self.logger.warning("Invalid info line: %s", line)
                    continue
                key, val = line.split(": ", 1)
                raw[key.lower()] = val
            
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
                data["name"] = raw["name"]
                data["steamid"] = raw["steamid64"]

                if playerids[num_info] != data["name"]:
                    self.logger.error('Requested playerinfo for %s but got %s', playerids[num_info], data["name"])
                
                team = raw.get("team")
                team_id = 1 if team == "Allies" else 2
                if team:
                    data["team"] = Link("teams", {'id': team_id})
                    data["role"] = raw.get("role", None)
                    data["loadout"] = raw.get("loadout", None)
                else:
                    data["team"] = None
                    data["role"] = None
                    data["loadout"] = None
                
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
                data["score"]["hopper"] = self.info

                players.append(data)
            except:
                self.logger.error("Couldn't unpack player data: %s", raw)
                raise

        squads = list()
        for i, squadids in enumerate([squads_allies, squads_axis]):
            team_id = i + 1
            for squad_id, squad_name in squadids.items():
                squads.append(dict(
                    id=squad_id,
                    name=squad_name,
                    team=Link("teams", {'id': team_id}),
                    players=Link("players", {'squad': {'id': squad_id}, 'team': {'id': team_id}}, multiple=True)
                ))

        return dict(
            map=map,
            rotation=rotation,
            players=players,
            squads=squads
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
        data = await self.exec_command('get vipids', unpack_array=True)
        self._vips = [entry.split(' ', 1)[0] for entry in data if entry]

    def __parse_logs(self, logs: str):
        if logs != 'EMPTY':
            logs = logs.strip('\n').split('\n')
            time = None

            for line in logs:
                """
                [11:51:58 hours (1639106251)] CONNECTED (WTH) Duba
                [7:18:50 hours (1639122640)] DISCONNECTED Saunders University 
                [1:30:15 hours (1639143555)] KILL: I.N.D.I.G.O.(Axis/76561198018628685) -> (WTH) vendrup0105(Allies/76561199089119792) with MP40
                [1:21:37 hours (1639144073)] TEAM KILL: (WTH) Xcessive(Allies/76561198017923783) -> Sheer_Luck96(Allies/76561198180120693) with M1918A2_BAR
                [1:20:52 hours (1639144118)] CHAT[Team][jameswstubbs(Allies/76561198251795176)]: My comms have gone
                [53:15 min (1639145775)] CHAT[Unit][Schuby(Axis/76561198023348032)]: sec my voice com is dead
                [9.06 sec (1639148961)] Player [\u272a (WTH) Beard (76561197985434745)] Entered Admin Camera
                [805 ms (1639148969)] Player [\u272a (WTH) Beard (76561197985434745)] Left Admin Camera
                """
                if not line:
                    continue

                try:
                    time, log = re.match(r"\[.*?\((\d+)\)\] (.+)", line).groups()
                    time = datetime.fromtimestamp(int(time))
                    if time < self._logs_seen_time:
                        continue

                    if log.startswith('KILL') or log.startswith('TEAM KILL'):
                        p1_name, p1_team, p1_steamid, p2_name, p2_team, p2_steamid, weapon = re.search(
                            r"KILL: (.+)\((Allies|Axis)\/(\d{17})\) -> (.+)\((Allies|Axis)\/(\d{17})\) with (.+)", log).groups()
                        e_cls = PlayerTeamkillEvent if log.startswith('TEAM KILL') else PlayerKillEvent
                        self.info.events.add(e_cls(self.info,
                            event_time=time,
                            player=Link('players', {'steamid': p1_steamid}),
                            other=Link('players', {'steamid': p2_steamid}),
                            weapon=weapon
                        ))
                        player = self.info.find_players(single=True, steamid=p2_steamid)
                        if player:
                            deaths = self._player_deaths.setdefault(player, 0)
                            self._player_deaths[player] = deaths + 1
                            # self.logger.info('{: <25} {} -> {}'.format(player.name, deaths, deaths + 1))
                        else:
                            self.logger.warning('Could not find player %s %s', p2_steamid, p2_name)
                    elif log.startswith('CHAT'):
                        channel, name, team, steamid, message = re.match(r"CHAT\[(Team|Unit)\]\[(.+)\((Allies|Axis)\/(\d{17})\)\]: (.+)", log).groups()
                        player = self.info.find_players(single=True, steamid=steamid)
                        self.info.events.add(PlayerMessageEvent(self.info,
                            event_time=time,
                            player=player.create_link(),
                            message=message,
                            channel=player.team.create_link() if channel == 'Team' else player.squad.create_link()
                        ))
                    elif log.startswith('Player'):
                        name, steamid, action = re.match(r"Player \[(.+) \((\d{17})\)\] (Left|Entered) Admin Camera", log).groups()
                        player = Link('players', {'steamid': steamid})
                        if action == "Entered":
                            self.info.events.add(PlayerEnterAdminCamEvent(self.info, event_time=time, player=player))
                        elif action == "Left":
                            self.info.events.add(PlayerExitAdminCamEvent(self.info, event_time=time, player=player))
                    elif log.startswith('MATCH START'):
                        map_name = log[12:]
                        self.info.events.add(
                            ServerMatchStarted(self.info, event_time=time, map=map_name)
                        )
                        self._state = "warmup"
                        if isinstance(self._end_warmup_handle, asyncio.TimerHandle):
                            self._end_warmup_handle.cancel()
                        self._end_warmup_handle = self.loop.call_later(180, self.__enter_playing_state)
                    elif log.startswith('MATCH ENDED'):
                        map_name, score = re.match(r'MATCH ENDED `(.+)` ALLIED \((.+)\) AXIS', log).groups()
                        self.info.events.add(
                            ServerMatchEnded(self.info, event_time=time, map=map_name, score=score)
                        )
                        self._state = "end_of_round"
                        if isinstance(self._end_warmup_handle, asyncio.TimerHandle):
                            self._end_warmup_handle.cancel()
                        self._end_warmup_handle = None
                    elif log.split(' ', 1)[0] in {'CONNECTED', 'DISCONNECTED', 'TEAMSWITCH', 'KICK:', 'BAN:', 'VOTESYS:'}:
                        # Suppress error logs
                        pass
                except:
                    self.logger.exception("Failed to parse log line: %s", line)

            if time:
                self._logs_seen_time = time

        if self._end_warmup_handle is True:
            self.info.events.add(
                ServerWarmupEnded(self.info, event_time=self._logs_seen_time)
            )
            self._state = "in_progress"
            self._end_warmup_handle = None



        for player in self.info.players:
            expected_deaths = self._player_deaths.get(player)

            if player not in self._player_suicide_handles:
            
                if (expected_deaths is not None) and (player.deaths - expected_deaths == 1):
                    # self.logger.info('Scheduling for %s: %s - %s == 1', player.name, player.deaths, expected_deaths)
                    handle = self.loop.call_later(7.0, self.__check_player_suicide, player)
                    self._player_suicide_handles[player] = handle

                else:
                    if (expected_deaths is not None) and (player.deaths != 0) and (player.deaths != expected_deaths):
                        self.logger.warning('Mismatch for %s: Has %s but expected %s', player.name, player.deaths, expected_deaths)
                    self._player_deaths[player] = player.deaths

        # _player_deaths = dict()
        # for p, v in self._player_deaths.items():
        #     if (p in self.info.players) or (p in self._player_suicide_handles):
        #         _player_deaths[p] = v
        #     else:
        #         self.logger.info('Disposing %s', p.name)
        # self._player_deaths = _player_deaths
        self._player_deaths = {p: v for p, v in self._player_deaths.items() if (p in self.info.players) or (p in self._player_suicide_handles)}

        for player in self._player_suicide_queue:
            self.info.events.add(
                PlayerSuicideEvent(self.info, event_time=self._logs_seen_time, player=player.create_link(with_fallback=True))
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
                # self.logger.info("Expected %s deaths but observed %s, player %s must've killed themself", expected_deaths, player.deaths, player.name)
                self._player_suicide_queue.add(player)
            else:
                # self.logger.info('Successfully ended check for %s. Expected %s and got %s.', player.name, expected_deaths, player.deaths)
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
            await self.exec_command(f'tempban {player.steamid} {hours} "{reason}" "Gamewatch"')
        else:
            await self.exec_command(f'permaban {player.steamid} "{reason}" "Gamewatch"')

    async def unban_player(self, steamid: str):
        temps, perms = await self.__fetch_bans()

        ban_log = temps.get(steamid)
        if ban_log:
            await self.exec_command(f'pardontempban {ban_log}')

        ban_log = perms.get(steamid)
        if ban_log:
            await self.exec_command(f'pardonpermaban {ban_log}')
    
    async def kill_player(self, player: Player, reason: str = "") -> bool:
        return await self.exec_command(f'punish "{player.name}" "{reason}"', can_fail=True)
 
    async def move_player_to_team(self, player: Player, reason: str = ""):
        if reason:
            await self.exec_command(f'punish "{player.name}" {reason}', can_fail=True)
        await self.exec_command(f'switchteamnow {player.name}')
    
    async def send_broadcast_message(self, message: str):
        await self.exec_command(f'broadcast {message}')
    
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
        self.task.cancel()
        if self.protocol._transport:
            self.protocol._transport.close()
        self.protocol = None
        self.task = None
    
    @property
    def connected(self):
        return bool(self.protocol and self.protocol._transport)

    async def _create_connection(self):
        protocol = await create_plain_transport(
            host=self.credentials.address,
            port=self.credentials.port,
            password=self.credentials.password,
            loop=self.loop,
            logger=self.logger,
        )

        if self.protocol:
            self.protocol._transport.close()
        self.protocol = protocol

    async def _worker(self):
        while True:
            fut, cmd, kwargs = await self.queue.get()
            try:
                res = await self.protocol.execute(cmd, **kwargs)
                fut.set_result(res)
            except Exception as exc:
                if not fut.done():
                    fut.set_exception(exc)
            self.queue.task_done()


async def create_plain_transport(host: str, port: int, password: str, loop: asyncio.AbstractEventLoop = None, logger = None):
    loop = loop or asyncio.get_event_loop()
    protocol_factory = lambda: HLLRconProtocol(loop=loop, timeout=10, logger=logger)

    try:
        _, protocol = await asyncio.wait_for(
            loop.create_connection(protocol_factory, host=host, port=port),
            timeout=3
        )
    except asyncio.TimeoutError:
        raise HLLConnectionError("Address %s could not be resolved" % host)
    except ConnectionRefusedError:
        raise HLLConnectionError("The server refused connection over port %s" % port)

    await protocol.authenticate(password)

    return protocol