import streamlit as st
import json
import queue
import time
import socket
from collections import deque
import paho.mqtt.client as mqtt
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# -------------------------
# CONFIG PAGE
# -------------------------
st.set_page_config(layout="wide")
st.title("Projet Final: A311 - Industrie 4.0 et A304 - Systèmes Embarqués II (2025 - 2026)")

# -------------------------
# AUTOREFRESH (en ms)
# -------------------------
count = st_autorefresh(interval=3_000, limit=None, key="mqtt_autorefresh")

# -------------------------
# MQTT CONFIG
# -------------------------
MQTT_BROKER = "51.103.178.209"
MQTT_PORT = 1883
MQTT_SUB_TOPIC = "ESP32/Streamlit"
MQTT_PUB_TOPIC = "ESP32/Station 1" 
HIST_LEN = 50

# -------------------------
# Fonctions "climat"
# -------------------------
def compute_ressenti(temp):

    if 0 <= temp <= 20:
        return "froid"
    elif 20 < temp <= 25:
        return "doux"
    elif temp > 25:
        return "chaud"

def compute_periode_journee(lum):

    if 0 <= lum <= 20:
        return "Nuit"
    elif 20 < lum <= 50:
        return "Soir"
    elif lum > 50: 
        return "Jour"

def compute_temps_quil_fait(temp, hum, lum):
    # Pluvieux : T <= 20, H >= 80, L <= 50
    if temp <= 20 and hum >= 80 and lum <= 50:
        return "Pluvieux"

    # Nuageux : T > 20, H >= 50, L >= 50
    if temp > 20 and hum >= 50 and lum >= 50:
        return "Nuageux"

    # Ensoleillé : T >= 20, H <= 50, L > 80
    if temp >= 20 and hum <= 50 and lum > 80:
        return "Ensoleillé"

    # Neigeux : T <= 0, 30 <= L <= 70, H >= 80
    if temp <= 0 and 30 <= lum <= 70 and hum >= 80:
        return "Neigeux"

    # Si aucune condition n'est remplie
    return "Temps normal"  

# -------------------------
# Queue globale MQTT
# -------------------------
if "mqtt_queue" not in st.session_state:
    st.session_state.mqtt_queue = queue.Queue()
mqtt_queue = st.session_state.mqtt_queue

if "mqtt_started" not in st.session_state:
    st.session_state.mqtt_started = False

# -------------------------
# INIT valeurs et historiques
# -------------------------
if "temperature" not in st.session_state:
    st.session_state.temperature = None
if "humidity" not in st.session_state:
    st.session_state.humidity = None
if "luminosity" not in st.session_state:
    st.session_state.luminosity = None

if "temp_hist" not in st.session_state:
    st.session_state.temp_hist = deque(maxlen=HIST_LEN)
if "hum_hist" not in st.session_state:
    st.session_state.hum_hist = deque(maxlen=HIST_LEN)
if "lum_hist" not in st.session_state:
    st.session_state.lum_hist = deque(maxlen=HIST_LEN)

# LED default
if "led" not in st.session_state:
    st.session_state.led = False
if "led_r" not in st.session_state:
    st.session_state.led_r = 0
if "led_g" not in st.session_state:
    st.session_state.led_g = 0
if "led_b" not in st.session_state:
    st.session_state.led_b = 0

# pour détecter changements LED
if "prev_led" not in st.session_state:
    st.session_state.prev_led = st.session_state.led
if "prev_rgb" not in st.session_state:
    st.session_state.prev_rgb = (st.session_state.led_r, st.session_state.led_g, st.session_state.led_b)

# style déjà injecté ?
if "climat_style_injected" not in st.session_state:
    st.session_state.climat_style_injected = False

# -------------------------
# MQTT callbacks
# -------------------------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connecté, abonnement au topic:", MQTT_SUB_TOPIC)
        client.subscribe(MQTT_SUB_TOPIC)
    else:
        print("Échec connexion MQTT, code rc =", rc)

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        # On attend des clés 'temperature', 'humidity', 'luminosity'
        mqtt_queue.put(data)
    except Exception as e:
        print("Erreur on_message:", e)

# -------------------------
# Démarrage MQTT (une seule fois)
# -------------------------
def start_mqtt():
    if st.session_state.mqtt_started:
        return

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        st.session_state.mqtt_client = client
        st.session_state.mqtt_started = True
    except Exception as e:
        st.session_state.mqtt_client = None
        st.session_state.mqtt_started = False
        print("Erreur connexion MQTT:", e)

start_mqtt()

