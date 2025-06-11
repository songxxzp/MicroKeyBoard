import micropython
# The 'struct' module is typically used for converting between Python values
# and C structs, but here we're using Viper's direct memory access.
# It's kept in the import for consistency if other parts of the project use it,
# but it's not directly used within these Viper functions themselves.
import struct 

# """ Viper Helper Functions for 16-bit Sample Access """
# These functions are critical for safely reading and writing multi-byte
# integer samples directly from/to `bytearray` memory in MicroPython's Viper mode.
# They explicitly handle endianness and signed conversion for 16-bit samples.

@micropython.viper
def _get_int16_le(buf: ptr8, byte_idx: int) -> int:
    """
    Reads a 16-bit signed **little-endian** integer from a bytearray at the specified byte index.
    
    Args:
        buf (ptr8): A pointer to the bytearray's underlying memory.
        byte_idx (int): The starting byte index of the 16-bit sample.
        
    Returns:
        int: The signed 16-bit integer value.
    """
    # Little-endian: LSB (Least Significant Byte) at lower address, MSB (Most Significant Byte) at higher address
    # Read LSB (buf[byte_idx]) and MSB (buf[byte_idx + 1]), then combine.
    val: int = int(buf[byte_idx]) | (int(buf[byte_idx + 1]) << 8)
    
    # Convert to signed 16-bit if the MSB indicates a negative number (e.g., if val is 32768 or greater)
    if val >= 32768:
        val -= 65536 # Equivalent to subtracting 2^16 for 2's complement
    return val

@micropython.viper
def _set_int16_le(buf: ptr8, byte_idx: int, value: int):
    """
    Writes a 16-bit signed **little-endian** integer to a bytearray at the specified byte index.
    Includes clamping to prevent overflow/underflow outside the 16-bit signed range.
    
    Args:
        buf (ptr8): A pointer to the bytearray's underlying memory.
        byte_idx (int): The starting byte index to write the 16-bit sample.
        value (int): The integer value to write.
    """
    # Clamp value to the 16-bit signed integer range (-32768 to 32767)
    if value > 32767:
        value = 32767
    elif value < -32768:
        value = -32768

    # Little-endian: LSB written first, then MSB
    buf[byte_idx] = int(value) & 0xFF        # Write LSB
    buf[byte_idx + 1] = (int(value) >> 8) & 0xFF # Write MSB

@micropython.viper
def _get_int16_be(buf: ptr8, byte_idx: int) -> int:
    """
    Reads a 16-bit signed **big-endian** integer from a bytearray at the specified byte index.
    
    Args:
        buf (ptr8): A pointer to the bytearray's underlying memory.
        byte_idx (int): The starting byte index of the 16-bit sample.
        
    Returns:
        int: The signed 16-bit integer value.
    """
    # Big-endian: MSB (Most Significant Byte) at lower address, LSB (Least Significant Byte) at higher address
    # Read MSB (buf[byte_idx]) and LSB (buf[byte_idx + 1]), then combine.
    val: int = (int(buf[byte_idx]) << 8) | int(buf[byte_idx + 1])
    
    # Convert to signed 16-bit if the MSB indicates a negative number
    if val >= 32768:
        val -= 65536
    return val

@micropython.viper
def _set_int16_be(buf: ptr8, byte_idx: int, value: int):
    """
    Writes a 16-bit signed **big-endian** integer to a bytearray at the specified byte index.
    Includes clamping to prevent overflow/underflow outside the 16-bit signed range.
    
    Args:
        buf (ptr8): A pointer to the bytearray's underlying memory.
        byte_idx (int): The starting byte index to write the 16-bit sample.
        value (int): The integer value to write.
    """
    # Clamp value to the 16-bit signed integer range (-32768 to 32767)
    if value > 32767:
        value = 32767
    elif value < -32768:
        value = -32768

    # Big-endian: MSB written first, then LSB
    buf[byte_idx] = (int(value) >> 8) & 0xFF # Write MSB
    buf[byte_idx + 1] = int(value) & 0xFF   # Write LSB

