from typing import Union

from lib.storage import cursor, database
from lib.exceptions import NotFound
from utils import ttl_cache

class Credentials:
    def __init__(self, id: Union[int, None], guild_id: int, name: str, address: str, port: int, password: str):
        self.id = id
        self.guild_id = guild_id
        self.name = name
        self.address = address
        self.port = port
        self.password = password
    
    @classmethod
    def load_from_db(cls, id: int):
        cursor.execute('SELECT ROWID, guild_id, name, address, port, password FROM credentials WHERE ROWID = ?', (id,))
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
        )
    
    @classmethod
    def create_in_db(cls, guild_id: int, name: str, address: str, port: int, password: str):
        cursor.execute('INSERT INTO credentials (guild_id, name, address, port, password) VALUES (?,?,?,?,?)', (guild_id, name, address, port, password))
        database.commit()

        return cls(
            id=cursor.lastrowid,
            guild_id=guild_id,
            name=name,
            address=address,
            port=port,
            password=password,
        )

    @classmethod
    def create_temporary(cls, guild_id: int, name: str, address: str, port: int, password: str):
        return cls(
            id=None,
            guild_id=guild_id,
            name=name,
            address=address,
            port=port,
            password=password,
        )

    @classmethod
    def in_guild(cls, guild_id: int):
        cursor.execute('SELECT ROWID, name, address, port, password FROM credentials WHERE guild_id = ?', (guild_id,))
        return [cls(
            id=id,
            guild_id=guild_id,
            name=name,
            address=address,
            port=port,
            password=password,
        ) for (
            id, name, address, port, password
        ) in cursor.fetchall()]

    def save(self):
        cursor.execute('UPDATE credentials SET name = ?, address = ?, port = ?, password = ? WHERE ROWID = ?',
            (self.name, self.address, self.port, self.password, self.id))
        database.commit()
        

@ttl_cache(size=15, seconds=15)
async def credentials_in_guild_tll(guild_id: int):
    return Credentials.in_guild(guild_id)
