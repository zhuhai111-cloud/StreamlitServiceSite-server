from __future__ import annotations

import json
import os

import streamlit as st
import streamlit.components.v1 as components

from appservice.route_mount import mount_with_short_retry

if os.environ.get('APP_ROUTES_READY') != '1':
    mount_with_short_retry()

st.set_page_config(
    page_title="Online Text to Speech",
    page_icon="🔊",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.title("Online Text to Speech")
st.caption("Enter text and listen to it using your browser's built-in speech engine.")

text = st.text_area(
    "Text to speak",
    value="Hello! Welcome to Online Text to Speech.",
    height=220,
    max_chars=12000,
)

col1, col2, col3 = st.columns(3)
with col1:
    rate = st.slider("Rate", 0.5, 2.0, 1.0, 0.1)
with col2:
    pitch = st.slider("Pitch", 0.0, 2.0, 1.0, 0.1)
with col3:
    volume = st.slider("Volume", 0.0, 1.0, 1.0, 0.1)

payload = json.dumps({"text": text, "rate": rate, "pitch": pitch, "volume": volume}, ensure_ascii=False)
components.html(
    f"""
<!doctype html><html><body style="margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif">
<style>
.row{{display:flex;gap:8px;flex-wrap:wrap}} button{{border:0;border-radius:9px;padding:10px 15px;font-weight:600;cursor:pointer}}
.primary{{background:#ff4b4b;color:white}} .secondary{{background:#eef1f6;color:#243047}}
#status{{margin-top:10px;color:#667085;font-size:14px}}
@media (prefers-color-scheme: dark){{.secondary{{background:#2a3040;color:#f2f4f7}} #status{{color:#aab2c0}}}}
</style>
<div class="row"><button class="primary" onclick="speak()">▶ Speak</button><button class="secondary" onclick="pause()">⏸ Pause</button><button class="secondary" onclick="resume()">▶ Resume</button><button class="secondary" onclick="stop()">■ Stop</button></div>
<div id="status">Ready.</div>
<script>
const p={payload}; const synth=window.speechSynthesis; const status=document.getElementById('status');
function speak(){{ if(!synth){{status.textContent='Speech synthesis is not supported by this browser.';return;}} synth.cancel(); if(!p.text.trim()){{status.textContent='Please enter some text first.';return;}} const u=new SpeechSynthesisUtterance(p.text); u.rate=p.rate;u.pitch=p.pitch;u.volume=p.volume;u.onstart=()=>status.textContent='Speaking…';u.onend=()=>status.textContent='Finished.';u.onerror=e=>status.textContent='Speech error: '+(e.error||'Unknown error'); synth.speak(u); }}
function pause(){{if(synth&&synth.speaking&&!synth.paused){{synth.pause();status.textContent='Paused.';}}}}
function resume(){{if(synth&&synth.paused){{synth.resume();status.textContent='Speaking…';}}}}
function stop(){{if(synth)synth.cancel();status.textContent='Stopped.';}}
</script></body></html>
""",
    height=80,
)

with st.expander("About this app"):
    st.write("Turn written text into spoken audio directly in your browser.")
    st.write("Adjust the speaking rate, pitch, and volume, then use the playback controls to speak, pause, resume, or stop at any time.")
    st.write("The available voices and pronunciation depend on the speech voices installed or provided by your browser and operating system.")
