
// === Configuración del cubo ===
const CUBE_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb";
const CUBE_CHAR_UUID    = "0000fff6-0000-1000-8000-00805f9b34fb";

// === Clave AES (misma que en Python) ===
const CLAVE_AES = new Uint8Array([87, 177, 249, 171, 205, 90, 232, 167,
                                  156, 185, 140, 231, 87, 140, 81, 8]);

// === Diccionario de movimientos ===
const mapaMovimientos = {
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
};

// === Utilidades ===

function crc16_modbus(datos) {
  let crc = 0xFFFF;
  for (let b of datos) {
    crc ^= b;
    for (let i = 0; i < 8; i++) {
      if ((crc & 1) !== 0) {
        crc >>= 1;
        crc ^= 0xA001;
      } else {
        crc >>= 1;
      }
    }
  }
  return crc;
}

function construirAppHello(macInvertida) {
  let data = new Uint8Array(19);
  data.set(macInvertida, 11);
  return data;
}

function construirAckDesdeMensaje(descifrado) {
  let ackHead = descifrado.slice(2, 7); // 5 bytes
  let ack = new Uint8Array(7);
  ack[0] = 0xFE;
  ack[1] = 9;
  ack.set(ackHead, 2);
  let crc = crc16_modbus(ack);
  let full = new Uint8Array(9);
  full.set(ack, 0);
  full[7] = crc & 0xFF;
  full[8] = (crc >> 8) & 0xFF;
  return full;
}

function construirMensajeEncriptado(cuerpo) {
  let longitud = cuerpo.length + 2;
  let msg = new Uint8Array(longitud);
  msg[0] = 0xFE;
  msg[1] = longitud;
  msg.set(cuerpo, 2);
  let crc = crc16_modbus(msg.slice(0, longitud-2));
  msg[longitud-2] = crc & 0xFF;
  msg[longitud-1] = (crc >> 8) & 0xFF;

  // Encriptar con AES-ECB → aquí conviene usar una lib AES en JS
  // (ej. crypto-js). Para simplificar, te lo dejo como pseudocódigo:
  // return encriptarAES(msg);
  return msg; // TODO: implementar AES-ECB real
}

function parsearEstadoCubo(raw) {
  let colores = [];
  for (let b of raw.slice(0,27)) {
    colores.push(b & 0x0F);
    colores.push((b >> 4) & 0x0F);
  }
  return colores;
}

// === Conexión BLE ===
let caracteristicaCubo = null;

async function conectarCubo() {
  try {
    const dispositivo = await navigator.bluetooth.requestDevice({
      filters: [{ services: [CUBE_SERVICE_UUID] }]
    });

    const servidor = await dispositivo.gatt.connect();
    const servicio = await servidor.getPrimaryService(CUBE_SERVICE_UUID);
    caracteristicaCubo = await servicio.getCharacteristic(CUBE_CHAR_UUID);

    await caracteristicaCubo.startNotifications();
    caracteristicaCubo.addEventListener("characteristicvaluechanged", manejarNotificacion);

    console.log("✅ Conectado al cubo!");

    // Enviar App Hello
    // Aquí habría que obtener la MAC invertida, en Web Bluetooth no siempre está accesible.
    // Puedes enviar un paquete genérico como hace tu script Python.
    // let macInvertida = ...;
    // let appHello = construirAppHello(macInvertida);
    // let enc = construirMensajeEncriptado(appHello);
    // await caracteristicaCubo.writeValueWithoutResponse(enc);

  } catch (err) {
    console.error("❌ Error al conectar:", err);
  }
}

function manejarNotificacion(event) {
  let valor = new Uint8Array(event.target.value.buffer);
  console.log("🔹 RX:", valor);

  // Aquí debería ir la lógica de descifrado (AES-ECB)
  let descifrado = valor; // TODO: descifrar real
  let tipo = descifrado[2];

  if (tipo === 0x02) {
    let estado = parsearEstadoCubo(descifrado.slice(7,34));
    let bateria = descifrado[35];
    console.log("🔋 Batería:", bateria, "%", estado);
    // enviar ACK
    let ack = construirAckDesdeMensaje(descifrado);
    let enc = construirMensajeEncriptado(ack.slice(2));
    caracteristicaCubo.writeValueWithoutResponse(enc);

  } else if (tipo === 0x03) {
    let movimiento = descifrado[34];
    let bateria = descifrado[35];
    console.log("↪️ Movimiento:", movimiento, mapaMovimientos[movimiento], "🔋", bateria);

    if (mapaMovimientos[movimiento]) {
      twistyPlayer.experimentalAddMove(mapaMovimientos[movimiento]);
    }

    // enviar ACK si hace falta…
  } else if (tipo === 0x04) {
    let estado = parsearEstadoCubo(descifrado.slice(7,34));
    console.log("🔄 Sync state:", estado);
  }
}

