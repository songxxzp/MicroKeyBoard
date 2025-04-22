import os

def exists(path: str) -> bool:
    try: os.stat(path); return True
    except OSError: return False

def partial(func, *args):
    def wrapper(*more_args):
        return func(*args, *more_args)
    return wrapper
