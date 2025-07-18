import functools
import importlib
import inspect
import re
from typing import Any, Callable, Dict, Optional, Tuple, Union
import transformers


def check_hasattr(config: Any, *args: Union[str, Tuple[Any, ...]]):
    """
    Checks the confiugation has all the attributes in ``args``.
    Raises an exception otherwise.
    """
    for a in args:
        assert isinstance(a, (str, tuple)), f"unexpected type {type(a)} in {args!r}"
        if isinstance(a, str):
            assert (isinstance(config, dict) and a in config) or hasattr(
                config, a
            ), f"Missing attribute {a!r} in\n{config}"
        elif isinstance(a, tuple):
            assert any(
                (isinstance(name, str) and hasattr(config, name))
                or all(hasattr(config, _) for _ in name)
                for name in a
            ), f"All attributes in {a!r} are missing from\n{config}"


def update_config(config: Any, mkwargs: Dict[str, Any]):
    """Updates a configuration with different values."""
    for k, v in mkwargs.items():
        if k == "attn_implementation":
            config._attn_implementation = v
            if getattr(config, "_attn_implementation_autoset", False):
                config._attn_implementation_autoset = False
            continue
        if isinstance(v, dict):
            if not hasattr(config, k) or getattr(config, k) is None:
                setattr(config, k, v)
                continue
            existing = getattr(config, k)
            if type(existing) is dict:
                existing.update(v)
            else:
                update_config(getattr(config, k), v)
            continue
        if type(config) is dict:
            config[k] = v
        else:
            setattr(config, k, v)


def _pick(config, *atts, exceptions: Optional[Dict[str, Callable]] = None):
    """Returns the first value found in the configuration."""
    if (
        exceptions
        and hasattr(config, "architectures")
        and len(config.architectures) == 1
        and config.architectures[0] in exceptions
    ):
        excs = exceptions[config.architectures[0]]
        return excs(config)
    for a in atts:
        if isinstance(a, str):
            if hasattr(config, a):
                return getattr(config, a)
        elif isinstance(a, tuple):
            if all(hasattr(config, _) for _ in a[1:]):
                return a[0]([getattr(config, _) for _ in a[1:]])
    raise AssertionError(f"Unable to find any of these {atts!r} in {config}")


def pick(config, name: str, default_value: Any) -> Any:
    """
    Returns the value of a attribute if config has it
    otherwise the default value.
    """
    if not config:
        return default_value
    if type(config) is dict:
        return config.get(name, default_value)
    return getattr(config, name, default_value)


@functools.cache
def config_class_from_architecture(arch: str, exc: bool = False) -> Optional[type]:
    """
    Retrieves the configuration class for a given architecture.

    :param arch: architecture (clas name)
    :param exc: raise an exception if not found
    :return: type
    """
    cls = getattr(transformers, arch)
    mod_name = cls.__module__
    mod = importlib.import_module(mod_name)
    source = inspect.getsource(mod)
    reg = re.compile("config: ([A-Za-z0-9]+)")
    fall = reg.findall(source)
    if len(fall) == 0:
        assert not exc, (
            f"Unable to guess Configuration class name for arch={arch!r}, "
            f"module={mod_name!r}, no candidate, source is\n{source}"
        )
        return None
    unique = set(fall)
    assert len(unique) == 1, (
        f"Unable to guess Configuration class name for arch={arch!r}, "
        f"module={mod_name!r}, found={unique} (#{len(unique)}), "
        f"source is\n{source}"
    )
    cls_name = unique.pop()
    return getattr(transformers, cls_name)