"""
## Viper Core Interpolation Function for Pitch Shifting

This function performs linear interpolation on audio samples to achieve pitch shifting. It takes an original buffer, interpolates its samples, and writes the result to a new buffer.

**Assumptions:**
* Audio samples are 16-bit signed integers.
* **Little-endian** format is used for sample reading/writing. If your samples are big-endian, you must swap `_get_int16_le` and `_set_int16_le` for their `_be` counterparts in this function.

"""
@micropython.viper
def _interpolate_viper_core(
    original_buf: ptr8,     # Pointer to the original audio data bytearray
    original_len_samples: int, # Number of samples in the original audio buffer
    new_len_samples: int,      # Desired number of samples for the interpolated audio
    result_buf: ptr8,          # Pointer to the bytearray where the interpolated result will be stored
    shift_factor_scaled: int,  # Pitch shift factor, scaled up by `scale_factor_interp` for integer math
    scale_factor_interp: int   # Scaling factor used for `shift_factor_scaled` (e.g., 10000)
):
    """
    Viper core interpolation function for audio pitch shifting.
    Performs linear interpolation to transform `original_buf` into `result_buf`.
    
    This function operates directly on memory for efficiency. It simulates
    floating-point arithmetic for interpolation by scaling values as integers.
    """
    # Fixed to 2 bytes per sample for 16-bit audio. Adjust if your sample bit depth changes.
    bytes_per_sample: int = 2 

    # Declare and initialize loop counter as a Viper integer for type safety and optimization.
    i_new_int: int = 0 

    for i_new_int in range(new_len_samples):
        # Calculate the floating-point index in the original sample array, scaled up.
        # Explicit `int()` casts are crucial in Viper to ensure operations are done with machine integers.
        original_float_idx_scaled: int = int(i_new_int) * int(shift_factor_scaled)

        # Separate the integer part (which sample index to start from)
        # and the fractional part (how far between that sample and the next).
        idx_int: int = int(original_float_idx_scaled) // int(scale_factor_interp)
        fractional_part_scaled: int = int(original_float_idx_scaled) % int(scale_factor_interp)

        # Boundary check: If the calculated index goes beyond the original sample data,
        # simply repeat the last valid sample to prevent out-of-bounds access.
        if int(idx_int) >= int(original_len_samples) - 1:
            sample_val: int = _get_int16_le(original_buf, (int(original_len_samples) - 1) * int(bytes_per_sample))
            _set_int16_le(result_buf, int(i_new_int) * int(bytes_per_sample), sample_val)
            continue # Move to the next sample in the result buffer

        # Get the two adjacent sample values from the original buffer needed for linear interpolation.
        y0: int = _get_int16_le(original_buf, int(idx_int) * int(bytes_per_sample))
        y1: int = _get_int16_le(original_buf, (int(idx_int) + 1) * int(bytes_per_sample))

        # Linear interpolation formula: y = y0 + (y1 - y0) * fractional_part
        # Implemented using scaled integer arithmetic for Viper compatibility.
        diff_y: int = int(y1) - int(y0)
        interp_val_scaled: int = int(y0) * int(scale_factor_interp) + int(diff_y) * int(fractional_part_scaled)
        
        # Scale back down to get the final interpolated sample value.
        interp_val: int = int(interp_val_scaled) // int(scale_factor_interp)

        # Write the calculated interpolated sample to the result buffer.
        _set_int16_le(result_buf, int(i_new_int) * int(bytes_per_sample), interp_val)

"""
## Python Wrapper for Interpolation

This higher-level Python function serves as a convenient wrapper for the Viper core, handling input validation, buffer preparation, and parameter scaling.

"""
def interpolate(
    closest_sample_bytes: bytes, # Original audio data (can be `bytes` or `bytearray`)
    original_length_bytes: int,  # Original length of the audio data in bytes
    new_length_bytes: int        # Desired length of the interpolated audio data in bytes
) -> bytearray:
    """
    Performs linear interpolation for audio pitch shifting using a Viper-optimized core.
    This function interpolates the `closest_sample_bytes` to a `new_length_bytes`.
    
    Assumes samples are 16-bit signed integers.
    
    Args:
        closest_sample_bytes (bytes): The input audio data.
        original_length_bytes (int): The byte length of the input audio data.
        new_length_bytes (int): The desired byte length of the output audio data.
        
    Returns:
        bytearray: A new bytearray containing the interpolated audio data.
        
    Raises:
        ValueError: If buffer lengths are not multiples of bytes per sample.
    """
    # Define bytes per sample. This must match the bit depth handled by _get_int16_le/_set_int16_le.
    BYTES_PER_SAMPLE: int = 2 
    
    # Validate that buffer lengths are compatible with the sample size.
    if original_length_bytes % BYTES_PER_SAMPLE != 0 or \
       new_length_bytes % BYTES_PER_SAMPLE != 0:
        raise ValueError("Buffer lengths must be multiples of bytes_per_sample.")

    # Convert byte lengths to sample counts.
    original_len_samples = original_length_bytes // BYTES_PER_SAMPLE
    new_len_samples = new_length_bytes // BYTES_PER_SAMPLE

    # Handle edge case: if the target length is zero, return an empty bytearray.
    if new_len_samples == 0:
        return bytearray() 

    # Ensure the original data is a mutable `bytearray` for Viper's direct memory access.
    # If `bytes` is passed, a copy is made. If `bytearray`, it's used directly.
    if not isinstance(closest_sample_bytes, bytearray):
        original_data_mutable = bytearray(closest_sample_bytes)
    else:
        original_data_mutable = closest_sample_bytes

    # Create a new `bytearray` to store the interpolated result.
    shifted_sample_bytes = bytearray(new_length_bytes)

    # Calculate the float pitch shift factor (ratio of original samples to new samples).
    # This factor will be scaled up for integer arithmetic in Viper.
    shift_factor_float: float = original_len_samples / new_len_samples

    # Define a scaling factor for integer-based float emulation in Viper.
    # A larger factor increases precision but might slightly increase computation time.
    SCALE_FACTOR_INTERP: int = 10000
    # Scale the float shift factor to an integer for Viper.
    shift_factor_scaled: int = int(shift_factor_float * SCALE_FACTOR_INTERP)

    # Call the Viper core interpolation function to perform the actual processing.
    _interpolate_viper_core(
        original_data_mutable,
        original_len_samples,
        new_len_samples,
        shifted_sample_bytes,
        shift_factor_scaled,
        SCALE_FACTOR_INTERP
    )

    return shifted_sample_bytes

