from datetime import datetime, timezone
from contextlib import contextmanager
import pydantic
from typing import *
from collections import UserList

from utils import SingletonMeta

if TYPE_CHECKING:
    from lib.info.models import InfoHopper

obj_setattr = object.__setattr__
obj_getattr = object.__getattribute__

class UnsetType(metaclass=SingletonMeta):
    def __bool__(self):
        return False
    def __iter__(self):
        return
        yield
    def __repr__(self):
        return "Unset"
Unset = UnsetType()
UnsetField = pydantic.Field(default_factory=lambda: Unset)

class Link:
    """Creates a link to one or more info entries"""
    def __init__(self, path: str, values: Dict[str, Any], multiple: bool = False, fallback: Any = None):
        """Initiate a link.

        A link is a reference to another value from an array. `path` is the
        path leading to this array. It will then filter out all values where
        all attributes match the given values, as specified in the `values`
        parameter. If `multiple` is `True` it will return all matches.
        Otherwise it will result a single object. If nothing is found, an
        empty list or `None` is returned instead.

        Parameters
        ----------
        path : str
            The path of the array
        values : Dict[str, Any]
            A mapping of attribute names and their respective values
        multiple : bool, optional
            Whether a list should be returned instead of a single object, by
            default False
        fallback : Any
            A value to fall back to in case no objects could be resolved
            with the given values. Use cautiously; it may cause problems
            when merging, by default None
        """
        self.values = values
        self.path = path
        self.multiple = multiple
        self.fallback = fallback
    def __str__(self):
        return ",".join([f"{attr}={val}" for attr, val in self.values.items()])
    def __repr__(self):
        return f'Link[{self.__str__()}{"..." if self.multiple else ""}]'
    def __eq__(self, other):
        if isinstance(other, Link):
            return self.values == other.values
        elif isinstance(other, dict):
            return other.items() <= self.values.items()
        return NotImplemented

