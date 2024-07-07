import http
import json
import discord
from io import StringIO
from functools import wraps
from typing import List

import aiohttp
from aiohttp import FormData

from lib.hss.api_key import HSSApiKey, HSSTeam
from lib.exceptions import HTTPException, HSSConnectionError

def retry_then_raise(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        err = None
        for _ in range(2):
            try:
                return await func(*args, **kwargs)
            except aiohttp.ClientError as exc:
                err = HSSConnectionError(exc)
            except Exception as exc:
                err = exc
        raise err
    return wrapper


class HSSApi:
    def __init__(self, api_url: str):
        self.api_url = api_url

    @retry_then_raise
    async def submit_match(self, api_key: HSSApiKey, opponent: HSSTeam, won: bool, kind: str, submitting_user: discord.User, csv_export: StringIO) -> str:
        teams = [api_key.tag, opponent.tag]
        if not won:
            teams.reverse()
        
        data = FormData()
        data.add_field("data", json.dumps({
            'teams': teams,
            'kind': kind,
        }))
        data.add_field("username", str(submitting_user))
        data.add_field("file", csv_export, filename="export.csv")
        async with aiohttp.ClientSession() as sess:
            async with sess.post('{0}/matches/serverlog'.format(self.api_url), data=data,
                                 headers={'Authorization': f'Bearer {api_key.key}'}) as resp:
                body = await resp.json()

                if resp.status == http.HTTPStatus.CREATED.value:
                    return body.get('match_id')
                if resp.status == http.HTTPStatus.FORBIDDEN or resp.status == http.HTTPStatus.BAD_REQUEST:
                    raise HTTPException(resp.status, body.get('error'))
                if resp.status == http.HTTPStatus.UNAUTHORIZED:
                    raise HTTPException(resp.status,
                        'You do not have a valid authorization for either the winning or opposing team.')
                raise HTTPException(resp.status, 'An unknown error occurred submitting your match. Error: ' + body.get('error'))

    @retry_then_raise
    async def teams(self) -> List[HSSTeam]:
        async with aiohttp.ClientSession() as sess:
            async with sess.get('{0}/teams'.format(self.api_url)) as resp:
                if resp.status != http.HTTPStatus.OK:
                    raise HTTPException(resp.status, 'Could not load teams. Expected 200 OK response, got: ' + str(resp.status))
                body = await resp.json()
                teams = list()
                for team in body:
                    teams.append(HSSTeam(
                        tag=team['tag'],
                        name=team.get('name'),
                    ))
                return teams

    @retry_then_raise
    async def resolve_token(self, key: str):
        async with aiohttp.ClientSession() as sess:
            async with sess.get('{0}/users/@me'.format(self.api_url),
                                headers={'Authorization': f'Bearer {key}'}) as resp:
                if resp.status != http.HTTPStatus.OK:
                    raise HTTPException(resp.status, 'Could not load teams. Expected 200 OK response, got: ' + str(resp.status))

                body = await resp.json()
                
                tag = body.get('tag')
                if tag is None:
                    raise HTTPException(resp.status, 'Received invalid data. Body does not include tag.')

                return HSSTeam(
                    tag=tag,
                    name=body.get('name'),
                )
