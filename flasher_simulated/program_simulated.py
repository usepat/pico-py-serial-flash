from dataclasses import dataclass
from flasher_simulated.util import debug, puts, exit_prog, hex_bytes_to_int
from flasher_simulated.bootloader_protocol_simulated import Protocol_RP2040


@dataclass
class Image:
    Addr: int = -1
    Data: bytes = None


@dataclass
class ProgressReport:
    Stage: str
    Progress: int
    Max: int


def align(val, to):
    return (val + (to - 1)) & ~(to - 1)


async def Program(reader, writer, image: Image, progress_bar):
    # Normal RP2040 (not wireless) protocol
    protocol = Protocol_RP2040()

    # Check if there is a Pico device connected, ready to be flashed
    has_sync = await protocol.sync_cmd(reader, writer)
    if not has_sync:
        puts("No Pico device to get in sync with.")
        exit_prog()

    # Receive information about flash size, and address offsets
    device_info = await protocol.info_cmd(reader, writer)

    # Pad the image data message
    pad_len = align(int(len(image.Data)), device_info.write_size) - int(len(image.Data))
    pad_zeros = bytes(pad_len)
    data = image.Data + pad_zeros

    debug("pad_len: " + str(pad_len))
    debug("pad_zeros: " + str(hex_bytes_to_int(pad_zeros)))

    if image.Addr < device_info.flash_addr:
        puts("Image load address is too low: " + str(hex(image.Addr)) + " < " + str(hex(device_info.flash_addr)))
        exit_prog(True)

    if image.Addr + int(len(data)) > device_info.flash_addr + device_info.flash_size:
        puts("Image of " + str(len(data)) + " bytes does not fit in target flash at: " + str(hex(image.Addr)))
        exit_prog(True)

    puts("Starting erase.")

    # Check how many bytes we need to erase, and start erasing.
    erase_len = int(align(len(data), device_info.erase_size))
    for start in range(0, erase_len, device_info.erase_size):
        debug("Erase: " + str(start))
        erase_addr = image.Addr + start
        has_succeeded = await protocol.erase_cmd(reader, writer, erase_addr, device_info.erase_size)
        if not has_succeeded:
            puts("Error when erasing flash, at addr: " + str(erase_addr))
            exit_prog(True)

    puts("Erase completed.")

    puts("Starting flash.")
    # Start write
    for start in range(0, len(data), device_info.max_data_len):
        end = start + device_info.max_data_len
        if end > int(len(data)):
            end = int(len(data))

        wr_addr = image.Addr + start
        wr_len = end - start
        wr_data = data[start:end]
        crc_valid = await protocol.write_cmd(reader, writer, wr_addr, wr_len, wr_data)
        if not crc_valid:
            puts("CRC mismatch! Exiting.")
            exit_prog(False)

    puts("Flashing completed.")

    puts("Adding seal to finalize.")
    has_sealed = await protocol.seal_cmd(reader, writer, image.Addr, data)
    debug("Has sealed: " + str(has_sealed))
    if not has_sealed:
        puts("Sealing failed. Exiting.")
        exit_prog(False)

    await protocol.go_to_application_cmd(reader, writer, image.Addr)

    debug("Program is done.")
