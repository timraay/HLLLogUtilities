from typing import Union, Dict

from lib.storage import cursor, database
from lib.exceptions import NotFound, TemporaryCredentialsError, CredentialsAlreadyCreatedError
from lib.modifiers import ModifierFlags
from lib.autosession import AutoSessionManager
from utils import ttl_cache

CREDENTIALS: Dict[int, 'Credentials'] = dict()

class Credentials:
    def __init__(self, id: Union[int, None], guild_id: int, name: str, address: str, port: int,
            password: str, default_modifiers: ModifierFlags = None, autosession_enabled: bool = False):
        self.id = id
        self.guild_id = guild_id
        self.name = name
        self.address = address
        self.port = port
        self.password = password
        self.default_modifiers = default_modifiers or ModifierFlags()

        if autosession_enabled and self.temporary:
            raise TemporaryCredentialsError("Credentials must not be temporary for AutoSession to be enabled")
        
        if self.id in CREDENTIALS:
            raise CredentialsAlreadyCreatedError("Credentials with ID %s were already loaded")

        if self.temporary:
            self.autosession = None
        else:
            self.autosession = AutoSessionManager(self, autosession_enabled)
        
        CREDENTIALS[self.id] = self

    @classmethod
    def get(cls, id: int):
        if id in CREDENTIALS:
            return CREDENTIALS[id]
        else:
            return cls.load_from_db(id)

    @classmethod
    def load_from_db(cls, id: int):
        cursor.execute('SELECT ROWID, guild_id, name, address, port, password, default_modifiers, autosession_enabled FROM credentials WHERE ROWID = ?', (id,))
        res = cursor.fetchone()

        if not res:
            raise NotFound(f"No credentials exist with ID {id}")

        return cls(
            id=int(res[0]),
            guild_id=int(res[1]),
            name=str(res[2]),
            address=str(res[3]),
            port=int(res[4]),
            password=str(res[5]),
            default_modifiers=ModifierFlags(int(res[6])),
            autosession_enabled=bool(res[7]),
        )
    
    @staticmethod
    def _create_in_db(guild_id: int, name: str, address: str, port: int, password: str, default_modifiers: ModifierFlags = ModifierFlags()):
        cursor.execute('INSERT INTO credentials (guild_id, name, address, port, password, default_modifiers) VALUES (?,?,?,?,?,?)',
            (guild_id, name, address, port, password, default_modifiers.value))
        database.commit()
        return cursor.lastrowid

    @classmethod
    def create_in_db(cls, guild_id: int, name: str, address: str, port: int, password: str, default_modifiers: ModifierFlags = None):
        if default_modifiers:
            default_modifiers = default_modifiers.copy()
        else:
            default_modifiers = ModifierFlags()

        id_ = cls._create_in_db(guild_id, name, address, port, password, default_modifiers)
        return cls(
            id=id_,
            guild_id=guild_id,
            name=name,
            address=address,
            port=port,
            password=password,
            default_modifiers=default_modifiers,
        )

    @classmethod
    def create_temporary(cls, guild_id: int, name: str, address: str, port: int, password: str, default_modifiers: ModifierFlags = None):
        if default_modifiers:
            default_modifiers = default_modifiers.copy()
        else:
            default_modifiers = ModifierFlags()
        
        return cls(
            id=None,
            guild_id=guild_id,
            name=name,
            address=address,
            port=port,
            password=password,
            default_modifiers=default_modifiers,
        )

    @classmethod
    def in_guild(cls, guild_id: int):
        cursor.execute('SELECT ROWID, name, address, port, password, default_modifiers FROM credentials WHERE guild_id = ?', (guild_id,))
        for (id, name, address, port, password, default_modifiers) in cursor.fetchall():
            id = int(id)
            if id in CREDENTIALS:
                yield cls.get(id)
            else:
                yield cls(
                    id=id,
                    guild_id=int(guild_id),
                    name=str(name),
                    address=str(address),
                    port=int(port),
                    password=str(password),
                    default_modifiers=ModifierFlags(default_modifiers),
                )
    
    @property
    def temporary(self):
        return not bool(self.id)

    @property
    def autosession_enabled(self):
        return bool(self.autosession and self.autosession.enabled)

    def __str__(self):
        return f"[#{self.id}] {self.name} - {self.address}:{self.port}"

    def __eq__(self, other):
        if isinstance(other, Credentials) and not self.temporary:
            return self.id == other.id
        return False
    
    def insert_in_db(self):
        if not self.temporary:
            raise TypeError('These credentials are already in the database')
        
        self.id = self._create_in_db(guild_id=self.guild_id,
            name=self.name,
            address=self.address,
            port=self.port,
            password=self.password,
            default_modifiers=self.default_modifiers,
        )

    def save(self):
        cursor.execute('UPDATE credentials SET name = ?, address = ?, port = ?, password = ?, default_modifiers = ?, autosession_enabled = ? WHERE ROWID = ?',
            (self.name, self.address, self.port, self.password, self.default_modifiers.value, self.autosession_enabled, self.id))
        database.commit()
    
    async def delete(self):
        if self.temporary:
            raise TypeError('These credentials are already unsaved')
        
        if self.autosession:
            await self.autosession.disable()
        
        cursor.execute('DELETE FROM credentials WHERE ROWID = ?', (self.id,))
        database.commit()
        self.id = None
        
        del CREDENTIALS[self.id]

@ttl_cache(size=15, seconds=15)
async def credentials_in_guild_tll(guild_id: int):
    return list(Credentials.in_guild(guild_id))