"""
## Viper Core: Clear Bytearray

This function efficiently clears a `bytearray` by setting all its bytes to `0` directly in memory.

"""
@micropython.viper
def clear_bytearray_viper(buf: ptr8, length: int):
    """
    Clears all bytes in a bytearray to 0 using Viper for maximum efficiency.
    
    Args:
        buf (ptr8): A pointer to the bytearray's underlying memory.
        length (int): The number of bytes in the bytearray to clear.
    """
    # Iterate through each byte in the buffer and set it to 0.
    for i in range(length):
        buf[i] = 0

"""
## Viper Core: Element-wise Array Addition

This function performs element-wise addition of two 16-bit signed integer arrays, storing the result in a third array.

**Assumptions:**
* All arrays contain 16-bit signed integers.
* **Little-endian** format is used for sample reading/writing. If your samples are big-endian, you must swap `_get_int16_le` and `_set_int16_le` for their `_be` counterparts.

"""
@micropython.viper
def add_int16_arrays_viper(
    arr1_ptr: ptr8,      # Pointer to the first input bytearray
    arr1_len_bytes: int, # Byte length of the first bytearray
    arr2_ptr: ptr8,      # Pointer to the second input bytearray
    arr2_len_bytes: int, # Byte length of the second bytearray
    result_ptr: ptr8,    # Pointer to the output bytearray where the sum will be stored
    result_len_bytes: int # Byte length of the result bytearray
):
    """
    Performs element-wise addition of two 16-bit signed integer arrays 
    (represented as bytearrays) and stores the sum in a third array.
    
    The operation processes samples up to the length of the shortest array among the inputs and result.
    
    Args:
        arr1_ptr: Pointer to the first input bytearray.
        arr1_len_bytes: Length of the first input bytearray in bytes.
        arr2_ptr: Pointer to the second input bytearray.
        arr2_len_bytes: Length of the second input bytearray in bytes.
        result_ptr: Pointer to the output bytearray where the sum will be stored.
        result_len_bytes: Length of the output bytearray in bytes.
    """
    # Fixed to 2 bytes per sample for 16-bit audio.
    BYTES_PER_SAMPLE: int = 2 

    # Calculate lengths in terms of samples.
    arr1_len_samples: int = arr1_len_bytes // BYTES_PER_SAMPLE
    arr2_len_samples: int = arr2_len_bytes // BYTES_PER_SAMPLE
    result_len_samples: int = result_len_bytes // BYTES_PER_SAMPLE

    # Determine the actual number of samples to process. This ensures we don't
    # read or write beyond the bounds of any of the arrays.
    num_samples_to_process: int = arr1_len_samples
    if arr2_len_samples < num_samples_to_process:
        num_samples_to_process = arr2_len_samples
    if result_len_samples < num_samples_to_process:
        num_samples_to_process = result_len_samples

    # Loop through each sample, performing the addition.
    for i in range(num_samples_to_process):
        # Calculate the byte offset for the current sample.
        byte_offset: int = i * BYTES_PER_SAMPLE

        # Read samples from both input arrays.
        val1: int = _get_int16_le(arr1_ptr, byte_offset)
        val2: int = _get_int16_le(arr2_ptr, byte_offset)

        # Perform the addition.
        sum_val: int = val1 + val2

        # Write the calculated sum to the result array.
        _set_int16_le(result_ptr, byte_offset, sum_val)

