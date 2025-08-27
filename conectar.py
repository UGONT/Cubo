import asyncio
from bleak import BleakClient
from Crypto.Cipher import AES

# === Config de tu cubo ===
CUBE_MAC = "CC:A3:00:00:88:D4"
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_UUID    = "0000fff6-0000-1000-8000-00805f9b34fb"

# === Clave AES (misma que en el JS) ===
AES_KEY = bytes([87, 177, 249, 171, 205, 90, 232, 167, 
                 156, 185, 140, 231, 87, 140, 81, 8])

# ==== Diccionario de movimientos ======

move_map = {
    1:"L'",
    2:"L",
    3:"R'",
    4:"R",
    5:"D'",
    6:"D",
    7:"U'",
    8:"U",
    9:"F'",
    10:"F",
    11:"B'",
    12:"B",
} 

# ====== Utilidades criptográficas / protocolo (1:1 con el JS) ======

def encrypt_message(raw: bytes) -> bytes:
    """AES-ECB con padding de 0x00 a múltiplos de 16."""
    if len(raw) % 16 != 0:
        raw = raw + bytes(16 - (len(raw) % 16))
    aes = AES.new(AES_KEY, AES.MODE_ECB)
    out = bytearray()
    for i in range(0, len(raw), 16):
        out += aes.encrypt(raw[i:i+16])
    return bytes(out)

def decrypt_message(enc: bytes) -> bytes:
    """AES-ECB bloque a bloque ."""
    aes = AES.new(AES_KEY, AES.MODE_ECB)
    out = bytearray()
    for i in range(0, len(enc), 16):
        out += aes.decrypt(enc[i:i+16])
    return bytes(out)

def crc16_modbus(data: bytes) -> int:
    """CRC16-Modbus."""
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
    """
    App Hello body (sin 0xFE/len/CRC): 19 bytes.
    Primeros 11 = 0x00, luego la MAC invertida (6 bytes), y quedan 2 bytes en 0x00.
    """
    data = bytearray(19)
    # 0..10 ya son 0x00
    data[11:11+6] = mac_reversed
    return bytes(data)

def build_ack_body_from_message(decrypted: bytes) -> bytes:
    """
    Toma decrypted, arma un paquete ACK completo (0xFE, len=9, head, CRC).
    luego enviaremos ack[2:] a send_encrypted().
    """
    ack_head = decrypted[2:7]  # 5 bytes
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
    """
    Devuelve los bytes cifrados.
    - len = body.length + 2  
    - msg = [0xFE, len, body..., CRC_lo, CRC_hi] y luego se rellena a múltiplo de 16 con 0x00
    - se encripta todo
    """
    length = len(body) + 2
    # armamos el buffer base (sin padding explícito aquí; se hará en encrypt_message)
    msg = bytearray(length)
    msg[0] = 0xFE
    msg[1] = length
    msg[2:2+len(body)] = body
    # CRC sobre msg[0: length-2] (igual que JS)
    crc = crc16_modbus(msg[:length-2])
    msg[length-2] = crc & 0xFF
    msg[length-1] = (crc >> 8) & 0xFF
    # cifrar con padding a múltiplo de 16
    return encrypt_message(bytes(msg))

def parse_cube_state(raw27to54: bytes):
    """
    27 bytes => 54 nibbles (colores 0..5).
    raw27to54 debería ser decrypted[7:34] según los mensajes 0x02/0x03/0x04.
    """
    colors = []
    for b in raw27to54[:27]:
        colors.append(b & 0x0F)
        colors.append((b >> 4) & 0x0F)
    return colors

# ====== Lógica BLE ======

async def main():
    # Prepara MAC invertida 
    mac_bytes = bytes(int(h, 16) for h in CUBE_MAC.split(":"))
    mac_reversed = mac_bytes[::-1]

    queue = asyncio.Queue()

    def notification_handler(sender: int, data: bytearray):
        # Llega cifrado -> lo ponemos desencriptado en una cola para procesar en async
        decrypted = decrypt_message(bytes(data))
        print("🔹 RX enc :", data.hex())
        print("🔹 RX dec :", decrypted.hex())
        queue.put_nowait(decrypted)

    async with BleakClient(CUBE_MAC) as client:
        print("✅ Conectado a", CUBE_MAC)

        # Suscribirse a notificaciones (FFF6)
        await client.start_notify(CHAR_UUID, notification_handler)
        print("📡 Notificaciones activadas en FFF6.")

        # === Enviar App Hello ===
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
                    # 0x02: "Cube Hello" con estado y batería
                    if msg_type == 0x02:
                        # Estado 27 bytes en [7:34], batería en [35]
                        if len(decrypted) >= 36:
                            state = parse_cube_state(decrypted[7:34])
                            battery = decrypted[35]
                            print(f"🔋 Battery: {battery}% | state_len={len(state)}")
                        # ACK obligatorio
                        ack_full = build_ack_body_from_message(decrypted)
                        enc_ack = build_encrypted_message_from_body(ack_full[2:])  
                        await client.write_gatt_char(CHAR_UUID, enc_ack, response=False)
                        print("✅ ACK a Cube Hello enviado.")

                    # 0x03: movimiento
                    elif msg_type == 0x03:
                        # move en [34], batería en [35], "needsAck" en [91] según el JS
                        move = decrypted[34] if len(decrypted) > 34 else None
                        battery = decrypted[35] if len(decrypted) > 35 else None
                        needs_ack = (len(decrypted) > 91 and decrypted[91] == 1)
                        print(f"↪️ Move={move} {move_map[int(move)]} | 🔋={battery}% | needsAck={needs_ack}")
                        
                        if needs_ack:
                            ack_full = build_ack_body_from_message(decrypted)
                            enc_ack = build_encrypted_message_from_body(ack_full[2:])
                            await client.write_gatt_char(CHAR_UUID, enc_ack, response=False)
                            print("✅ ACK a State Change enviado.")

                    # 0x04: Sync state
                    elif msg_type == 0x04:
                        if len(decrypted) >= 34:
                            state = parse_cube_state(decrypted[7:34])
                            print(f"🔄 Sync state recibido | state_len={len(state)}")

                finally:
                    queue.task_done()

        # Lanza procesador de mensajes
        task = asyncio.create_task(processor())

        # Mantener el programa vivo 
        try:
            await asyncio.sleep(3600)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await client.stop_notify(CHAR_UUID)

# --- Ejecutar ---
if __name__ == "__main__":
    import contextlib
    asyncio.run(main())