# -------------------------
# Traitement de la queue MQTT
# -------------------------
def process_mqtt_queue():
    updated = False
    while not mqtt_queue.empty():
        try:
            data = mqtt_queue.get_nowait()
        except queue.Empty:
            break

        # --- capteurs ---
        temp = data.get("temperature")
        hum = data.get("humidity")
        lum = data.get("luminosity")

        if temp is not None:
            st.session_state.temperature = float(temp)
            st.session_state.temp_hist.append(st.session_state.temperature)
            updated = True
        if hum is not None:
            st.session_state.humidity = float(hum)
            st.session_state.hum_hist.append(st.session_state.humidity)
            updated = True
        if lum is not None:
            st.session_state.luminosity = float(lum)
            st.session_state.lum_hist.append(st.session_state.luminosity)
            updated = True

        # --- LED / RGB (pour que les sliders bougent quand MQTT envoie une couleur) ---
        led = data.get("led")
        r = data.get("r")
        g = data.get("g")
        b = data.get("b")

        if led is not None:
            # selon ton ESP/Node-RED : 1/0, "on"/"off", etc.
            st.session_state.led = bool(int(led)) if str(led).isdigit() else bool(led)

        if r is not None:
            st.session_state.led_r = int(r)
        if g is not None:
            st.session_state.led_g = int(g)
        if b is not None:
            st.session_state.led_b = int(b)

    return updated

process_mqtt_queue()

# -------------------------
# Fonction pour publier une commande
# -------------------------
def publish_command(client, topic, payload_dict):
    if client is None:
        return
    try:
        payload_str = json.dumps(payload_dict)
        client.publish(topic, payload_str, qos=1)
    except Exception as e:
        print("Erreur publish_command:", e)

# -------------------------
# SIDEBAR : contrôle LED (avec keys fixes)
# -------------------------
st.sidebar.header("Contrôle LED")

# Utiliser des keys fixes pour éviter désynchronisation DOM
led_val = st.sidebar.toggle("LED ON / OFF", value=st.session_state.led, key="ui_led_toggle")

r_val = st.sidebar.slider("Rouge", 0, 255, st.session_state.led_r, key="ui_led_r")
g_val = st.sidebar.slider("Vert", 0, 255, st.session_state.led_g, key="ui_led_g")
b_val = st.sidebar.slider("Bleu", 0, 255, st.session_state.led_b, key="ui_led_b")

# Mettre à jour session_state de façon contrôlée
st.session_state.led = bool(led_val)
st.session_state.led_r = int(r_val)
st.session_state.led_g = int(g_val)
st.session_state.led_b = int(b_val)

current_rgb = (st.session_state.led_r, st.session_state.led_g, st.session_state.led_b)

if ("mqtt_client" in st.session_state) and st.session_state.mqtt_client is not None:
    # si changement état LED ou couleur => on publie
    if (st.session_state.led != st.session_state.prev_led) or (current_rgb != st.session_state.prev_rgb):
        payload = {
            "led": 1 if st.session_state.led else 0,
            "r": st.session_state.led_r,
            "g": st.session_state.led_g,
            "b": st.session_state.led_b,
        }
        publish_command(st.session_state.mqtt_client, MQTT_PUB_TOPIC, payload)
        st.session_state.prev_led = st.session_state.led
        st.session_state.prev_rgb = current_rgb

st.sidebar.write("☀️ LED ON" if st.session_state.led else "🌑 LED OFF")

# --- Initialisation sûre
if "sync" not in st.session_state:
    st.session_state.sync = False

# Bouton poussoir : toggle (avec key fixe)
if st.sidebar.button("🧭 🔁 Synchro", key="ui_sync_button"):
    st.session_state.sync = not st.session_state.sync

    payload = {
        "Synchro": 1 if st.session_state.sync else 0,
        "LED": 1 if st.session_state.led else 0,
        "R": int(st.session_state.led_r),
        "G": int(st.session_state.led_g),
        "B": int(st.session_state.led_b),
    }

    client = st.session_state.get("mqtt_client")
    if client:
        publish_command(client, MQTT_PUB_TOPIC, payload)
    else:
        st.sidebar.warning("Pas de client MQTT — message non envoyé")

st.sidebar.write("🔄 Mode synchronisé" if st.session_state.sync else "🔒 Mode local")

# -------------------------
# MAIN DASHBOARD
# -------------------------
st.header("📡 Station Météo")
st.subheader("Groupe A05")

# -------------------------
# SECTION CLIMAT (juste sous Station Météo)
# -------------------------
st.markdown("### 🌤️ Climat")