class ModelTree(pydantic.BaseModel):
    class Config:
        arbitrary_types_allowed = True

    def __repr_args__(self):
        return [
            (k, obj_getattr(self, k)) for k in self.__fields__.keys() if self.__fields__[k].field_info.repr
        ]

    @property
    def root(self) -> 'InfoHopper':
        return getattr(self, '__hopper__', self)

    def __iter__(self) -> Generator[tuple, None, None]:
        for attr in self.__fields__:
            yield (attr, obj_getattr(self, attr))

    def __contains__(self, item):
        if isinstance(item, ModelTree):
            return item in self.flatten()
        else:
            return False

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, pydantic.BaseModel):
            return dict(self) == dict(other)
        else:
            return dict(self) == other

    def flatten(self):
        """Create a generator of all models attached
        to this one

        Yields
        ------
        ModelTree
            An attached model
        """        
        for key, value in self:
            if isinstance(value, ModelTree):
                if hasattr(self, '__links__') and not self.__links__.get(key):
                    yield value
                    yield from value.flatten()
            elif isinstance(value, InfoModelArray):
                for item in value:
                    yield item
                    yield from item.flatten()

    def is_mutable(self):
        """Whether the model is mutable or not

        Returns
        -------
        bool
            Whether the model is mutable
        """
        return not self.root.__solid__ and self.__config__.allow_mutation
    def set_mutable(self, _bool, force=False):
        """Change this model's mutability, including all of
        its children.

        Parameters
        ----------
        _bool : bool
            Whether this model should be mutable
        force : bool, optional
            Whether to continue with the operation even if in
            theory it shouldn't make a difference, by default
            False
        """
        root = self.root
        _bool = bool(_bool)
        if root.__solid__ != _bool or force:
            for model in root.flatten():
                model.__config__.allow_mutation = False
            root.__solid__ = _bool
    @contextmanager
    def ignore_immutability(self):
        """A context manager to make this model temporarily mutable
        even if it shouldn't."""
        is_mutable = self.is_mutable()
        try:
            if not is_mutable:
                self.set_mutable(True)
            yield self
        finally:
            if not is_mutable:
                self.set_mutable(False)

    def merge(self, other: 'ModelTree'):
        """Merge another model into this one.
        
        This model will inherit all of the other model with
        the other model taking priority, while the other model
        stays untouched.

        Parameters
        ----------
        other : ModelTree
            The other ModelTree to merge from

        Raises
        ------
        TypeError
            Models are not of same class
        TypeError
            This model is not mutable
        """
        if not isinstance(other, self.__class__):
            raise TypeError('Info classes are not of same type: %s and %s' % (type(self).__name__, type(other).__name__))
        if not self.is_mutable():
            raise TypeError('Model must be mutable to merge another into it')

        for attr in other.__fields__:
            self_val = self.get(attr, raw=True)
            other_val = other.get(attr, raw=True)

            if other_val is Unset:
                # Do nothing
                continue
            
            if self_val is Unset:
                # Copy other to self
                setattr(self, attr, other_val)
            
            elif isinstance(self_val, ModelTree):
                if isinstance(other_val, self_val.__class__):
                    # Merge other into self
                    self_val.merge(other_val)
                else:
                    #getLogger().warning('Skipping attempt to merge %s into %s', type(other_val).__name__, type(self_val).__name__)
                    pass

            elif isinstance(other_val, InfoModelArray) and isinstance(self_val, InfoModelArray):
                for other_iter in other_val:
                    if isinstance(other_iter, InfoModel):
                        # Find matching model and merge
                        attrs = {attr: other_iter.get(attr) for attr in other_iter.__key_fields__ if other_iter.get(attr)}
                        self_iter = self._get(self_val, single=True, ignore_unknown=True, **attrs)
                        if self_iter:
                            self_iter.merge(other_iter)
                        else:
                            #getLogger().warning('Could not match %s %s to existing record, discarding...', type(other_iter).__name__, attrs)
                            pass


    def _get(self, key, multiple=False, ignore_unknown=False, **filters) -> Union['ModelTree', 'InfoModel', 'InfoModelArray']:
        """Return a model from one of this model's `InfoModelArray`s.

        `**filters` contains a mapping of attributes and values to
        filter for. The array to filter is `key`. If `key` is a string
        it will be interpret as the name of one of this model's
        attributes.

        Parameters
        ----------
        key : Union[InfoModelArray, str]
            An array or attribute name
        multiple : bool, optional
            Whether a list of matches should be returned, by default
            False
        ignore_unknown : bool, optional
            Whether to ignore filter keys that are not recognized as
            a property, by default False
        **filters : dict
            A mapping of attribute names and values to filter for

        Returns
        -------
        Union[ModelTree, InfoModel, InfoModelArray]
            The model or array of models found

        Raises
        ------
        TypeError
            The `key` attribute does not point to an `InfoModelArray`
        """
        if isinstance(key, InfoModelArray):
            array = key
        else:
            array = self.get(key, raw=True)

        if array is Unset:
            array = InfoModelArray()
        elif not isinstance(array, InfoModelArray):
            raise TypeError('%s must point to an InfoModelArray, not %s' % (key, type(array)))

        res = InfoModelArray(filter(lambda x: x.matches(ignore_unknown=ignore_unknown, **filters), array))
        return res if multiple else (res[0] if res else None)
    
    def _add(self, key, *objects):
        """Add a model to one of this model's `InfoModelArray`s.

        Parameters
        ----------
        key : Union[InfoModelArray, str]
            An array or attribute name

        Returns
        -------
        InfoModelArray
            The new array

        Raises
        ------
        TypeError
            The `key` attribute does not point to an `InfoModelArray`
        """
        if isinstance(key, InfoModelArray):
            array = key
        else:
            array = self.get(key, raw=True)
            
        if array is Unset:
            array = InfoModelArray()
        elif not isinstance(array, InfoModelArray):
            raise TypeError('%s must point to an InfoModelArray, not %s' % (key, type(array)))

        for obj in objects:
            array.append(obj)
        setattr(self, key, array)
        return array
    
    def get(self, name, default=None, raw=False):
        """Get one of this model's attributes.

        Parameters
        ----------
        name : str
            The name of the attribute
        default : bool, optional
            The value to return if the attribute is not found,
            by default None
        raw : bool, optional
            Whether to resolve links and `UnsetField`s, by default False

        Returns
        -------
        Any
            The returned value
        """        
        try:
            if raw:
                return obj_getattr(self, name)
            else:
                return getattr(self, name, default)
        except AttributeError:
            return default
    def has(self, name):
        """Returns whether this model has an attribute with
        this name.

        Parameters
        ----------
        name : str
            The name of the attribute

        Returns
        -------
        bool
            Whether the attribute exists
        """
        return name in self.__fields__ and obj_getattr(self, name) is not Unset
    
    def to_dict(self, is_ref=False, exclude_unset=False) -> dict:
        """Cast this model to a dict.

        Parameters
        ----------
        is_ref : bool, optional
            Whether the model was obtained via a :class:`Link`.
            This will only return the key fields to
            avoid infinite recursion, by default False
        exclude_unset : bool, optional
            Whether to exclude variables that are left unset, by
            default False

        Returns
        -------
        dict
            The model as a dict
        """
        d = dict()
        key_fields = getattr(self, '__key_fields__', [])

        for attr in self.__fields__ if not is_ref or not key_fields else key_fields:
            val = self.get(attr, default=Unset)

            #if not is_ref and not key_fields and isinstance(val, pydantic.BaseModel):
            #    continue
            if exclude_unset and val == Unset:
                continue

            _is_ref = isinstance(self, InfoModel) and attr in self.__links__
            if isinstance(val, ModelTree):
                val = val.to_dict(is_ref=_is_ref, exclude_unset=exclude_unset)
            elif isinstance(val, InfoModelArray):
                val = [v.to_dict(is_ref=_is_ref, exclude_unset=exclude_unset) for v in val]
            d[attr] = val
        return d

