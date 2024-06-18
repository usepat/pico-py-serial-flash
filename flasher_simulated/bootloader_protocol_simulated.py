import time
import asyncio
import serial_asyncio
import serial
import binascii
from dataclasses import dataclass, field
from flasher_simulated.util import debug, puts, exit_prog, hex_bytes_to_int, bytes_to_little_end_uint32, little_end_uint32_to_bytes


@dataclass
class PicoInfo:
    flash_addr: int
    flash_size: int
    erase_size: int
    write_size: int
    max_data_len: int


@dataclass
class Protocol_RP2040:
    MAX_SYNC_ATTEMPTS: int = 1
    has_sync: bool = False
    wait_time_before_read: float = 0.05  # seconds

    plc_output_bin: str = field(default="plc_output.bin")
    plc_output_txt: str = field(default="plc_output.txt")
    
    device_output_bin: str = field(default="device_output.bin")
    device_output_txt: str = field(default="device_output.txt")

    plc_device_output_bin: str = field(default="plc_device_output.bin")
    plc_device_output_txt: str = field(default="plc_device_output.txt")

    def __post_init__(self):
        self.plc_bin = open(self.plc_output_bin, 'wb')  # Open the file in binary mode
        self.plc_txt = open(self.plc_output_txt, 'w')  # Open the file in binary mode
        self.device_bin = open(self.device_output_bin, 'wb')  # Open the file in binary mode
        self.device_txt = open(self.device_output_txt, 'w')  # Open the file in binary mode
        self.plc_device_bin = open(self.plc_device_output_bin, 'wb')  # Open the file in binary mode
        self.plc_device_txt = open(self.plc_device_output_txt, 'w')  # Open the file in binary mode


    def __del__(self):
        if self.plc_bin:
            self.plc_bin.close()
        if self.plc_txt:
            self.plc_txt.close()
        if self.device_bin:
            self.device_bin.close()
        if self.device_txt:
            self.device_txt.close()
        if self.plc_device_bin:
            self.plc_device_bin.close()
        if self.plc_device_txt:
            self.plc_device_txt.close()

    def log_device_plc_output(self, message: bytes):
        self.plc_device_bin.write(message + b"\n")
        self.plc_device_txt.write(str(message) + "\n")

    def log_plc_output(self, message: bytes):
        self.log_device_plc_output(message)
        self.plc_bin.write(message + b"\n")
        self.plc_txt.write(str(message) + "\n")

    def log_device_output(self, message: bytes):
        self.log_device_plc_output(message)
        self.device_bin.write(message + b"\n")
        self.device_txt.write(str(message) + "\n")

    Opcodes = {
        'Sync': b'SYNC',
        'Read': b'READ',
        'Csum': b'CSUM',
        'CRC': b'CRCC',
        'Erase': b'ERAS',
        'Write': b'WRIT',
        'Seal': b'SEAL',
        'Go': b'GOGO',
        'Info': b'INFO',
        'ResponseSync': b'PICO',
        'ResponseSyncWota': b'WOTA',
        'ResponseOK': b'OKOK',
        'ResponseErr': b'ERR!',
    }

    async def read_bootloader_resp(self, reader, response_len: int, exit_before_flash=True) -> (bytes, bytes):
        await asyncio.sleep(self.wait_time_before_read)
        debug("Start blocking code reponse length is hit. Resp_len: " + str(response_len))
        all_bytes = await reader.read(response_len)
        err_byte = all_bytes.removeprefix(self.Opcodes["ResponseErr"])
        data_bytes = bytes()
        if len(err_byte) == response_len:
            data_bytes = all_bytes.removeprefix(self.Opcodes["ResponseOK"])
            debug("No error encoutered")
        else:
            puts("Error encoutered in RPi Pico! Please POR your Pico and try again.")
            exit_prog(exit_before_flash)

        debug("Complete Buff: " + str(all_bytes))
        debug("Data buff: " + str(data_bytes))
        debug("Len Data buff: " + str(len(data_bytes)))
        return all_bytes, data_bytes

    async def sync_cmd(self, reader, writer) -> bool:
        for i in range(1, self.MAX_SYNC_ATTEMPTS + 1):
            response = bytes()
            try:
                debug("Starting sync command by sending: " + str(self.Opcodes["Sync"]))
                self.log_plc_output(self.Opcodes["Sync"])
                writer.write(self.Opcodes["Sync"])
                await writer.drain()

                await asyncio.sleep(self.wait_time_before_read)
                debug("Have send Sync command, start reading response")
                response = await reader.read(4)

                debug("Whole response has arrived: " + str(response))
                self.log_device_output(response)
                if response == self.Opcodes["ResponseSync"]:
                    puts("Found a Pico device who responded to sync.")
                    self.has_sync = True
                    return self.has_sync
                else:
                    puts("No Pico bootloader found that will respond to the sync command. Is your device connected and in bootloader?")
                    exit_prog(True)
            except serial.SerialTimeoutException:
                puts("Serial timeout expired.")
                exit_prog(True)

    async def info_cmd(self, reader, writer) -> PicoInfo:
        expected_len = len(self.Opcodes['ResponseOK']) + (4 * 5)
        writer.write(self.Opcodes["Info"])
        await writer.drain()
        self.log_plc_output(self.Opcodes["Info"])
        debug("Written following bytes to Pico: " + str(self.Opcodes["Info"]))
        all_bytes, resp_ok_bytes = await self.read_bootloader_resp(reader, expected_len, True)
        self.log_device_output(all_bytes)
        decoded_arr = []
        if len(resp_ok_bytes) <= 0:
            puts("Something went horribly wrong. Please POR and retry.")
            exit_prog(True)
        else:
            decoded_arr = hex_bytes_to_int(resp_ok_bytes)
            debug("Decoded data array: " + str(decoded_arr))

        flash_addr = bytes_to_little_end_uint32(resp_ok_bytes)
        flash_size = bytes_to_little_end_uint32(resp_ok_bytes[4:])
        erase_size = bytes_to_little_end_uint32(resp_ok_bytes[8:])
        write_size = bytes_to_little_end_uint32(resp_ok_bytes[12:])
        max_data_len = bytes_to_little_end_uint32(resp_ok_bytes[16:])
        this_pico_info = PicoInfo(flash_addr, flash_size, erase_size, write_size, max_data_len)

        debug("flash_addr: " + str(flash_addr))
        debug("flash_size: " + str(flash_size))
        debug("erase_size: " + str(erase_size))
        debug("write_size: " + str(write_size))
        debug("max_data_len: " + str(max_data_len))

        return this_pico_info

    async def erase_cmd(self, reader, writer, addr, length) -> bool:
        expected_bit_n = 3 * 4
        write_buff = bytes()
        write_buff += self.Opcodes['Erase']
        write_buff += little_end_uint32_to_bytes(addr)
        write_buff += little_end_uint32_to_bytes(length)
        if len(write_buff) != expected_bit_n:
            missing_bits = expected_bit_n - len(write_buff)
            b = bytes(missing_bits)
            write_buff += b
        writer.write(write_buff)
        await writer.drain()
        self.log_plc_output(write_buff)
        debug("Number of bytes written: " + str(len(write_buff)))
        await asyncio.sleep(self.wait_time_before_read)
        all_bytes, resp_ok_bytes = await self.read_bootloader_resp(reader, len(self.Opcodes['ResponseOK']), True)
        self.log_device_output(all_bytes)
        debug("Erased a length of bytes, response is: " + str(all_bytes))
        if all_bytes != self.Opcodes['ResponseOK']:
            return False
        return True

    async def write_cmd(self, reader, writer, addr, length, data):
        expected_bit_n_no_data = len(self.Opcodes['Write']) + 4 + 4
        write_buff = bytes()
        write_buff += self.Opcodes['Write']
        write_buff += little_end_uint32_to_bytes(addr)
        write_buff += little_end_uint32_to_bytes(length)
        len_before_data = len(write_buff)
        if len_before_data != expected_bit_n_no_data:
            missing_bits = expected_bit_n_no_data - len_before_data
            b = bytes(missing_bits)
            write_buff += b
        write_buff += data
        writer.write(write_buff)
        await writer.drain()
        self.log_plc_output(write_buff)
        debug("Number of bytes written: " + str(len(write_buff)))
        await asyncio.sleep(self.wait_time_before_read)
        all_bytes, data_bytes = await self.read_bootloader_resp(reader, len(self.Opcodes['ResponseOK']) + 4, True)
        self.log_device_output(all_bytes)
        debug("All bytes return from read: " + str(all_bytes))
        resp_crc = bytes_to_little_end_uint32(data_bytes)
        calc_crc = binascii.crc32(data)

        if resp_crc != calc_crc:
            return False
        return True

    async def seal_cmd(self, reader, writer, addr, data):
        expected_bits_before_crc = len(self.Opcodes['Seal']) + 4 + 4
        data_length = len(data)
        crc = binascii.crc32(data)
        write_buff = bytes()
        write_buff += self.Opcodes['Seal']
        write_buff += little_end_uint32_to_bytes(addr)
        write_buff += little_end_uint32_to_bytes(data_length)
        len_before_data = len(write_buff)
        if len_before_data != expected_bits_before_crc:
            missing_bits = expected_bits_before_crc - len_before_data
            b = bytes(missing_bits)
            write_buff += b
        write_buff += little_end_uint32_to_bytes(crc)
        wr_buff_read = hex_bytes_to_int(write_buff)
        writer.write(write_buff)
        await writer.drain()
        self.log_plc_output(write_buff)
        debug("Number of bytes written: " + str(len(write_buff)))
        await asyncio.sleep(self.wait_time_before_read)
        all_bytes, data_bytes = await self.read_bootloader_resp(reader, len(self.Opcodes['ResponseOK']), False)
        self.log_device_output(all_bytes)
        debug("All bytes seal: " + str(all_bytes))
        if all_bytes[:4] != self.Opcodes['ResponseOK']:
            return False
        return True

    async def go_to_application_cmd(self, reader, writer, addr):
        expected_bit_n = len(self.Opcodes['Go']) + 4
        write_buff = bytes()
        write_buff += self.Opcodes['Go']
        write_buff += little_end_uint32_to_bytes(addr)
        if len(write_buff) != expected_bit_n:
            missing_bits = expected_bit_n - len(write_buff)
            b = bytes(missing_bits)
            write_buff += b
        write_readable = hex_bytes_to_int(write_buff)
        self.log_plc_output(write_buff)
        writer.write(write_buff)
        await writer.drain()
        debug("Go.")
