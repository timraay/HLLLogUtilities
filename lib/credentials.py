from typing import Union

from lib.storage import cursor, database
from lib.exceptions import NotFound
from lib.modifiers import ModifierFlags
from utils import ttl_cache

class Credentials:
    def __init__(self, id: Union[int, None], guild_id: int, name: str, address: str, port: int, password: str, default_modifiers: ModifierFlags = None):
        self.id = id
        self.guild_id = guild_id
        self.name = name
        self.address = address
        self.port = port
        self.password = password
        self.default_modifiers = default_modifiers or ModifierFlags()
    
    @classmethod
    def load_from_db(cls, id: int):
        cursor.execute('SELECT ROWID, guild_id, name, address, port, password, default_modifiers FROM credentials WHERE ROWID = ?', (id,))
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
        return [cls(
            id=id,
            guild_id=guild_id,
            name=name,
            address=address,
            port=port,
            password=password,
            default_modifiers=ModifierFlags(default_modifiers),
        ) for (
            id, name, address, port, password, default_modifiers
        ) in cursor.fetchall()]
    
    @property
    def temporary(self):
        return not bool(self.id)

    def __str__(self):
        return f"{self.name} - {self.address}:{self.port}"

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
        cursor.execute('UPDATE credentials SET name = ?, address = ?, port = ?, password = ?, default_modifiers = ? WHERE ROWID = ?',
            (self.name, self.address, self.port, self.password, self.default_modifiers.value, self.id))
        database.commit()
    
    def delete(self):
        if self.temporary:
            raise TypeError('These credentials are already unsaved')
        
        cursor.execute('DELETE FROM credentials WHERE ROWID = ?', (self.id,))
        database.commit()
        self.id = None

@ttl_cache(size=15, seconds=15)
async def credentials_in_guild_tll(guild_id: int):
    return Credentials.in_guild(guild_id)
