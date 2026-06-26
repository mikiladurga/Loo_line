# Loo-Line · Virtual Bathroom Queue System
**Block C Hostel — Privacy-First Queue Management**

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python app.py
```

Open your browser to: **http://localhost:5050**

---

## Features

- 🚿 **Real-time door simulation** — CSS animated doors swing open when in use
- 🚦 **Traffic density bar** — Google Maps-style queue visualization (Green/Yellow/Red)
- 🔒 **Lock Inside** — marks stall as "In Use", starts countdown timer
- 🔧 **Maintenance lock** — marks stall as "Out of Order" with diagonal overlay
- 👥 **Virtual queue** — join/leave with privacy-first display (count only, no names)
- ⚡ **WebSocket sync** — all connected browsers update within 100ms
- 🕹️ **Simulation speed** — 1×, 5×, 10×, 30× time warp for testing

---

## Architecture

```
loo-line/
├── app.py              # Flask + Flask-SocketIO backend
├── requirements.txt
├── data/
│   ├── users.json       # User registry (8 demo users)
│   ├── bathrooms.json   # 2 stall states
│   ├── queue.json       # Active virtual queue
│   └── notifications.json  # Activity log
└── templates/
    └── index.html       # Single-page frontend (HTML + CSS + JS)
```

## Data Schemas

### users.json
```json
[{ "UserId": "u001", "FirstName": "Arjun", "LastName": "Sharma",
   "DisplayName": "A. Sharma", "Department": "Computer Science" }]
```

### bathrooms.json
```json
[{ "RoomId": "b001", "RoomName": "Stall A", "Status": "Vacant",
   "TimeRemaining": 0, "LockType": null, "OccupiedBy": null }]
```

### queue.json
```json
[{ "UserId": "u002", "Timestamp": "2024-01-01T10:00:00" }]
```

## Privacy
The public `sync_state` WebSocket broadcast **never** includes user names or IDs —
only `queueCount` and `trafficStatus`. Full identity data stays server-side only.

## Simulation Speed
`SIM_SPEED = 5` (default): 1 real second burns 5 sim-seconds off the countdown.
Change at runtime via the speed buttons or `POST /api/sim-speed`.