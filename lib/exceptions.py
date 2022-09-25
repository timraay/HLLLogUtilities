
class HLLError(Exception):
    """Base exception for all source-related errors."""


class HLLCommandError(HLLError):
    """Raised when the game server returns an error for a request"""

class HLLConnectionError(HLLError):
    """Raised when the source is unable to connect and authenticate."""

class HLLAuthError(HLLConnectionError):
    """Raised for failed authentication.
    :ivar bool banned: signifies whether the authentication failed due to
        being banned or for merely providing the wrong password.
    """

    def __init__(self, banned=False):
        super().__init__("Authentication failed: " +
                         ("Banned" if banned else "Wrong password"))
        self.banned = banned

class HLLConnectionLostError(HLLConnectionError):
    pass


class HLLUnpackError(HLLError):
    """Raised for errors encoding or decoding RCON messages."""



class NotFound(ValueError):
    """Raised when a specific object could not be found or resolved"""

class SessionDeletedError(ValueError):
    """Raised when attempting to load a session whose data has already been deleted"""

class SessionAlreadyRunningError(ValueError):
    """Raised when attempting to load a session twice"""

class SessionMissingCredentialsError(RuntimeError):
    """Raised when trying to activate a session that doesn't have any server credentials"""