class InfoModel(ModelTree):
    __scope_path__: ClassVar[str]
    __key_fields__: ClassVar[Tuple[str, ...]]
    __hopper__: 'InfoHopper'
    __links__: Dict[str, Link]
    __created_at__: datetime
    
    def __init__(self, hopper: 'InfoHopper', *args, **kwargs):
        _flat = hopper.flatten()
        self.__validate_values(kwargs.values(), _flat=_flat)

        self.update_forward_refs()
        super().__init__(*args, **kwargs)

        links = dict()
        for key, val in kwargs.items():
            if isinstance(val, Link):
                links[key] = val

        obj_setattr(self, '__hopper__', hopper)
        obj_setattr(self, '__links__', links)
        obj_setattr(self, '__created_at__', datetime.now(tz=timezone.utc))

    def __validate_values(self, values, _flat=None):
        for val in values:
            if isinstance(val, ModelTree):
                if _flat is None:
                    _flat = self.__hopper__.flatten()
                flat = list(_flat)
                if val in flat:
                    raise ValueError('%s is already part of tree. Use a Link instead.' % val.__class__.__name__)
                self.__validate_values(dict(val).values(), _flat=_flat)

    def __getattribute__(self, name: str):
        if name in obj_getattr(self, '__fields__'):
            try:
                links = obj_getattr(self, '__links__')
                link = links.get(name)
            except:
                link = None

            if link:
                res = self._get_link_value(link)
            else:
                res = super().__getattribute__(name)

            if res is Unset:
                raise AttributeError(f'"{type(self).__name__}" has no attribute "{name}"')
            return res
        else:
            return super().__getattribute__(name)
    
    def __setattr__(self, name, value):
        if isinstance(value, Link):
            return self._add_link(value, name)
        elif isinstance(value, ModelTree):
            self.__validate_values([value])
        super().__setattr__(name, value)
        obj_getattr(self, '__links__').pop(name, None)
    
    def __eq__(self, other):
        if isinstance(other, dict):
            d2 = other
        elif isinstance(other, InfoModel):    
            if not isinstance(other, self.__class__) or not isinstance(self, other.__class__):
                #raise TypeError("%s is no instance of %s or vice versa" % (other.__class__.__name__, self.__class__.__name__))
                return False
            d2 = other.get_key_attributes(exclude_unset=True)
        else:
            return NotImplemented
            
        d1 = self.get_key_attributes(exclude_unset=True)
        for k, v in d1.items():
            if k in d2:
                if d2[k] != v:
                    return False
        return True

    def _add_link(self, link: Link, name):
        super().__setattr__(name, link)
        self.__links__[name] = link
    
    def _get_link_value(self, link: Link):
        hopper: 'InfoHopper' = obj_getattr(self, '__hopper__')
        res = hopper._get(link.path, multiple=link.multiple, **link.values)
        if not res and link.fallback:
            return link.fallback
        return res
    
    def create_link(self, with_fallback=False, hopper: 'InfoHopper' = None):
        if not self.__key_fields__:
            raise TypeError('This model does not have any key fields specified')

        values = self.get_key_attributes(exclude_unset=True, exclude_links=True)
        if not values:
            raise ValueError('No key fields have values assigned')
        
        fallback = None
        if with_fallback:
            if hopper is None:
                fallback = type(self)(self.__hopper__, **self.get_key_attributes(exclude_unset=True, exclude_links=True))
            elif isinstance(hopper, ModelTree):
                fallback = self.copy(hopper.root)
            else:
                raise TypeError('hopper must be an ModelTree, got %s' % type(hopper).__name__)

        return Link(self.__scope_path__, values, fallback=fallback)

    def copy(self, hopper: 'InfoHopper'):
        new = type(self)(hopper)
        new.merge(self)
        return new

    def _get_raw_value(self, attr):
        res = self.get(attr, raw=True)
        if isinstance(res, Link):
            return res.values
        else:
            return res

    def get_key_attributes(self, exclude_unset=False, exclude_links=False):
        return {attr: self._get_raw_value(attr) for attr in self.__key_fields__
                if not (exclude_unset and self._get_raw_value(attr) == Unset)
                and not (exclude_links and self.__links__.get(attr))}
    
    @property
    def key_attribute(self):
        return tuple(self.get_key_attributes(exclude_unset=True, exclude_links=True).values())[0]
        
    def matches(self, ignore_unknown=False, **filters):
        return all(
            self.get(key, raw=True) == value for key, value in filters.items()
            if not (ignore_unknown and self.get(key, default=Unset, raw=True) == Unset)
        )
    
    def args(self):
        return (self.get(attr) for attr in self.__fields__)