"""
## Viper Core: In-place Array Addition (`a += b`)

This function performs element-wise addition directly into the first array (`arr1`), effectively adding the elements of `arr2` to `arr1`.

**Assumptions:**
* Both arrays contain 16-bit signed integers.
* **Little-endian** format is used for sample reading/writing. If your samples are big-endian, you must swap `_get_int16_le` and `_set_int16_le` for their `_be` counterparts.

"""
@micropython.viper
def add_int16_array_in_place_viper(
    arr1_ptr: ptr8,      # Pointer to the first bytearray (which will be modified in-place)
    arr1_len_bytes: int, # Byte length of the first bytearray
    arr2_ptr: ptr8,      # Pointer to the second input bytearray
    arr2_len_bytes: int  # Byte length of the second bytearray
):
    """
    Performs element-wise addition of `arr2` into `arr1` (`arr1 += arr2`) directly in memory.
    The result is stored back into `arr1`.
    
    The operation processes samples up to the length of the shortest array.
    
    Args:
        arr1_ptr: Pointer to the first bytearray (the one to be modified).
        arr1_len_bytes: Length of the first bytearray in bytes.
        arr2_ptr: Pointer to the second input bytearray.
        arr2_len_bytes: Length of the second input bytearray in bytes.
    """
    # Fixed to 2 bytes per sample for 16-bit audio.
    BYTES_PER_SAMPLE: int = 2 

    # Calculate lengths in terms of samples.
    arr1_len_samples: int = arr1_len_bytes // BYTES_PER_SAMPLE
    arr2_len_samples: int = arr2_len_bytes // BYTES_PER_SAMPLE

    # Determine the actual number of samples to process, avoiding out-of-bounds access.
    num_samples_to_process: int = arr1_len_samples
    if arr2_len_samples < num_samples_to_process:
        num_samples_to_process = arr2_len_samples

    # Loop through each sample, performing the in-place addition.
    for i in range(num_samples_to_process):
        # Calculate the byte offset for the current sample.
        byte_offset: int = i * BYTES_PER_SAMPLE

        # Read samples from both arrays.
        val1: int = _get_int16_le(arr1_ptr, byte_offset)
        val2: int = _get_int16_le(arr2_ptr, byte_offset)

        # Perform the addition.
        sum_val: int = val1 + val2

        # Write the sum back to the first array (in-place modification).
        _set_int16_le(arr1_ptr, byte_offset, sum_val)

"""
## Viper Core: In-place Array Division (`a //= b`)

This function performs element-wise integer division of an array by a scalar value, modifying the array in place.

**Assumptions:**
* The array contains 16-bit signed integers.
* **Little-endian** format is used for sample reading/writing. If your samples are big-endian, you must swap `_get_int16_le` and `_set_int16_le` for their `_be` counterparts.

"""
@micropython.viper
def divide_int16_array_in_place_viper(
    arr_ptr: ptr8,      # Pointer to the bytearray to be modified (a)
    arr_len_bytes: int, # Byte length of the array (a_len)
    divisor: int        # The integer value to divide each element by (b)
):
    """
    Performs element-wise integer division (`arr[i] //= divisor`) on the array in-place.
    
    This function is optimized for speed using Viper. It includes robust handling
    for division by zero to prevent crashes, typically silencing the output in that case.
    
    Args:
        arr_ptr: Pointer to the bytearray containing 16-bit signed integers.
                 This array will be modified directly.
        arr_len_bytes: The length of the array in bytes.
        divisor: The integer value to divide each element by.
    """
    # Fixed to 2 bytes per sample for 16-bit audio.
    BYTES_PER_SAMPLE: int = 2 

    # Calculate length in terms of samples.
    arr_len_samples: int = arr_len_bytes // BYTES_PER_SAMPLE

    # Critical: Handle division by zero. If the divisor is zero, the array is cleared to zeros
    # (silence) to prevent runtime errors or undefined behavior.
    if int(divisor) == 0:
        for i in range(arr_len_bytes):
            arr_ptr[i] = 0 # Clear the entire bytearray to 0.
        return # Exit the function early

    # Loop through each sample, performing the division.
    for i in range(arr_len_samples):
        # Calculate the byte offset for the current sample.
        byte_offset: int = i * BYTES_PER_SAMPLE

        # Read the sample value from the array.
        val: int = _get_int16_le(arr_ptr, byte_offset)

        # Perform integer division (floor division in Python).
        # Explicit `int()` casts are used to ensure Viper performs the operation with machine integers.
        divided_val: int = int(val) // int(divisor)

        # Write the divided sample back to the array (in-place modification).
        _set_int16_le(arr_ptr, byte_offset, divided_val)
