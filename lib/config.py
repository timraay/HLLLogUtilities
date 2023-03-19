import pydantic
from typing import Type

class BasicConfig(pydantic.BaseModel):
    _exclude_keys: set = pydantic.PrivateAttr(default=set())
    config_class: Type['BasicConfig'] = None

    class Config:
        arbitrary_types_allowed = True

class ConfigMeta(type):
    """Metaclass for plugins used to initialize config variables"""
    def __new__(cls, name, bases, attrs):
        config_options = dict()
        config = attrs.pop('Config', None)

        parent = None
        if bases:
            parent = bases[0]
            if issubclass(parent, Configurable):
                config_options = parent.config.dict(exclude_unset=True)

        if config:
            for k, v in config.__dict__.items():
                if not k.startswith('_'):
                    config_options[k] = v

        exclude_keys = set()
        Config = config_options.get('config_class', None) or BasicConfig
        if parent and getattr(config, '__skip_config_init', None) and not getattr(parent, '__skip_config_init', None):
            # Create a new pydantic model with validation disabled. Then
            # populate it with default values even if technically they
            # shouldn't be allowed.
            class Template(Config):
                class Config:
                    validate_all = False
            Config = Template
            for field in Config.__fields__.values():
                field.required = False

        attrs['config'] = Config(**config_options)
        attrs['config']._exclude_keys = exclude_keys
        return super(ConfigMeta, cls).__new__(cls, name, bases, attrs)


class Configurable(metaclass=ConfigMeta):
    """Inheritable class that adds a `config` classvar
    
    .. code-block:: py

        class MyClass(Configurable):
            config: MyClassConfig

            @skip_config_init
            class Config:
                config_class=MyClassConfig
    
    """
    config: BasicConfig

def skip_config_init(cls):
    cls.__skip_config_init = True
    return cls