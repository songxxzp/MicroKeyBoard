import os


DEBUG = False


def debug_switch(mode = None):
    global DEBUG
    if mode is None:
        DEBUG = not DEBUG
    else:
        DEBUG = mode
    print(f"set DEBUG = {DEBUG}")
    

def debugging() -> bool:
    return DEBUG


def exists(path: str) -> bool:
    try: os.stat(path); return True
    except OSError: return False


def partial(func, *args, **kwargs):
    def wrapper(*more_args, **more_kwargs):
        return func(*args, *more_args, **kwargs, **more_kwargs)
    return wrapper


def makedirs(path):
    parts = path.split('/')
    current_path = ''
    if path.startswith('/'):
        current_path = '/'

    for part in parts:
        if not part:
            continue

        if current_path == '/':
            current_path += part
        elif current_path != '':
            current_path += os.sep + part
        else:
            current_path = part

        if current_path == '/' or exists(current_path):
            continue

        os.mkdir(current_path)


def format_bytes(size):
    """
    Helper function to format byte counts into a human-readable string
    using B, KB, MB, GB units.
    """
    # Define units and their corresponding powers of 1024
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'} # Added T for Terabytes if needed, though unlikely on typical MicroPython

    # Divide by 1024 until the size is less than the next unit or we run out of labels
    while size >= power and n < len(power_labels) - 1:
        size /= power
        n += 1

    # Return the formatted string, rounding to one decimal place for units larger than bytes
    return f"{size:.1f}{power_labels[n]}B" if n > 0 else f"{size}{power_labels[n]}B"


def check_disk_space():
    """
    Checks and prints the total, free, and used disk space
    of the root filesystem ('/') on a MicroPython device.
    Prints the information in a human-readable format (B, KB, MB, GB).
    """
    try:
        # Get filesystem statistics for the root directory.
        # os.statvfs('/') returns a tuple with filesystem information.
        # We are interested in:
        # [0]: f_bsize (file system block size)
        # [2]: f_blocks (total number of blocks)
        # [3]: f_bfree (total number of free blocks)
        # [4]: f_bavail (number of free blocks available to non-privileged users)
        # We'll use f_bsize, f_blocks, and f_bfree to calculate space.
        stats = os.statvfs('/')

        # Extract the necessary values from the stats tuple
        block_size = stats[0]     # Size of each block in bytes
        total_blocks = stats[2]   # Total number of blocks in the filesystem
        free_blocks = stats[3]    # Number of free blocks

        # Calculate the total, free, and used space in bytes
        total_bytes = total_blocks * block_size
        free_bytes = free_blocks * block_size
        used_bytes = total_bytes - free_bytes

        # Print the disk space information in a clear, human-readable format
        print("--- MicroPython Storage Information ---")
        print(f"Total Space: {format_bytes(total_bytes)}")
        print(f"Free Space:  {format_bytes(free_bytes)}")
        print(f"Used Space:  {format_bytes(used_bytes)}")
        print("-------------------------------------")

    except AttributeError:
        # Handle the case where os.statvfs is not available (e.g., on a minimal build)
        print("Error: The 'os.statvfs' function is not available on this MicroPython build.")
    except OSError as e:
        # Handle potential OS errors, like the filesystem not being ready or mounted
        print(f"Error accessing filesystem statistics: {e}")
    except Exception as e:
        # Catch any other unexpected errors
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
  check_disk_space()
