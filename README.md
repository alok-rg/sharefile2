# LocalShare ⚡

**Real-time P2P file sharing over your local WiFi network — no cloud, no storage, no limits.**

Works like Nearby Share / Quick Share — but inside a browser tab.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         YOUR WiFi NETWORK                       │
│                                                                 │
│   Browser A          FastAPI Server         Browser B           │
│   ─────────          ─────────────         ─────────           │
│   SignalingWS ──────► WebSocket relay ◄──── SignalingWS         │
│                      (signaling ONLY)                           │
│                                                                 │
│   WebRTC DataChannel ──────────────────────────────────►        │
│   (direct P2P, file bytes never hit server)                     │
│                                                                 │
│   Shared text editor ◄────── WS broadcast ──────────────►      │
└─────────────────────────────────────────────────────────────────┘
```

### Server Role
- **WebSocket signaling relay** — routes SDP offers/answers, ICE candidates
- **Peer discovery** — maintains list of connected users, broadcasts joins/leaves
- **Shared editor state** — last-write-wins document sync
- **Zero file I/O** — no disk, no RAM buffering of file data

### File Transfer Flow
1. Sender selects file → clicks peer → `transfer_request` sent via WebSocket
2. Receiver sees accept/reject dialog
3. If accepted → sender receives `transfer_response` via WebSocket
4. Sender initiates WebRTC offer → ICE negotiation via server relay
5. DataChannel opens (direct browser-to-browser on LAN)
6. File streamed in 64KB chunks with backpressure control
7. Receiver reassembles blobs → browser auto-downloads
8. Progress bar updates live on both sides

---

## Quick Start

### Requirements
- Python 3.8+ 
- pip

### Run
```bash
# Install dependencies
pip install -r requirements.txt

# Start server
python server.py
```

Server will print:
```
══════════════════════════════════════════════
  🚀  LocalShare is running!
══════════════════════════════════════════════
  Local:    http://localhost:3000
  Network:  http://192.168.1.X:3000
══════════════════════════════════════════════
```

Open the **Network URL** on any device on the same WiFi.

### Custom port
```bash
PORT=8080 python server.py
```

---

## Android / Termux Setup

```bash
# Install Python in Termux
pkg update && pkg install python

# Clone / copy files to Termux
# Then:
pip install fastapi uvicorn

# Find your Android IP
ip addr show wlan0 | grep inet

# Start server
python server.py
```

Open `http://<android-ip>:3000` from any device on the same WiFi.

---

## Folder Structure

```
localshare/
├── server.py              # FastAPI + WebSocket signaling server
├── requirements.txt       # Python deps (fastapi, uvicorn)
├── README.md
├── templates/
│   └── index.html         # Single-page app (join + lobby + editor)
└── static/
    └── js/
        ├── transfer.js    # WebRTC FileTransferEngine (standalone module)
        └── signaling.js   # WebSocket wrapper with reconnect
```

---

## Features

| Feature | Implementation |
|---|---|
| Peer discovery | WebSocket broadcast on join/leave |
| File transfer | WebRTC DataChannel (P2P, direct) |
| Large files (multi-GB) | Chunked streaming (64KB) + backpressure |
| Accept/reject dialog | Signaling message `transfer_request` → UI modal |
| Progress bar | Chunk count → percentage update |
| Transfer speed | bytes / elapsed seconds |
| Drag & drop | HTML5 DragEvent on drop zone |
| Shared editor | WebSocket broadcast with 200ms debounce |
| Typing indicator | `typing` signal → animated UI |
| Auto-reconnect | SignalingSocket exponential backoff |
| Mobile friendly | Responsive CSS, touch-friendly targets |

---

## Streaming Mechanism (Deep Dive)

### Why WebRTC?
- **True P2P**: on LAN, after signaling, data flows browser→browser with no hops
- **No server memory**: server only sees tiny JSON signaling messages
- **Speed**: saturates WiFi link (100Mbps+ on 802.11ac)

### Chunk pipeline
```
File.slice(offset, offset+64KB)
  → ArrayBuffer
  → RTCDataChannel.send(buffer)   ← binary frame
  → [wire] →
  → ondatachannel message
  → state.chunks.push(buffer)
  → when END signal received:
      new Blob(chunks) → URL.createObjectURL → <a>.click()
```

### Backpressure
When `channel.bufferedAmount > 4MB`, sending pauses.
When it drops below `bufferedAmountLowThreshold` (256KB), it resumes.
This prevents memory spikes on large files.

---

## Security Notes

- Usernames are sanitized server-side (strip HTML chars, max 32 chars)
- No file data ever touches the server — MITM impossible at server level
- XSS prevention: all peer names escaped via `escHtml()` before DOM insertion
- For production: add HTTPS (required for WebRTC in Chrome on non-localhost)

---

## Example Workflow

```
1. Start server on laptop:  python server.py
   → prints http://192.168.1.5:3000

2. Laptop opens http://192.168.1.5:3000
   → enters name "Alice's MacBook" → Join

3. Phone opens http://192.168.1.5:3000
   → enters name "Bob's Phone" → Join

4. Alice's sidebar shows: Bob's Phone [online]
5. Alice drags a 2GB video onto the drop zone
6. Alice clicks Bob's Phone → "Send to Bob's Phone"
7. Bob sees: "Alice's MacBook wants to send video.mp4 (2.1 GB). Accept?"
8. Bob clicks Accept
9. WebRTC handshake via server, then direct P2P DataChannel
10. Progress bar fills → Bob's browser auto-downloads video.mp4
11. Both sides see "Sent ✓" / "Saved ✓"

Total server involvement: ~10 tiny JSON messages (< 5KB total)
```
