import pydantic

from typing import Union, Optional

from lib.storage import cursor, database
from lib.exceptions import NotFound
from utils import ttl_cache

class HSSApiKey:
    def __init__(self, id: Union[int, None], guild_id: int, team: 'HSSTeam', key: str):
        self.id = id
        self.guild_id = guild_id
        self.team = team
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
            team=HSSTeam(tag=res[2]),
            key=str(res[3]),
        )

    @staticmethod
    def _create_in_db(guild_id: int, tag: str, key: str):
        cursor.execute('INSERT INTO hss_api_keys (guild_id, tag, `key`) VALUES (?,?,?)', (guild_id, tag, key))
        database.commit()
        return cursor.lastrowid

    @classmethod
    def create_in_db(cls, guild_id: int, team: 'HSSTeam', key: str):
        id_ = cls._create_in_db(guild_id, team.tag, key)
        return cls(
            id=id_,
            guild_id=guild_id,
            team=team,
            key=key,
        )

    @classmethod
    def create_temporary(cls, guild_id: int, team: 'HSSTeam', key: str):
        return cls(
            id=None,
            guild_id=guild_id,
            team=team,
            key=key,
        )

    @classmethod
    def in_guild(cls, guild_id: int):
        cursor.execute('SELECT ROWID, tag, `key` FROM hss_api_keys WHERE guild_id = ?', (guild_id,))
        return [cls(
            id=id,
            guild_id=guild_id,
            team=HSSTeam(tag=tag),
            key=key,
        ) for (
            id, tag, key,
        ) in cursor.fetchall()]

    @property
    def temporary(self):
        return not bool(self.id)

    @property
    def tag(self):
        return self.team.tag

    def __str__(self):
        return self.team.tag

    def __eq__(self, other):
        if isinstance(other, HSSApiKey) and not self.temporary:
            return self.id == other.id
        return False
    
    def insert_in_db(self):
        if not self.temporary:
            raise TypeError('This API key is already in the database')
        self.id = self._create_in_db(
            guild_id=self.guild_id,
            tag=self.team.tag,
            key=self.key,
        )

    def save(self):
        cursor.execute('UPDATE hss_api_keys SET tag = ?, key = ? WHERE ROWID = ?',
                       (self.team.tag, self.key, self.id))
        database.commit()

    def delete(self):
        if self.temporary:
            raise TypeError('This API key is already unsaved')
        cursor.execute('DELETE FROM hss_api_keys WHERE ROWID = ?', (self.id,))
        database.commit()
        self.id = None

class HSSTeam(pydantic.BaseModel):
    tag: str
    name: Optional[str]

    def __str__(self):
        if self.name:
            return f"{self.tag} ({self.name})"
        else:
            return self.tag
    
    def __eq__(self, other):
        if isinstance(other, HSSTeam):
            return self.tag == other.tag
        elif isinstance(other, str):
            return self.tag == other
        return False

@ttl_cache(size=15, seconds=15)
async def api_keys_in_guild_ttl(guild_id: int):
    return HSSApiKey.in_guild(guild_id)
