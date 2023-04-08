from typing import Union

from lib.storage import cursor, database
from lib.exceptions import NotFound
from utils import ttl_cache

class ApiKeys:
    def __init__(self, id: Union[int, None], guild_id: int, tag: str, key: str):
        self.id = id
        self.guild_id = guild_id
        self.tag = tag
        self.key = key

    @classmethod
    def load_from_db(cls, id: int):
        cursor.execute('SELECT ROWID, guild_id, tag, `key` FROM hss_api_keys WHERE ROWID = ?', (id,))
        res = cursor.fetchone()

        if not res:
            raise NotFound(f"No API key exist with ID {id}")

        return cls(
            id=int(res[0]),
            guild_id=int(res[1]),
            tag=str(res[2]),
            key=str(res[3]),
        )

    @staticmethod
    def _create_in_db(guild_id: int, tag: str, key: str):
        cursor.execute('INSERT INTO hss_api_keys (guild_id, tag, `key`) VALUES (?,?,?)', (guild_id, tag, key))
        database.commit()
        return cursor.lastrowid

    @classmethod
    def create_in_db(cls, guild_id: int, tag: str, key: str):
        id_ = cls._create_in_db(guild_id, tag, key)
        return cls(
            id=id_,
            guild_id=guild_id,
            tag=tag,
            key=key,
        )

    @classmethod
    def in_guild(cls, guild_id: int):
        cursor.execute('SELECT ROWID, tag, `key` FROM hss_api_keys WHERE guild_id = ?', (guild_id,))
        return [cls(
            id=id,
            guild_id=guild_id,
            tag=tag,
            key=key,
        ) for (
            id, tag, key,
        ) in cursor.fetchall()]

    def __str__(self):
        return self.tag

    def insert_in_db(self):
        self.id = self._create_in_db(guild_id=self.guild_id,
                                     tag=self.tag,
                                     key=self.key,
                                     )

    def save(self):
        cursor.execute('UPDATE hss_api_keys SET tag = ?, key = ? WHERE ROWID = ?',
                       (self.tag, self.key, self.id))
        database.commit()

    def delete(self):
        cursor.execute('DELETE FROM hss_api_keys WHERE ROWID = ?', (self.id,))
        database.commit()
        self.id = None

@ttl_cache(size=15, seconds=15)
async def api_keys_in_guild_ttl(guild_id: int):
    return ApiKeys.in_guild(guild_id)
