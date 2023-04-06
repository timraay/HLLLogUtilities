import http
import json
from io import StringIO

import aiohttp
from aiohttp import FormData


class HSSApi:
    def __init__(self, api_url: str):
        self.api_url = api_url

    async def submit_match(self, winning_team, opposing_team, csv_export: StringIO) -> str:
        data = FormData()
        data.add_field("data", json.dumps({'teams': [winning_team, opposing_team]}))
        data.add_field("file", csv_export, filename="export.csv")
        async with aiohttp.ClientSession() as sess:
            async with sess.post('{0}/matches/serverlog'.format(self.api_url), data=data, headers={'Authorization': 'Bearer ...'}) as resp:
                body = await resp.json()

                if resp.status == http.HTTPStatus.CREATED.value:
                    return body.match_id
                if resp.status == http.HTTPStatus.FORBIDDEN or resp.status == http.HTTPStatus.BAD_REQUEST:
                    raise Exception(body.error)
                if resp.status == http.HTTPStatus.UNAUTHORIZED:
                    raise Exception(
                        'You do not have a valid authorization for either the winning or opposing team. '
                        'Please add your authorization token of your team using the ... command')
                raise Exception('An unknown error occurred submitting your match. Error: ' + body.error)
