# From https://github.com/russhughes/st7789py_mpy/blob/master/examples/color_test.py
def interpolate(value1, value2, position, total_range):
    """
    Perform linear interpolation between two values based on a position within a range.

    Args:
        value1 (float): Starting value.
        value2 (float): Ending value.
        position (float): Current position within the range.
        total_range (float): Total range of positions.

    Returns:
        float: Interpolated value.
    """
    return value1 + (value2 - value1) * position / total_range
