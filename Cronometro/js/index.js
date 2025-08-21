let startTime, interval;
let running = false;
let listo = false; // si ya está verde y listo para iniciar
let timeoutId = null; // para cancelar el cambio a verde
const display = document.getElementById("cronometro");

// -------------------
// Lógica de cronómetro con presionado
// -------------------

document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !running && !listo && !timeoutId) {
        e.preventDefault();
        display.style.color = "red"; // se pone rojo
        // Programar cambio a verde en 0.5s
        timeoutId = setTimeout(() => {
            display.style.color = "lime";
            listo = true;
        }, 500);
    }
});

document.addEventListener("keyup", (e) => {
    if (e.code === "Space") {
        e.preventDefault();
        // Si estaba listo (verde) → arrancar
        if (!running && listo) {
            iniciarCronometro();
        }
        // Si se suelta antes de estar listo (aún rojo) → cancelar
        else if (!running && !listo) {
            display.style.color = "white";
        }
        // Si estaba corriendo → detener
        else if (running) {
            detenerCronometro();
        }

        // Reset de timeout y estado
        clearTimeout(timeoutId);
        timeoutId = null;
        listo = false;
    }
});

function iniciarCronometro() {
    startTime = Date.now();
    interval = setInterval(actualizarDisplay, 10);
    running = true;
    display.style.color = "white";
}

function detenerCronometro() {
    clearInterval(interval);
    let tiempoFinal = display.textContent;
    guardarTiempo(tiempoFinal);
    mostrarTiempos();
    running = false;
    display.style.color = "white";
}

function actualizarDisplay() {
    let tiempo = Date.now() - startTime;
    let minutos = Math.floor(tiempo / 60000);
    let segundos = Math.floor((tiempo % 60000) / 1000);
    let centesimas = Math.floor((tiempo % 1000) / 10);
    display.textContent =
        `${minutos.toString().padStart(2, "0")}:${segundos.toString().padStart(2, "0")}.${centesimas.toString().padStart(2, "0")}`;
}

// -------------------
// Guardado en localStorage
// -------------------

function guardarTiempo(tiempo) {
    let tiempos = JSON.parse(localStorage.getItem("tiempos")) || [];
    tiempos.push(tiempo);
    localStorage.setItem("tiempos", JSON.stringify(tiempos));
}

function mostrarTiempos() {
    listaTiempos.innerHTML = "";
    let tiempos = JSON.parse(localStorage.getItem("tiempos")) || [];
    tiempos.forEach((t, index) => {
        let li = document.createElement("li");
        li.className = "list-group-item d-flex justify-content-between align-items-center";
        li.textContent = t;

        let btn = document.createElement("button");
        btn.className = "btn btn-sm btn-danger";
        btn.textContent = "X";
        btn.onclick = () => borrarTiempo(index);

        li.appendChild(btn);
        listaTiempos.appendChild(li);
    });
}

function borrarTiempo(index) {
    let tiempos = JSON.parse(localStorage.getItem("tiempos")) || [];
    tiempos.splice(index, 1);
    localStorage.setItem("tiempos", JSON.stringify(tiempos));
    mostrarTiempos();
}

function borrarTodos() {
    localStorage.removeItem("tiempos");
    mostrarTiempos();
}

// Mostrar tiempos al cargar
mostrarTiempos();