temp = st.session_state.temperature
hum = st.session_state.humidity
lum = st.session_state.luminosity

if temp is None or hum is None or lum is None:
    st.info("En attente de données pour calculer le climat...")
else:
    ressenti = compute_ressenti(temp)
    periode = compute_periode_journee(lum)
    temps = compute_temps_quil_fait(temp, hum, lum)

    if not st.session_state.climat_style_injected:
        st.markdown(
            """
            <style>
            .climat-card {
                padding: 1rem 1.25rem;
                border-radius: 0.75rem;
                border: 1px solid #444444;
                background-color: #111111;
                margin-bottom: 1rem;
            }
            .climat-row {
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                white-space: nowrap;    /* évite le retour à la ligne */
                overflow-x: auto;       /* si écran trop petit, on peut scroller */
                -webkit-overflow-scrolling: touch;
            }
            .climat-item {
                flex: 1 1 0;
                min-width: 180px;      /* ajuste pour éviter trop de rétrécissement */
                max-width: 33%;
                box-sizing: border-box;
                padding: 0.25rem 0.5rem;
                text-align: center;
            }
            .climat-item h4 {
                margin: 0 0 0.25rem 0;
                font-size: 0.95rem;
            }
            .climat-item p {
                margin: 0;
                font-weight: 600;
                font-size: 1.05rem;
            }
            /* facultatif : style responsive pour très petits écrans */
            @media (max-width: 520px) {
                .climat-item { min-width: 150px; max-width: none; }
            }
            </style>
            """,
            unsafe_allow_html=True,
    )
    st.session_state.climat_style_injected = True

st.markdown(
    f"""
    <div class="climat-card">
      <div class="climat-row">
        <div class="climat-item">
          <h4>Ressenti</h4>
          <p>{ressenti}</p>
        </div>
        <div class="climat-item">
          <h4>Période de la journée</h4>
          <p>{periode}</p>
        </div>
        <div class="climat-item">
          <h4>Temps actuel</h4>
          <p>{temps}</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -------------------------
# CARTES Temp / Hum / Lum
# -------------------------
c1, c2, c3 = st.columns(3)

with c1:
    temp_display = "—" if st.session_state.temperature is None else f"{st.session_state.temperature:.1f}"
    st.metric("🌡️ Température (°C)", temp_display)
    st.line_chart(list(st.session_state.temp_hist))

with c2:
    hum_display = "—" if st.session_state.humidity is None else f"{st.session_state.humidity:.1f}"
    st.metric("💧 Humidité (%)", hum_display)
    st.line_chart(list(st.session_state.hum_hist))

with c3:
    lum_display = "—" if st.session_state.luminosity is None else f"{st.session_state.luminosity:.0f}"
    st.metric("💡 Lumière (%)", lum_display)
    st.line_chart(list(st.session_state.lum_hist))

# -------------------------
# GRAPH COMBINÉ
# -------------------------
st.markdown("### Graphique combiné — Température / Humidité / Lumière")

def deque_to_list_aligned(*deques, fill_value=None):
    lists = [list(d) for d in deques]
    maxlen = max((len(l) for l in lists), default=0)
    aligned = []
    for l in lists:
        pad = [fill_value] * (maxlen - len(l))
        aligned.append(pad + l)
    return aligned, maxlen

aligned, length = deque_to_list_aligned(
    st.session_state.temp_hist,
    st.session_state.hum_hist,
    st.session_state.lum_hist,
    fill_value=None,
)

if length > 0:
    df = pd.DataFrame({
        "Temp (°C)": aligned[0],
        "Hum (%)": aligned[1],
        "Lum (%)": aligned[2],
    })
    st.line_chart(df)
else:
    st.info("Pas encore de données pour le graphique combiné.")

# -------------------------
# DEBUG
# -------------------------
with st.expander("Debug: dernières valeurs & état MQTT"):
    st.json({
        "temperature": st.session_state.temperature,
        "humidity": st.session_state.humidity,
        "luminosity": st.session_state.luminosity,
        "led": st.session_state.led,
        "led_r": st.session_state.led_r,
        "led_g": st.session_state.led_g,
        "led_b": st.session_state.led_b,
    })
    st.write(f"MQTT client running: {st.session_state.mqtt_started}")
    st.write(f"Broker: {MQTT_BROKER}  Port: {MQTT_PORT}")
    st.write(f"Subscribe topic: {MQTT_SUB_TOPIC}  Publish topic: {MQTT_PUB_TOPIC}")
    client_obj = st.session_state.get("mqtt_client")
    st.write(f"MQTT client object: {'present' if client_obj else 'None'}")