from types import FunctionType, ModuleType


#Bind legacy functions to shared runtime state
def bind_module(target_globals, source_module):
    for name, value in vars(source_module).items():
        if name.startswith("__") or isinstance(value, ModuleType):
            continue
        if isinstance(value, FunctionType):
            rebound = FunctionType(
                value.__code__,
                target_globals,
                name,
                value.__defaults__,
                value.__closure__,
            )
            rebound.__annotations__ = value.__annotations__
            rebound.__kwdefaults__ = value.__kwdefaults__
            target_globals[name] = rebound
            continue
        target_globals[name] = value
