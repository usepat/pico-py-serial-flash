import asyncio
import struct
import binascii

class SimulatedDevice(asyncio.Protocol):
    def __init__(self):
        self.buffer = bytearray()
        self.state = 'WAIT_FOR_SYNC'

    def connection_made(self, transport):
        self.transport = transport
        print("Connection made with simulated device")

    def data_received(self, data):
        self.buffer.extend(data)
        while self.buffer:
            if self.state == 'WAIT_FOR_SYNC':
                self.handle_wait_for_sync()
            elif self.state == 'READ_OPCODE':
                self.handle_read_opcode()
            elif self.state == 'READ_ARGS':
                self.handle_read_args()
            elif self.state == 'READ_DATA':
                self.handle_read_data()
            elif self.state == 'HANDLE_DATA':
                self.handle_handle_data()
            elif self.state == 'ERROR':
                self.handle_error()

    def handle_wait_for_sync(self):
        if len(self.buffer) >= 4:
            opcode = struct.unpack('<I', self.buffer[:4])[0]
            self.buffer = self.buffer[4:]
            if opcode == 0x43594e53:  # CMD_SYNC
                response = struct.pack('<I', 0x4f4b4f4b)  # RSP_OK
                self.transport.write(response)
                self.state = 'READ_OPCODE'
            else:
                self.state = 'ERROR'

    def handle_read_opcode(self):
        if len(self.buffer) >= 4:
            self.opcode = struct.unpack('<I', self.buffer[:4])[0]
            self.buffer = self.buffer[4:]
            self.state = 'READ_ARGS'

    def handle_read_args(self):
        if self.opcode in (0x52414544, 0x4353554d, 0x43524343, 0x45524153, 0x57524954, 0x5345414c, 0x474f474f, 0x494e464f):  # Read, Csum, Crc, Erase, Write, Seal, Go, Info
            if len(self.buffer) >= 8:
                self.args = struct.unpack('<II', self.buffer[:8])
                self.buffer = self.buffer[8:]
                if self.opcode == 0x52414544:  # CMD_READ
                    self.state = 'HANDLE_DATA'
                else:
                    self.state = 'READ_DATA'
            else:
                self.state = 'ERROR'
        else:
            self.state = 'ERROR'

    def handle_read_data(self):
        # Handle data length based on opcode if necessary
        if self.opcode == 0x57524954:  # CMD_WRITE
            data_len = self.args[1]
            if len(self.buffer) >= data_len:
                self.data = self.buffer[:data_len]
                self.buffer = self.buffer[data_len:]
                self.state = 'HANDLE_DATA'
            else:
                self.state = 'ERROR'
        else:
            self.state = 'HANDLE_DATA'

    def handle_handle_data(self):
        if self.opcode == 0x52414544:  # CMD_READ
            addr, length = self.args
            response = struct.pack('<I', 0x4f4b4f4b) + bytes([0]*length)
            self.transport.write(response)
        elif self.opcode == 0x494e464f:  # CMD_INFO
            response = struct.pack('<I', 0x4f4b4f4b) + struct.pack('<IIIII', 0x10000, 0x1000000 - 0x10000, 0x1000, 0x100, 0x400)
            self.transport.write(response)
        elif self.opcode == 0x57524954:  # CMD_WRITE
            addr, length = self.args
            crc32 = binascii.crc32(self.data)
            response = struct.pack('<I', 0x4f4b4f4b) + struct.pack('<I', crc32)
            self.transport.write(response)
        else:
            response = struct.pack('<I', 0x45525221)  # RSP_ERR
            self.transport.write(response)
        self.state = 'READ_OPCODE'

    def handle_error(self):
        response = struct.pack('<I', 0x45525221)  # RSP_ERR
        self.transport.write(response)
        self.state = 'WAIT_FOR_SYNC'

async def main():
    loop = asyncio.get_running_loop()
    server = await loop.create_server(lambda: SimulatedDevice(), '127.0.0.1', 8888)
    print("Created server")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
