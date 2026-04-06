#!/usr/bin/env python3
"""
LocalShare - Real-time P2P file sharing over local network
Server acts as signaling-only relay. Files never touch the server.
"""

import asyncio
import json
import logging
import os
import socket
import sys
import uuid
from datetime import datetime
from typing import Dict, Optional

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except ImportError:
    print("Installing dependencies...")
    os.system(f"{sys.executable} -m pip install fastapi uvicorn[standard] --break-system-packages -q")
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="LocalShare")

# Mount static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# ── In-memory state ──────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # peer_id -> {"ws": WebSocket, "name": str, "joined_at": str}
        self.peers: Dict[str, dict] = {}
        # shared text document state
        self.doc_content: str = ""
        self.doc_version: int = 0

    def get_peer_list(self):
        return [
            {"id": pid, "name": p["name"], "joined_at": p["joined_at"]}
            for pid, p in self.peers.items()
        ]

    async def broadcast(self, message: dict, exclude: Optional[str] = None):
        """Broadcast JSON message to all connected peers."""
        data = json.dumps(message)
        dead = []
        for pid, peer in self.peers.items():
            if pid == exclude:
                continue
            try:
                await peer["ws"].send_text(data)
            except Exception:
                dead.append(pid)
        for pid in dead:
            await self.remove_peer(pid)

    async def send_to(self, peer_id: str, message: dict):
        """Send JSON message to a specific peer."""
        if peer_id in self.peers:
            try:
                await self.peers[peer_id]["ws"].send_text(json.dumps(message))
            except Exception:
                await self.remove_peer(peer_id)

    async def add_peer(self, peer_id: str, ws: WebSocket, name: str):
        self.peers[peer_id] = {
            "ws": ws,
            "name": name,
            "joined_at": datetime.utcnow().isoformat()
        }
        # Notify everyone of updated peer list
        await self.broadcast({
            "type": "peer_joined",
            "peer": {"id": peer_id, "name": name},
            "peers": self.get_peer_list()
        })
        log.info(f"Peer joined: {name} ({peer_id})")

    async def remove_peer(self, peer_id: str):
        if peer_id not in self.peers:
            return
        name = self.peers[peer_id]["name"]
        del self.peers[peer_id]
        await self.broadcast({
            "type": "peer_left",
            "peer_id": peer_id,
            "peers": self.get_peer_list()
        })
        log.info(f"Peer left: {name} ({peer_id})")


manager = ConnectionManager()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "templates", "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    peer_id = str(uuid.uuid4())[:8]

    try:
        # First message must be join
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "join":
            await ws.close()
            return

        # Sanitize name
        name = str(msg.get("name", "Anonymous"))[:32]
        name = "".join(c for c in name if c.isprintable() and c not in '<>"\'&')
        name = name.strip() or "Anonymous"

        await manager.add_peer(peer_id, ws, name)

        # Send initial state to this peer
        await ws.send_text(json.dumps({
            "type": "welcome",
            "peer_id": peer_id,
            "name": name,
            "peers": manager.get_peer_list(),
            "doc_content": manager.doc_content,
            "doc_version": manager.doc_version
        }))

        # Main message loop
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            # ── WebRTC Signaling relay ──────────────────────────────────────
            if msg_type in ("offer", "answer", "ice_candidate",
                            "transfer_request", "transfer_response",
                            "transfer_cancel", "transfer_complete"):
                target = msg.get("to")
                if target and target in manager.peers:
                    msg["from"] = peer_id
                    msg["from_name"] = manager.peers[peer_id]["name"]
                    await manager.send_to(target, msg)

            # ── Shared text editor ──────────────────────────────────────────
            elif msg_type == "doc_update":
                # Simple last-write-wins with version vector
                new_version = manager.doc_version + 1
                manager.doc_content = msg.get("content", manager.doc_content)
                manager.doc_version = new_version
                await manager.broadcast({
                    "type": "doc_sync",
                    "content": manager.doc_content,
                    "version": new_version,
                    "from": peer_id,
                    "from_name": manager.peers[peer_id]["name"]
                }, exclude=peer_id)

            elif msg_type == "typing":
                await manager.broadcast({
                    "type": "typing",
                    "from": peer_id,
                    "from_name": manager.peers[peer_id]["name"]
                }, exclude=peer_id)

            # ── Ping/pong ───────────────────────────────────────────────────
            elif msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:
        log.warning(f"Peer {peer_id} error: {e}")
    finally:
        await manager.remove_peer(peer_id)


# ── Entry point ────────────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    ip = get_local_ip()
    print("\n" + "═" * 50)
    print("  🚀  LocalShare is running!")
    print("═" * 50)
    print(f"  Local:    http://localhost:{port}")
    print(f"  Network:  http://{ip}:{port}")
    print("═" * 50)
    print("  Share the Network URL with devices on the same WiFi\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
