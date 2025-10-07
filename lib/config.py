import pydantic

class BasicConfig(pydantic.BaseModel):
    config_class: type['BasicConfig'] = None # type: ignore

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
                config_options = parent.config.model_dump(exclude_unset=True)

        if config:
            for k, v in config.__dict__.items():
                if not k.startswith('_'):
                    config_options[k] = v

        Config = config_options.get('config_class', None) or BasicConfig

        skip_init = (parent is not None) and getattr(config, '__skip_config_init', None) and not getattr(parent, '__skip_config_init', None)
        attrs['config'] = BasicConfig(config_class=Config) if skip_init else Config(**config_options)
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