import os

def path_exists(path: str) -> bool:
    try: os.stat(path); return True
    except OSError: return False
