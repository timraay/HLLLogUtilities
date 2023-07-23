import asyncio

import array

from lib.exceptions import *

class HLLRconProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.AbstractEventLoop, timeout=None, logger=None):
        self._transport = None
        self._waiter = loop.create_future()
        self._queue = list()

        self._loop = loop
        self.timeout = timeout
        self.xorkey = None
        self.logger = logger

        self.has_key = loop.create_future()

    def connection_made(self, transport):
        if self.logger: self.logger.info('Connection made! Transport: %s', transport)
        self._transport = transport

    def data_received(self, data, was_repeated=False):
        if self.xorkey is None:
            if self.logger: self.logger.debug('Received XOR-key: %s', data)
            self.xorkey = data
            self.has_key.set_result(True)
        else:
            if self._waiter.done():
                if was_repeated:
                    if self.logger: self.logger.warning('Active waiter is not being awaited, discarding additional incoming data')
                else:
                    if self.logger: self.logger.debug('Received data too early, calling again soon')
                    self._loop.call_soon(self.data_received, data, True)
            else:
                self._waiter.set_result(data)
                # self._waiter = self._loop.create_future()
                if not self._queue:
                    self.logger.warning('Received data but there are no waiters: `%s`', self._xor(data))

    def connection_lost(self, exc):
        self._transport = None
        if exc:
            if self.logger:
                self.logger.critical('Connection lost: %s', exc)
            raise HLLConnectionLostError(exc)
        else:
            if self.logger:
                self.logger.info('Connection closed')

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
    
    async def _get_waiter(self):
        result = await self._waiter
        self._waiter = self._loop.create_future()
        return result
    
    async def write(self, message):
        waiter = self._loop.create_future()
        self._queue.append(waiter)

        if len(self._queue) > 1: # Wait for previous request to finish
            await self._queue[len(self._queue) - 2]
        
        if self.logger:
            self.logger.debug('Writing: %s', message)
        xored = self._xor(message)
        self._transport.write(xored)

        return waiter
    
    async def receive(self, waiter, decode=False, is_array=False, multipart=False):
        if self.logger:
            self.logger.debug('Receiving! %s is_array=%s multipart=%s', self._waiter, is_array, multipart)

        if self._waiter.cancelled():
            self._waiter = self._loop.create_future()
            if self.logger:
                self.logger.warning('Waiter was cancelled, replacing.')
        
        data = await self._get_waiter()

        if multipart:
            do_loop = True
        else:
            do_loop = False
            if is_array:
                try:
                    self.unpack_array(self._xor(data))
                except HLLUnpackError:
                    # Response is incomplete
                    do_loop = True
        
        i_max = 10
        for i in range(i_max):
            if not do_loop:
                break

            if self.logger:
                self.logger.debug('Waiting for more packets to arrive...')
            
            try:
                data += await asyncio.wait_for(self._get_waiter(), 1.0)

            except asyncio.TimeoutError:
                self._waiter = self._loop.create_future()
                do_loop = False
                if self.logger:
                    self.logger.debug('Timed out, exiting loop.')

            else:
                if is_array:
                    try:
                        # Response is complete!
                        self.unpack_array(self._xor(data))
                        if self.logger:
                            self.logger.debug('Array response complete, exiting loop.')
                    except HLLUnpackError:
                        do_loop = True

        if i == i_max - 1 and self.logger:
            self.logger.debug('Completed all %s multipart cycles', i_max)
        

        res = self._xor(data, decode=decode)
        if self.logger:
            self.logger.debug('Response: %s', res[:200].replace('\n', '\\n')+'...' if len(res) > 200 else res.replace('\n', '\\n'))
        
        waiter.set_result(res)

        return res

    async def execute(self, command, unpack_array=False, can_fail=False, multipart=False):
        waiter = await self.write(command)
        res = await self.receive(waiter, decode=True, is_array=unpack_array, multipart=multipart)

        if res == "FAIL":
            if can_fail:
                return False
            else:
                raise HLLCommandError('Game server returned status FAIL')

        if unpack_array:
            res = self.unpack_array(res)
        
        elif res == "SUCCESS":
            return True

        return res
    
    @staticmethod
    def unpack_array(string: str):
        sep = b'\t' if isinstance(string, bytes) else '\t'
        res = string.split(sep)[:-1]
        arr_size = int(res.pop(0))
        if arr_size != len(res):
            raise HLLUnpackError("Expected array size %s but got %s", arr_size, len(res))
        return res

    async def authenticate(self, password):
        if self.logger: self.logger.debug('Waiting to login...')
        await self.has_key # Wait for XOR-key
        res = await self.execute(f'login {password}', can_fail=True)
        if res != True:
            raise HLLAuthError()
