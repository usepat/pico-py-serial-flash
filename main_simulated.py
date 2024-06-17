import sys
import traceback
import os
import asyncio
import serial_asyncio
from flasher_simulated.elf import load_elf
from flasher_simulated.util import debug, puts, usage_flasher, exit_prog
from flasher_simulated.program_simulated import Image, Program
import serial


# Called at start of main(), to catch program arguments and respond accordingly.
def handle_args():
    _sys_args = sys.argv[1:]
    debug("All args: " + str(_sys_args))
    debug("Len args: " + str(len(_sys_args)))
    if len(_sys_args) != 1:
        return -1
    else:
        return _sys_args


# Runs the flasher program
async def run(_sys_args):
    global bin_found, img
    if _sys_args == -1:
        puts(usage_flasher())
        exit_prog(True)

    file_path = str(_sys_args[0])
    filename, file_extension = os.path.splitext(file_path)

    if file_extension == ".elf":
        debug("Elf found!: " + str(file_extension))
        img = load_elf(file_path)
        debug("ELF Image Data List Length: " + str(len(img.Data)))
        debug("")
    else:
        puts("Incorrect file extension. Currently supported extensions are: '.elf'.")
        exit_prog(True)

    conn = None

    if img.Data is None or img.Addr <= -1:
        puts("Image file has not been read correctly.")
        exit_prog(True)

    try:
        loop = asyncio.get_running_loop()
        conn, protocol = await serial_asyncio.create_serial_connection(loop, SerialProtocol, '127.0.0.1', 8888)
    except ValueError as e:
        puts("Serial parameters out of range, with exception: " + str(e))
        exit_prog(True)
    except serial.SerialException as s_e:
        puts("Serial Exception. Serial port probably not available: " + str(s_e))
        exit_prog(True)

    puts("Image file has been read correctly.")
    await Program(protocol, img, None)

    conn.close()


class SerialProtocol(asyncio.Protocol):
    def __init__(self):
        self.buffer = bytearray()
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.buffer.extend(data)

    def write(self, data):
        if self.transport is not None:
            self.transport.write(data)

    async def read(self, n=-1):
        while len(self.buffer) < n:
            await asyncio.sleep(0.01)
        data = self.buffer[:n]
        self.buffer = self.buffer[n:]
        return data

    @property
    def in_waiting(self):
        return len(self.buffer)


# Module level global definitions
bin_found: bool = False
img: Image

# Main of the program, handles args and captures the run function in try except clauses
# to be able to easily catch errors
if __name__ == '__main__':
    sys_args = handle_args()
    try:
        asyncio.run(run(sys_args))
        puts("\nJobs done. Pico should have rebooted into the flashed application.")
    except TypeError as err:
        print(err)
        puts(usage_flasher())
    except OSError as err:
        puts("OS error: {0}".format(err))
    except ValueError as err:
        puts("Value error, with error: " + str(err))
    except Exception:
        puts("Unexpected error: ", sys.exc_info()[0])
        puts(traceback.print_exc())
        raise
