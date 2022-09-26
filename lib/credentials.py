from typing import Union

from lib.storage import cursor, database
from lib.exceptions import NotFound
from utils import ttl_cache

cursor.execute("""
CREATE TABLE IF NOT EXISTS "credentials" (
	"guild_id"	VARCHAR(18) NOT NULL,
	"name"	VARCHAR(80) NOT NULL,
	"address"	VARCHAR(25),
	"port"	INTEGER,
	"password"	VARCHAR(50)
);""")
database.commit()

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
    
    @staticmethod
    def _create_in_db(guild_id: int, name: str, address: str, port: int, password: str):
        cursor.execute('INSERT INTO credentials (guild_id, name, address, port, password) VALUES (?,?,?,?,?)', (guild_id, name, address, port, password))
        database.commit()
        return cursor.lastrowid

    @classmethod
    def create_in_db(cls, guild_id: int, name: str, address: str, port: int, password: str):
        id_ = cls._create_in_db(guild_id, name, address, port, password)
        return cls(
            id=id_,
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
            password=self.password
        )

    def save(self):
        cursor.execute('UPDATE credentials SET name = ?, address = ?, port = ?, password = ? WHERE ROWID = ?',
            (self.name, self.address, self.port, self.password, self.id))
        database.commit()

@ttl_cache(size=15, seconds=15)
async def credentials_in_guild_tll(guild_id: int):
    return Credentials.in_guild(guild_id)
