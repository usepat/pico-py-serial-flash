import sys
import os
import asyncio
import binascii
from flasher.elf import load_elf
from flasher.util import debug, puts, usage_flasher, exit_prog
from flasher_simulated.program_simulated import Image, Program

async def simulated_device(reader, writer):
    async def usb_read_blocking(length):
        return await reader.readexactly(length)

    async def usb_write_blocking(data):
        writer.write(data)
        await writer.drain()

    async def state_wait_for_sync(ctx):
        idx = 0
        recv = bytearray(4)
        match = b'SYNC'

        while idx < 4:
            recv[idx:idx + 1] = await usb_read_blocking(1)
            if recv[idx:idx + 1] != match[idx:idx + 1]:
                idx = 0
            else:
                idx += 1

        ctx['opcode'] = int.from_bytes(recv, 'little')
        await usb_write_blocking(b'PICO')
        return 'READ_OPCODE'

    async def state_read_opcode(ctx):
        ctx['opcode'] = int.from_bytes(await usb_read_blocking(4), 'little')
        return 'READ_ARGS'

    async def state_read_args(ctx):
        desc = next((cmd for cmd in cmds if cmd['opcode'] == ctx['opcode']), None)
        if not desc:
            ctx['status'] = RSP_ERR
            return 'ERROR'
        
        ctx['desc'] = desc
        ctx['args'] = [int.from_bytes(await usb_read_blocking(4), 'little') for _ in range(desc['nargs'])]
        ctx['data'] = bytearray()
        return 'READ_DATA'

    async def state_read_data(ctx):
        desc = ctx['desc']
        if desc['size']:
            ctx['status'], ctx['data_len'], ctx['resp_data_len'] = desc['size'](ctx['args'])
            if is_error(ctx['status']):
                return 'ERROR'
        else:
            ctx['data_len'] = 0
            ctx['resp_data_len'] = 0
        
        if ctx['data_len']:
            ctx['data'] = await usb_read_blocking(ctx['data_len'])
        return 'HANDLE_DATA'

    async def state_handle_data(ctx):
        desc = ctx['desc']
        if desc['handle']:
            ctx['status'], ctx['resp_args'], ctx['resp_data'] = desc['handle'](ctx['args'], ctx['data'])
            if is_error(ctx['status']):
                return 'ERROR'
        else:
            ctx['status'] = RSP_OK
        
        resp = ctx['status'].to_bytes(4, 'little')
        for arg in ctx['resp_args']:
            resp += arg.to_bytes(4, 'little')
        resp += ctx['resp_data']
        await usb_write_blocking(resp)
        if ctx['opcode'] == int.from_bytes(b'GOGO', 'little'):
            os._exit(0)
        return 'READ_OPCODE'

    async def state_error(ctx):
        await usb_write_blocking(ctx['status'].to_bytes(4, 'little'))
        return 'WAIT_FOR_SYNC'

    states = {
        'WAIT_FOR_SYNC': state_wait_for_sync,
        'READ_OPCODE': state_read_opcode,
        'READ_ARGS': state_read_args,
        'READ_DATA': state_read_data,
        'HANDLE_DATA': state_handle_data,
        'ERROR': state_error,
    }

    cmds = [
        {
            'opcode': int.from_bytes(b'SYNC', 'little'),
            'nargs': 0,
            'resp_nargs': 0,
            'size': None,
            'handle': lambda args, data: (RSP_SYNC, [], b'')
        },
        {
            'opcode': int.from_bytes(b'READ', 'little'),
            'nargs': 2,
            'resp_nargs': 0,
            'size': lambda args: (RSP_OK, 0, args[1]),
            'handle': lambda args, data: (RSP_OK, [], flash_memory[args[0]:args[0]+args[1]])
        },
        {
            'opcode': int.from_bytes(b'ERAS', 'little'),
            'nargs': 2,
            'resp_nargs': 0,
            'size': None,
            'handle': lambda args, data: (
                RSP_OK,
                [],
                (flash_memory.__setitem__(slice(args[0], args[0] + args[1]), b'\xff' * args[1]) or b'')
            )
        },
        {
            'opcode': int.from_bytes(b'WRIT', 'little'),
            'nargs': 2,
            'resp_nargs': 1,
            'size': lambda args: (RSP_OK, args[1], 0),
            'handle': lambda args, data: (
                RSP_OK,
                [binascii.crc32(data)],
                (flash_memory[args[0]:args[0]+args[1]] == data and b'') or (flash_memory.__setitem__(slice(args[0], args[0]+args[1]), data) or b'')
            )
        },
        {
            'opcode': int.from_bytes(b'SEAL', 'little'),
            'nargs': 3,
            'resp_nargs': 0,
            'size': None,
            'handle': lambda args, data: (RSP_OK, [], b'')
        },
        {
            'opcode': int.from_bytes(b'INFO', 'little'),
            'nargs': 0,
            'resp_nargs': 5,
            'size': None,
            'handle': lambda args, data: (
                RSP_OK,
                [0x10000000, len(flash_memory), 0x1000, 0x100, 0x100],
                b''
            )
        },
        {
            'opcode': int.from_bytes(b'GOGO', 'little'),
            'nargs': 0,
            'resp_nargs': 0,
            'size': None,
            'handle': lambda args, data: (RSP_OK, [], b'')
        },
    ]

    RSP_SYNC = int.from_bytes(b'PICO', 'little')
    RSP_OK = int.from_bytes(b'OKOK', 'little')
    RSP_ERR = int.from_bytes(b'ERR!', 'little')

    def is_error(status):
        return status == RSP_ERR

    flash_memory = bytearray(16 * 1024 * 1024)  # 16MB flash

    ctx = {
        'opcode': 0,
        'status': 0,
        'desc': None,
        'args': [],
        'data': bytearray(),
        'resp_args': [],
        'resp_data': bytearray(),
        'data_len': 0,
        'resp_data_len': 0,
    }
    state = 'WAIT_FOR_SYNC'

    while True:
        state = await states[state](ctx)

async def run_flash_program(reader, writer, img):
    await Program(reader, writer, Image(Addr=0x10000000, Data=img.Data), None)

async def main():
    if len(sys.argv) != 2:
        print("Usage: main_simulated.py <path to ELF file>")
        sys.exit(1)

    elf_path = sys.argv[1]
    img = load_elf(elf_path)

    server = await asyncio.start_server(simulated_device, '127.0.0.1', 8888)
    await asyncio.sleep(1)  # Give the server a moment to start

    device_reader, device_writer = await asyncio.open_connection('127.0.0.1', 8888)
    flash_task = asyncio.create_task(run_flash_program(device_reader, device_writer, img))

    await flash_task

if __name__ == '__main__':
    asyncio.run(main())
