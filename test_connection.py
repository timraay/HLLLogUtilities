from lib.exceptions import HLLAuthError
from traceback import print_exc
import asyncio

from hllrcon import Rcon

inp = input('Address + Port: ')
address, port = inp.split(':', 1)
password = input('Password (optional): ')

async def main():
    try:
        rcon = Rcon(
            host=address,
            port=int(port),
            password="password",
        )
        async with rcon.connect():
            pass
        
    except HLLAuthError:
        if password:
            print_exc()
        else:
            print('Successfully connected')
    except Exception:
        print_exc()
    
    else:
        print('Successfully connected') 
        
    finally:
        input('Press Enter to exit')

asyncio.run(main())