class InfoModelArray(UserList):
    def __init__(self, initlist=None) -> List[InfoModel]:
        self.data = []
        if initlist is not None:
            if isinstance(initlist, UserList):
                self.data[:] = initlist.data[:]
            else:
                if type(initlist) != type(self.data):
                    initlist = list(initlist)
                for value in initlist:
                    self.__validate(value)
                self.data[:] = initlist

    @staticmethod
    def __validate(value):
        if not isinstance(value, InfoModel):
            raise TypeError('Sequence only allows InfoModel, not %s' % type(value).__name__)

    def __setitem__(self, index, value):
        self.__validate(value)
        return super().__setitem__(index, value)
    
    def __iadd__(self, other):
        if isinstance(other, UserList):
            self.data += other.data
        elif isinstance(other, type(self.data)):
            for value in other:
                self.__validate(value)
            self.data += other
        else:
            other = list(other)
            for value in other:
                self.__validate(value)
            self.data += other
        return self
    
    def append(self, item):
        self.__validate(item)
        self.data.append(item)

    def insert(self, i, item):
        self.__validate(item)
        self.data.insert(i, item)
    
    def extend(self, other):
        if isinstance(other, InfoModelArray):
            self.data.extend(other.data)
        else:
            if isinstance(other, UserList):
                other = other.data
            for value in other:
                self.__validate(value)
            self.data.extend(other)

from functools import reduce
from discord.flags import BaseFlags
# discord.py provides some nice tools for making flags. We have to be
# careful for breaking changes however.

class Flags(BaseFlags):
    __slots__ = ()

    def __init__(self, value: int = 0, **kwargs: bool) -> None:
        self.value: int = value
        for key, value in kwargs.items():
            if key not in self.VALID_FLAGS:
                raise TypeError(f'{key!r} is not a valid flag name.')
            setattr(self, key, value)

    def is_subset(self, other: 'Flags') -> bool:
        """Returns ``True`` if self has the same or fewer permissions as other."""
        if isinstance(other, Flags):
            return (self.value & other.value) == self.value
        else:
            raise TypeError(f"cannot compare {self.__class__.__name__} with {other.__class__.__name__}")

    def is_superset(self, other: 'Flags') -> bool:
        """Returns ``True`` if self has the same or more permissions as other."""
        if isinstance(other, Flags):
            return (self.value | other.value) == self.value
        else:
            raise TypeError(f"cannot compare {self.__class__.__name__} with {other.__class__.__name__}")

    def is_strict_subset(self, other: 'Flags') -> bool:
        """Returns ``True`` if the permissions on other are a strict subset of those on self."""
        return self.is_subset(other) and self != other

    def is_strict_superset(self, other: 'Flags') -> bool:
        """Returns ``True`` if the permissions on other are a strict superset of those on self."""
        return self.is_superset(other) and self != other

    def __len__(self):
        i = 0
        for _, enabled in self:
            if enabled:
                i += 1
        return i

    def copy(self):
        return type(self)(self.value)

    __le__ = is_subset
    __ge__ = is_superset
    __lt__ = is_strict_subset
    __gt__ = is_strict_superset

    @classmethod
    def all(cls: Type['Flags']) -> 'Flags':
        value = reduce(lambda a, b: a | b, cls.VALID_FLAGS.values())
        self = cls.__new__(cls)
        self.value = value
        return self

    @classmethod
    def none(cls: Type['Flags']) -> 'Flags':
        self = cls.__new__(cls)
        self.value = self.DEFAULT_VALUE
        return self
