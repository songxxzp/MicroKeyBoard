import os

def exists(path: str) -> bool:
    try: os.stat(path); return True
    except OSError: return False

def partial(func, *args, **kwargs):
    def wrapper(*more_args, **more_kwargs):
        return func(*args, *more_args, **kwargs, **more_kwargs)
    return wrapper
