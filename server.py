import asyncio
from bleak import BleakClient
from Crypto.Cipher import AES
import websockets   # 🔌 WEBSOCKET

# === Config de tu cubo ===
CUBE_MAC = "CC:A3:00:00:88:D4"
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_UUID    = "0000fff6-0000-1000-8000-00805f9b34fb"

# === Clave AES (misma que en el JS) ===
AES_KEY = bytes([87, 177, 249, 171, 205, 90, 232, 167,
                 156, 185, 140, 231, 87, 140, 81, 8])

# ====== Utilidades criptográficas / protocolo (1:1 con el JS) ======

move_map = {
    1:"L'", 2:"L", 3:"R'", 4:"R", 5:"D'", 6:"D", 
    7:"U'", 8:"U", 9:"F'", 10:"F", 11:"B'", 12:"B",
} 

def encrypt_message(raw: bytes) -> bytes:
    if len(raw) % 16 != 0:
        raw = raw + bytes(16 - (len(raw) % 16))
    aes = AES.new(AES_KEY, AES.MODE_ECB)
    out = bytearray()
    for i in range(0, len(raw), 16):
        out += aes.encrypt(raw[i:i+16])
    return bytes(out)

def decrypt_message(enc: bytes) -> bytes:
    aes = AES.new(AES_KEY, AES.MODE_ECB)
    out = bytearray()
    for i in range(0, len(enc), 16):
        out += aes.decrypt(enc[i:i+16])
    return bytes(out)

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if (crc & 1) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc

def build_app_hello(mac_reversed: bytes) -> bytes:
    data = bytearray(19)
    data[11:11+6] = mac_reversed
    return bytes(data)

def build_ack_body_from_message(decrypted: bytes) -> bytes:
    ack_head = decrypted[2:7]
    ack = bytearray(7)
    ack[0] = 0xFE
    ack[1] = 9
    ack[2:7] = ack_head
    crc = crc16_modbus(ack[:7])
    full = bytearray(9)
    full[:7] = ack
    full[7] = crc & 0xFF
    full[8] = (crc >> 8) & 0xFF
    return bytes(full)

def build_encrypted_message_from_body(body: bytes) -> bytes:
    length = len(body) + 2
    msg = bytearray(length)
    msg[0] = 0xFE
    msg[1] = length
    msg[2:2+len(body)] = body
    crc = crc16_modbus(msg[:length-2])
    msg[length-2] = crc & 0xFF
    msg[length-1] = (crc >> 8) & 0xFF
    return encrypt_message(bytes(msg))

def parse_cube_state(raw27to54: bytes):
    colors = []
    for b in raw27to54[:27]:
        colors.append(b & 0x0F)
        colors.append((b >> 4) & 0x0F)
    return colors

# 🔌 WEBSOCKET - gestión de clientes
clientes = set()

async def ws_handler(websocket):
    print("🌐 Cliente WebSocket conectado")
    clientes.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clientes.remove(websocket)
        print("❌ Cliente WebSocket desconectado")

async def enviar_a_clientes(mensaje: str):
    if clientes:
        await asyncio.gather(*[c.send(mensaje) for c in clientes])

# ====== Lógica BLE ======

async def main():
    mac_bytes = bytes(int(h, 16) for h in CUBE_MAC.split(":"))
    mac_reversed = mac_bytes[::-1]

    queue = asyncio.Queue()

    def notification_handler(sender: int, data: bytearray):
        decrypted = decrypt_message(bytes(data))
        #print("🔹 RX enc :", data.hex())
        #print("🔹 RX dec :", decrypted.hex())
        queue.put_nowait(decrypted)

    async with BleakClient(CUBE_MAC) as client:
        print("✅ Conectado a", CUBE_MAC)

        await client.start_notify(CHAR_UUID, notification_handler)
        print("📡 Notificaciones activadas en FFF6.")

        app_hello_body = build_app_hello(mac_reversed)
        enc = build_encrypted_message_from_body(app_hello_body)
        await client.write_gatt_char(CHAR_UUID, enc, response=False)
        print("📤 App Hello enviado.")

        async def processor():
            while True:
                decrypted = await queue.get()
                try:
                    if len(decrypted) < 3 or decrypted[0] != 0xFE:
                        continue

                    msg_type = decrypted[2]
                    if msg_type == 0x02:
                        if len(decrypted) >= 36:
                            state = parse_cube_state(decrypted[7:34])
                            battery = decrypted[35]
                            #print(f"🔋 Battery: {battery}% | state_len={len(state)}")
                        ack_full = build_ack_body_from_message(decrypted)
                        enc_ack = build_encrypted_message_from_body(ack_full[2:])
                        await client.write_gatt_char(CHAR_UUID, enc_ack, response=False)
                       # print("✅ ACK a Cube Hello enviado.")

                    elif msg_type == 0x03:
                        move = decrypted[34] if len(decrypted) > 34 else None
                        battery = decrypted[35] if len(decrypted) > 35 else None
                        needs_ack = (len(decrypted) > 91 and decrypted[91] == 1)
                        if move and move in move_map:
                            movimiento = move_map[int(move)]
                            #print(f"↪️ Move={move} {movimiento} | 🔋={battery}% | needsAck={needs_ack}")
                            print(f"Letra =  {movimiento}, Bateria = {battery}%")
                            # 🔌 Enviar movimiento al WebSocket
                            asyncio.create_task(enviar_a_clientes(movimiento))
                        if needs_ack:
                            ack_full = build_ack_body_from_message(decrypted)
                            enc_ack = build_encrypted_message_from_body(ack_full[2:])
                            await client.write_gatt_char(CHAR_UUID, enc_ack, response=False)
                            #print("✅ ACK a State Change enviado.")

                    elif msg_type == 0x04:
                        if len(decrypted) >= 34:
                            state = parse_cube_state(decrypted[7:34])
                            #print(f"🔄 Sync state recibido | state_len={len(state)}")

                finally:
                    queue.task_done()

        task = asyncio.create_task(processor())

        # 🔌 Ejecutar servidor WebSocket en paralelo
        ws_server = await websockets.serve(ws_handler, "0.0.0.0", 8765)
        print("🚀 Servidor WebSocket en ws://0.0.0.0:8765")

        try:
            await asyncio.sleep(3600)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await client.stop_notify(CHAR_UUID)
            ws_server.close()
            await ws_server.wait_closed()

# --- Ejecutar ---
if __name__ == "__main__":
    import contextlib
    asyncio.run(main())
