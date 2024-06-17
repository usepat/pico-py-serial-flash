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

    file_path: str = field(default="pico_log.bin")

    def __post_init__(self):
        self.file = open(self.file_path, 'ab')  # Open the file in binary mode

    def __del__(self):
        if self.file:
            self.file.close()

    def log_to_file(self, message: bytes):
        self.file.write(message + b"\n")

    Opcodes = {
        'Sync': bytes('SYNC', 'utf-8'),
        'Read': bytes('READ', 'utf-8'),
        'Csum': bytes('CSUM', 'utf-8'),
        'CRC': bytes('CRCC', 'utf-8'),
        'Erase': bytes('ERAS', 'utf-8'),
        'Write': bytes('WRIT', 'utf-8'),
        'Seal': bytes('SEAL', 'utf-8'),
        'Go': bytes('GOGO', 'utf-8'),
        'Info': bytes('INFO', 'utf-8'),
        'ResponseSync': bytes('PICO', 'utf-8'),
        'ResponseSyncWota': bytes('WOTA', 'utf-8'),
        'ResponseOK': bytes('OKOK', 'utf-8'),
        'ResponseErr': bytes('ERR!', 'utf-8')
    }

    async def read_bootloader_resp(self, conn, response_len: int, exit_before_flash=True) -> (bytes, bytes):
        await asyncio.sleep(self.wait_time_before_read)
        debug("Start blocking code reponse length is hit. Resp_len: " + str(response_len))
        all_bytes = await conn.read(response_len)
        err_byte = all_bytes.removeprefix(self.Opcodes["ResponseErr"][:])
        data_bytes = bytes()
        if len(err_byte) == response_len:
            data_bytes = all_bytes.removeprefix((self.Opcodes["ResponseOK"][:]))
            debug("No error encoutered")
        else:
            puts("Error encoutered in RPi Pico! Please POR your Pico and try again.")
            exit_prog(exit_before_flash)

        debug("Complete Buff: " + str(all_bytes))
        debug("Data buff: " + str(data_bytes))
        debug("Len Data buff: " + str(len(data_bytes)))
        return all_bytes, data_bytes

    async def sync_cmd(self, conn) -> bool:
        for i in range(1, self.MAX_SYNC_ATTEMPTS + 1):
            response = bytes()
            try:
                debug("Starting sync command by sending: " + str(self.Opcodes["Sync"][:]))
                self.log_to_file(self.Opcodes["Sync"][:])
                conn.write(self.Opcodes["Sync"][:])

                await asyncio.sleep(self.wait_time_before_read)
                debug("Have send Sync command, start reading response")
                while conn.in_waiting > 0:
                    data_byte = await conn.read(conn.in_waiting)
                    response += data_byte

                debug("Whole response has arrived: " + str(response))
                self.log_to_file(response)
                if response == self.Opcodes["ResponseSync"][:]:
                    puts("Found a Pico device who responded to sync.")
                    self.has_sync = True
                    return self.has_sync
                else:
                    puts("No Pico bootloader found that will respond to the sync command. Is your device connected and in bootloader?")
                    exit_prog(True)
            except serial.SerialTimeoutException:
                puts("Serial timeout expired.")
                exit_prog(True)

    async def info_cmd(self, conn) -> PicoInfo:
        expected_len = len(self.Opcodes['ResponseOK']) + (4 * 5)
        conn.write(self.Opcodes["Info"][:])
        self.log_to_file(self.Opcodes["Info"][:])
        debug("Written following bytes to Pico: " + str(self.Opcodes["Info"][:]))
        all_bytes, resp_ok_bytes = await self.read_bootloader_resp(conn, expected_len, True)
        self.log_to_file(all_bytes)
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

    async def erase_cmd(self, conn, addr, length) -> bool:
        expected_bit_n = 3 * 4
        write_buff = bytes()
        write_buff += self.Opcodes['Erase'][:]
        write_buff += little_end_uint32_to_bytes(addr)
        write_buff += little_end_uint32_to_bytes(length)
        if len(write_buff) != expected_bit_n:
            missing_bits = expected_bit_n - len(write_buff)
            b = bytes(missing_bits)
            write_buff += b
        n = conn.write(write_buff)
        self.log_to_file(write_buff)
        debug("Number of bytes written: " + str(n))
        await asyncio.sleep(self.wait_time_before_read)
        all_bytes, resp_ok_bytes = await self.read_bootloader_resp(conn, len(self.Opcodes['ResponseOK']), True)
        self.log_to_file(all_bytes)
        debug("Erased a length of bytes, response is: " + str(all_bytes))
        if all_bytes != self.Opcodes['ResponseOK']:
            return False
        return True

    async def write_cmd(self, conn, addr, length, data):
        expected_bit_n_no_data = len(self.Opcodes['Write']) + 4 + 4
        write_buff = bytes()
        write_buff += self.Opcodes['Write'][:]
        write_buff += little_end_uint32_to_bytes(addr)
        write_buff += little_end_uint32_to_bytes(length)
        len_before_data = len(write_buff)
        if len_before_data != expected_bit_n_no_data:
            missing_bits = expected_bit_n_no_data - len_before_data
            b = bytes(missing_bits)
            write_buff += b
        write_buff += data
        n = conn.write(write_buff)
        self.log_to_file(write_buff)
        debug("Number of bytes written: " + str(n))
        await asyncio.sleep(self.wait_time_before_read)
        all_bytes, data_bytes = await self.read_bootloader_resp(conn, len(self.Opcodes['ResponseOK']) + 4, True)
        self.log_to_file(all_bytes)
        debug("All bytes return from read: " + str(all_bytes))
        resp_crc = bytes_to_little_end_uint32(data_bytes)
        calc_crc = binascii.crc32(data)

        if resp_crc != calc_crc:
            return False
        return True

    async def seal_cmd(self, conn, addr, data):
        expected_bits_before_crc = len(self.Opcodes['Seal']) + 4 + 4
        data_length = len(data)
        crc = binascii.crc32(data)
        write_buff = bytes()
        write_buff += self.Opcodes['Seal'][:]
        write_buff += little_end_uint32_to_bytes(addr)
        write_buff += little_end_uint32_to_bytes(data_length)
        len_before_data = len(write_buff)
        if len_before_data != expected_bits_before_crc:
            missing_bits = expected_bits_before_crc - len_before_data
            b = bytes(missing_bits)
            write_buff += b
        write_buff += little_end_uint32_to_bytes(crc)
        wr_buff_read = hex_bytes_to_int(write_buff)
        n = conn.write(write_buff)
        self.log_to_file(write_buff)
        debug("Number of bytes written: " + str(n))
        await asyncio.sleep(self.wait_time_before_read)
        all_bytes, data_bytes = await self.read_bootloader_resp(conn, len(self.Opcodes['ResponseOK']), False)
        self.log_to_file(all_bytes)
        debug("All bytes seal: " + str(all_bytes))
        if all_bytes[:4] != self.Opcodes['ResponseOK']:
            return False
        return True

    async def go_to_application_cmd(self, conn, addr):
        expected_bit_n = len(self.Opcodes['Go']) + 4
        write_buff = bytes()
        write_buff += self.Opcodes['Go'][:]
        write_buff += little_end_uint32_to_bytes(addr)
        if len(write_buff) != expected_bit_n:
            missing_bits = expected_bit_n - len(write_buff)
            b = bytes(missing_bits)
            write_buff += b
        write_readable = hex_bytes_to_int(write_buff)
        n = conn.write(write_buff)
        self.log_to_file(write_buff)
        debug("Go.")