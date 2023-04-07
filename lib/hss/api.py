import http
import json
from io import StringIO
from typing import TypedDict

import aiohttp
from aiohttp import FormData

from lib.hss.apikeys import ApiKeys


class Team(TypedDict):
    tag: str
    name: str


class HSSApi:
    def __init__(self, api_url: str):
        self.api_url = api_url

    async def submit_match(self, guild_id: int, winning_team: str, opposing_team: str, csv_export: StringIO) -> str:
        key = await self._api_key(guild_id, winning_team, opposing_team)
        if key is None:
            raise Exception(f'You do not have an API Key for {winning_team}, nor for {opposing_team} and '
                            f'can therefore not submit a match for these teams.')

        data = FormData()
        data.add_field("data", json.dumps({'teams': [winning_team, opposing_team]}))
        data.add_field("file", csv_export, filename="export.csv")
        async with aiohttp.ClientSession() as sess:
            async with sess.post('{0}/matches/serverlog'.format(self.api_url), data=data,
                                 headers={'Authorization': f'Bearer {key.key}'}) as resp:
                body = await resp.json()

                if resp.status == http.HTTPStatus.CREATED.value:
                    return body.get('match_id')
                if resp.status == http.HTTPStatus.FORBIDDEN or resp.status == http.HTTPStatus.BAD_REQUEST:
                    raise Exception(body.get('error'))
                if resp.status == http.HTTPStatus.UNAUTHORIZED:
                    raise Exception(
                        'You do not have a valid authorization for either the winning or opposing team. '
                        'Please add your authorization token of your team using the ... command')
                raise Exception('An unknown error occurred submitting your match. Error: ' + body.get('error'))

    async def teams(self) -> list[Team]:
        async with aiohttp.ClientSession() as sess:
            async with sess.get('{0}/teams'.format(self.api_url)) as resp:
                if resp.status != http.HTTPStatus.OK:
                    raise Exception('Could not load teams. Expected 200 OK response, got: ' + str(resp.status))
                body = await resp.json()
                teams: list[Team] = []
                for team in body:
                    teams.append({
                        'name': team.get('name'),
                        'tag': team.get('tag'),
                    })
                return teams

    async def _api_key(self, guild_id: int, winning_team: str, opposing_team: str) -> ApiKeys or None:
        for key in ApiKeys.in_guild(guild_id):
            if key.tag == winning_team:
                return key
            if key.tag == opposing_team:
                return key
        return None
