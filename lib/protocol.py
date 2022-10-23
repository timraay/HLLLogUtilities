import asyncio

import array

from lib.exceptions import *

class HLLRconProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.AbstractEventLoop, timeout=None, logger=None):
        self._transport = None
        self._waiters = list()
        self._buffer = None

        self._loop = loop
        self.timeout = timeout
        self.xorkey = None
        self.logger = logger

        self.has_key = loop.create_future()

    def connection_made(self, transport):
        if self.logger: self.logger.info('Connection made! Transport: %s', transport)
        self._transport = transport

    def data_received(self, data):
        if self.xorkey is None:
            if self.logger: self.logger.debug('Received XOR-key: %s', data)
            self.xorkey = data
            self.has_key.set_result(True)
        else:
            if self._buffer is not None:
                self._buffer += data
            else:
                try:
                    waiter = self._waiters.pop(0)
                except:
                    print('NO WAITER:', data)
                    raise
                waiter.set_result(data)

    def connection_lost(self, exc):
        if self.logger: self.logger.fatal('Connection lost: %s', exc)
        self._transport = None
        if exc:
            raise HLLConnectionLostError(exc)

    def _xor(self, message, decode=False):
        """Encrypt or decrypt a message using the XOR key provided by the game server"""
        if isinstance(message, str):
            message = message.encode()

        n = []
        if not self.xorkey:
            raise HLLConnectionError("The game server did not return a key")
            
        for i in range(len(message)):
            n.append(message[i] ^ self.xorkey[i % len(self.xorkey)])

        res = array.array('B', n).tobytes()
        assert len(res) == len(message)
        if decode:
            return res.decode()
        return res
    
    async def write(self, message, multipart=False):
        waiter = self._loop.create_future()
        self._waiters.append(waiter)
        if len(self._waiters) > 1: # Wait for previous request to finish
            await self._waiters[len(self._waiters) - 2]

        if multipart:
            self._buffer = b""
        else:
            self._buffer = None

        if self.logger: self.logger.debug('Writing: %s', message)
        xored = self._xor(message)
        self._transport.write(xored)

        return waiter
    
    async def receive(self, waiter, decode=False, multipart=False):
        if multipart:
            try:
                data = b""
                self._buffer = b""
                for _ in range(10):
                    await asyncio.sleep(1.0)
                    if not self._buffer:
                        break
                    data += self._buffer
                    self._buffer = b""

                waiter2 = self._waiters.pop(0)
                if waiter != waiter2 and self.logger:
                    self.logger.warning('Popped waiter does not match')
                waiter.set_result(data)
                res = self._xor(data, decode=decode)
            
            finally:
                self._buffer = None

        else:
            data = await waiter
            res = self._xor(data, decode=decode)

        if self.logger: self.logger.debug('Response: %s', res[:200].replace('\n', '\\n')+'...' if len(res) > 200 else res.replace('\n', '\\n'))
        return res

    async def execute(self, command, unpack_array=False, can_fail=False, multipart=False):
        waiter = await self.write(command)
        res = await self.receive(waiter, decode=True, multipart=multipart)

        if res == "FAIL":
            if can_fail:
                return False
            else:
                raise HLLCommandError('Game server returned status FAIL')

        if unpack_array:
            res = res.rstrip('\t').split('\t')
            arr_size = int(res.pop(0))
            if arr_size != len(res):
                raise HLLUnpackError("Expected array size %s but got %s", arr_size, len(res))
        
        elif res == "SUCCESS":
            return True

        return res

    async def authenticate(self, password):
        if self.logger: self.logger.debug('Waiting to login...')
        await self.has_key # Wait for XOR-key
        res = await self.execute(f'login {password}')
        if res != True:
            raise HLLAuthError()