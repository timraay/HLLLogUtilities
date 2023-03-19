from typing import TYPE_CHECKING, Dict, List

from lib.info.models import EventModel, EventTypes
from lib.info.events import EventListener
from lib.config import Configurable, BasicConfig, skip_config_init

if TYPE_CHECKING:
    from lib.session import HLLCaptureSession

class ModifierConfig(BasicConfig):
    id: str
    name: str
    description: str
    emoji: str

class Modifier(Configurable):
    """The base class for modifiers. Modifiers contain event listeners
    for in-game actions allowing custom rules to be enforced."""
    config: ModifierConfig

    @skip_config_init
    class Config:
        config_class=ModifierConfig

    def __init__(self, session: 'HLLCaptureSession'):
        self.session = session

        self.listeners: Dict[str, List[EventListener]] = dict()
        for listener in self.walk_listeners():
            for event_type in listener.events:
                self.listeners.setdefault(event_type, list()).append(listener)
    
    @property
    def rcon(self):
        return self.session.rcon
    @property
    def logger(self):
        return self.session.logger
    
    def walk_listeners(self):
        """Creates a generator of all listeners this plugin has.

        Yields
        ------
        EventListener
            An event listener
        """
        for cls in self.__class__.mro():
            for val in cls.__dict__.values():
                if isinstance(val, EventListener):
                    yield val
    
    def get_listeners_for_event(self, event: EventModel):
        """Returns a generator of all listeners that listen for this event

        Parameters
        ----------
        event : EventModel
            The event

        Yields
        ------
        EventListener
            A corresponding event listener
        """
        event_type = EventTypes(type(event)).name
        yield from self.listeners.get(event_type, list())
