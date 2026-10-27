"""Mã nguồn HTML/JS của bộ quét camera chạy trong trình duyệt (nhúng sẵn để không cần thư mục riêng)."""

QR_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body { margin: 0; padding: 0; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }
  #wrap { position: relative; width: 100%; background: #000; border-radius: 12px; overflow: hidden; }
  video { width: 100%; display: block; max-height: 70vh; object-fit: cover; background: #000; }
  #frame { position: absolute; inset: 12% 10%; border: 3px solid rgba(0,230,118,.9);
           border-radius: 14px; pointer-events: none; box-shadow: 0 0 0 9999px rgba(0,0,0,.25); }
  #msg { position: absolute; left: 0; right: 0; bottom: 0; padding: 8px 10px; color: #fff;
         background: rgba(0,0,0,.55); font-size: 14px; text-align: center; }
  #bar { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  button { flex: 1; min-width: 120px; padding: 10px 12px; font-size: 15px; border: 0; border-radius: 8px;
           background: #ff4b4b; color: #fff; cursor: pointer; }
  button.alt { background: #555; }
  #zoomRow { display: none; margin-top: 8px; font-size: 13px; color: #888; }
  #zoomRow input { width: 70%; vertical-align: middle; }
</style>
</head>
<body>
<div id="wrap">
  <video id="v" playsinline muted autoplay></video>
  <div id="frame"></div>
  <div id="msg">Bấm "Bật camera" để bắt đầu</div>
</div>
<div id="bar">
  <button id="start">📷 Bật camera</button>
  <button id="snap" class="alt">📸 Chụp ảnh độ phân giải cao</button>
  <button id="flip" class="alt">🔄 Đổi camera</button>
</div>
<div id="zoomRow">Zoom: <input id="zoom" type="range" min="1" max="1" step="0.1" value="1"></div>

<script src="https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js"></script>
<script>
// ---- Giao thức Streamlit component (không cần build) ----
function send(type, data) {
  window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, data), "*");
}
function setValue(v) { send("streamlit:setComponentValue", { value: v, dataType: "json" }); }
function setHeight(h) { send("streamlit:setFrameHeight", { height: h }); }
send("streamlit:componentReady", { apiVersion: 1 });

const v = document.getElementById("v");
const msg = document.getElementById("msg");
const canvas = document.createElement("canvas");
const ctx = canvas.getContext("2d", { willReadFrequently: true });
const detector = ("BarcodeDetector" in window) ? new BarcodeDetector({ formats: ["qr_code"] }) : null;

let stream = null, facing = "environment", running = false, done = false;

function looksCccd(t) {
  if (!t) return false;
  const p = t.split("|");
  const so = (p[0] || "").trim();
  return p.length >= 5 && /^\d+$/.test(so) && (so.length === 12 || so.length === 9);
}

async function startCamera() {
  stopCamera();
  done = false;
  msg.textContent = "Đang mở camera...";
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: facing },
               width: { ideal: 1920 }, height: { ideal: 1080 } }
    });
  } catch (e) {
    msg.textContent = "Không mở được camera: " + e.name + ". Hãy cho phép quyền camera cho trang này.";
    return;
  }
  v.srcObject = stream;
  await v.play().catch(() => {});
  const track = stream.getVideoTracks()[0];
  try { await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }); } catch (e) {}
  try {
    const cap = track.getCapabilities ? track.getCapabilities() : {};
    if (cap.zoom) {
      const z = document.getElementById("zoom");
      z.min = cap.zoom.min; z.max = cap.zoom.max; z.step = cap.zoom.step || 0.1; z.value = cap.zoom.min;
      z.oninput = () => track.applyConstraints({ advanced: [{ zoom: Number(z.value) }] }).catch(() => {});
      document.getElementById("zoomRow").style.display = "block";
    }
  } catch (e) {}
  running = true;
  msg.textContent = "Đưa mã QR vào khung, giữ cách 15–25 cm";
  setHeight(document.body.scrollHeight + 10);
  scanLoop();
}

function stopCamera() {
  running = false;
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
}

async function decodeFrame() {
  const w = v.videoWidth, h = v.videoHeight;
  if (!w || !h) return null;
  if (detector) {
    try {
      const r = await detector.detect(v);
      for (const b of r) { if (looksCccd(b.rawValue)) return b.rawValue; }
    } catch (e) {}
  }
  // jsQR dự phòng (và bổ sung) trên khung hình tối đa 1600px
  const scale = Math.min(1, 1600 / Math.max(w, h));
  canvas.width = Math.round(w * scale); canvas.height = Math.round(h * scale);
  ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
  const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const code = window.jsQR ? jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" }) : null;
  if (code) {
    let t = code.data;
    try { t = new TextDecoder("utf-8").decode(Uint8Array.from(code.binaryData)); } catch (e) {}
    if (looksCccd(t)) return t;
  }
  return null;
}

async function scanLoop() {
  if (!running || done) return;
  if (v.readyState >= 2) {
    const text = await decodeFrame();
    if (text) {
      done = true;
      msg.textContent = "✅ Đã đọc được!";
      setValue({ type: "text", text: text, w: v.videoWidth, h: v.videoHeight, t: Date.now() });
      stopCamera();
      return;
    }
  }
  setTimeout(scanLoop, 50);
}

function snap() {
  if (!v.videoWidth) { msg.textContent = "Hãy bật camera trước."; return; }
  const c = document.createElement("canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  const data = c.toDataURL("image/jpeg", 0.92);
  msg.textContent = "Đang gửi ảnh " + c.width + "×" + c.height + " để phân tích...";
  setValue({ type: "image", data: data, w: c.width, h: c.height, t: Date.now() });
}

document.getElementById("start").onclick = startCamera;
document.getElementById("snap").onclick = snap;
document.getElementById("flip").onclick = () => {
  facing = (facing === "environment") ? "user" : "environment";
  startCamera();
};
window.addEventListener("pagehide", stopCamera);
setHeight(document.body.scrollHeight + 10);
</script>
</body>
</html>
"""
