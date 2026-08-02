class NotFound(ValueError):
    """Raised when a specific object could not be found or resolved"""


class DuplicationError(ValueError):
    """Raised when attempting to instantiate a class with a custom ID for which another class is already instantiated"""


class SessionDeletedError(ValueError):
    """Raised when attempting to load a session whose data has already been deleted"""


class SessionAlreadyRunningError(DuplicationError):
    """Raised when attempting to load a session twice"""


class SessionMissingCredentialsError(RuntimeError):
    """Raised when trying to activate a session that doesn't have any server credentials"""


class CredentialsAlreadyCreatedError(DuplicationError):
    """Raised when attempting to load a set of credentials more than once"""


class AutoSessionAlreadyCreatedError(DuplicationError):
    """Raised when attempting to create an AutoSession for the same credentials twice"""


class TemporaryCredentialsError(ValueError):
    """Raised when the given credentials must not be but are temporary"""


class HTTPException(Exception):
    """Raised when an unexpected response was received from a web API"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


from aiohttp import ClientError


class HSSConnectionError(ClientError):
    """Raised when an error occurs connecting to HSS"""
