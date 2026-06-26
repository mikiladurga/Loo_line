# Production-Ready Bathroom Queue System (Redis + Advanced Features)

import json
import threading
import time
import os
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from flask_socketio import SocketIO, emit
import redis
from whatsapp_service import send_whatsapp


# ─── App Setup ─────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ─── Redis Setup (Production Ready) ────────────────────
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

SIM_SPEED = 5
DEFAULT_DURATION = 900  # 15 minutes
RESTRICTION_SECONDS = 8 * 60 * 60
lock = threading.Lock()



def get_user_mobile(user_id):
    users = get_json('users', [])
    user = next((u for u in users if u['UserId'] == user_id), None)

    if not user:
        print(f"[USER] ❌ User not found: {user_id}")
        return None

    mobile = user.get('Mobile')

    if not mobile:
        print(f"[USER] ❌ No mobile for user: {user_id}")

    print(f"[USER] Found mobile → {user_id} → {mobile}")
    return mobile



# ─── Redis Helpers ─────────────────────────────────────

def get_json(key, default):
    data = r.get(key)
    return json.loads(data) if data else default


def set_json(key, value):
    r.set(key, json.dumps(value))

# ─── Advanced Features ─────────────────────────────────

def estimate_wait(position, bathrooms):
    if position == 1:
        vacant = [b for b in bathrooms if b['Status']=='Vacant']
        if vacant:
            return 0
    in_use = [b for b in bathrooms if b['Status']=='In Use']
    if not in_use:
        return DEFAULT_DURATION
    avg = sum(b['TimeRemaining'] for b in in_use)/len(in_use)
    rooms = max(1, len(in_use))
    return int((position/rooms)*avg)


def traffic_status(count):
    if count <= 1:
        return 'low'
    elif count <= 4:
        return 'moderate'
    return 'high'


def pre_allocate(bathrooms):
    busy = sorted([b for b in bathrooms if b['Status']=='In Use'], key=lambda x:x['TimeRemaining'])
    if not busy:
        return None
    soon = busy[0]
    total = soon.get('TotalDuration', DEFAULT_DURATION)
    if soon['TimeRemaining'] <= total*0.2:
        return soon['RoomId']
    return None

@app.route('/api/users')
def api_users():
    return jsonify(get_json('users', []))

@app.route('/api/sim-speed', methods=['POST'])
def set_speed():
    global SIM_SPEED
    data = request.json or {}
    SIM_SPEED = max(1, min(int(data.get('speed', 5)), 60))
    return jsonify({'simSpeed': SIM_SPEED})

@app.route('/api/lock', methods=['POST'])
def lock_room():
    data = request.json or {}
    room_id = data.get('roomId')
    user_id = data.get('userId')
    duration = int(data.get('duration', 300))
    lockType = data.get('lockType')

    with lock:
        bathrooms = get_json('bathrooms', [])
        room = next((b for b in bathrooms if b['RoomId'] == room_id), None)

        if is_user_restricted(user_id):
            return jsonify({'error': 'You are restricted for 8 hours after last usage.'}), 403

        if any(b.get('OccupiedBy') == user_id for b in bathrooms):
            return jsonify({'error': 'You are already using a room'}), 400

        if not room:
            return jsonify({'error': 'Room not found'}), 404

        if room['Status'] != 'Vacant':
            return jsonify({'error': 'Room not available'}), 409

        room.update({
            'Status': 'In Use' if lockType == 'Inside' else 'Out of Order',
            'LockType': lockType,
            'OccupiedBy': user_id,
            'TimeRemaining': duration,
            'TotalDuration': duration
        })

        set_json('bathrooms', bathrooms)

    broadcast()
    return jsonify({'success': True})

@app.route('/api/unlock', methods=['POST'])
def unlock_room():
    data = request.json or {}
    room_id = data.get('roomId')

    with lock:
        bathrooms = get_json('bathrooms', [])
        room = next((b for b in bathrooms if b['RoomId'] == room_id), None)

        if not room:
            return jsonify({'error': 'Room not found'}), 404

        user_id = room.get('OccupiedBy')

        # ✅ log usage before clearing
        if user_id:
            log_usage(user_id, room_id, room.get('TotalDuration', DEFAULT_DURATION))

        room.update({
            'Status': 'Vacant',
            'OccupiedBy': None,
            'TimeRemaining': 0,
            'LockType': None
        })

        set_json('bathrooms', bathrooms)

    broadcast()
    return jsonify({'success': True})


# ─── Core Logic ───────────────────────────────────────

def build_state():
    bathrooms = get_json('bathrooms', [])
    queue = get_json('queue', [])
    users = get_json('users', [])

    q_details = []
    for i, e in enumerate(queue):
        user = next((u for u in users if u['UserId'] == e['UserId']), {})
        q_details.append({
            'position': i + 1,
            'UserId': e['UserId'],
            'DisplayName': user.get('DisplayName', 'Unknown'),
            'Department': user.get('Department', ''), # ← Bug 7 fix also here
            'estimatedWait': estimate_wait(i + 1, bathrooms),
            'allocatedRoom': pre_allocate(bathrooms) if i == 0 else None
        })

    return {
        'bathrooms': bathrooms,
        'queue': q_details,
        'queueCount': len(queue), # ← was missing
        'trafficStatus': traffic_status(len(queue)), # ← was named 'traffic'
        'simSpeed': SIM_SPEED, # ← was missing
        'notifications': get_json('notifications', []), # ← was missing
        'timestamp': datetime.now().strftime('%H:%M:%S')
    }



def broadcast():
    socketio.emit('sync_state', build_state())

# ─── Notification Logger ────────────────────────────────────────────
def log_event(message):
    notifs = get_json('notifications', [])
    notifs.insert(0, {
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'message': message
    })
    set_json('notifications', notifs[:50])  # keep last 50 events


# ─── Usage Logger ───────────────────────────────────────────────────
def log_usage(user_id, room_id, duration_used):
    log = get_json('usage_log', [])

    now_ts = int(time.time())

    log.append({
        'UserId': user_id,
        'RoomId': room_id,
        'Duration': duration_used,
        'Date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'timestamp': now_ts   # ✅ IMPORTANT
    })

    set_json('usage_log', log)

    # ✅ store last usage separately (fast lookup)
    last_usage = get_json('last_usage', {})
    last_usage[user_id] = now_ts
    set_json('last_usage', last_usage)

def is_user_restricted(user_id):
    last_usage = get_json('last_usage', {})
    last_time = last_usage.get(user_id)

    if not last_time:
        return False

    now = int(time.time())
    return (now - last_time) < RESTRICTION_SECONDS

def get_remaining_restriction(user_id):
    last_usage = get_json('last_usage', {})
    last_time = last_usage.get(user_id)

    if not last_time:
        return 0

    remaining = RESTRICTION_SECONDS - (int(time.time()) - last_time)
    return max(0, remaining)

# ─── Simulation ───────────────────────────────────────

# ─── Simulation ─────────────────────────────────────────────────────
def simulation():
    # Track warnings + reminders
    reminder_sent = {}
    overstay_warned = set()

    while True:
        try:
            time.sleep(1)
            with lock:
                bathrooms = get_json('bathrooms', [])
                queue     = get_json('queue', [])
                changed   = False

                # ── 1. Tick every in-use room ──────────────────────
                for b in bathrooms:
                    if b['Status'] != 'In Use':
                        continue

                    total        = b.get('TotalDuration', DEFAULT_DURATION)
                    prev_time    = b['TimeRemaining']
                    b['TimeRemaining'] = max(0, prev_time - SIM_SPEED)
                    changed      = True

                    room_id  = b['RoomId']
                    remaining = b['TimeRemaining']

                    # Initialize reminder tracker
                    if room_id not in reminder_sent:
                        reminder_sent[room_id] = set()

                    # ── 2. MULTI-STAGE REMINDERS ───────────────────
                    # Only send reminders for the room that will free first
                    soonest_room = min(
                        [x for x in bathrooms if x['Status'] == 'In Use'],
                        key=lambda x: x['TimeRemaining'],
                        default=None
                    )

                    if not soonest_room or soonest_room['RoomId'] != room_id:
                        continue

                    next_users = [queue[0]['UserId']] if queue else []

                    def send_reminder(tag, message):
                        if tag not in reminder_sent[room_id]:
                            print(f"[REMINDER] Trigger → {tag} | room={room_id} | msg={message}")

                            reminder_sent[room_id].add(tag)

                            for user in next_users:
                                print(f"[REMINDER] Target user → {user}")

                                socketio.emit('queue_reminder', {
                                    'userId': user,
                                    'message': message
                                })

                                mobile = get_user_mobile(user)
                                if mobile:
                                    print(f"[REMINDER] Sending WA → {mobile}")
                                    send_whatsapp(mobile, message)
                                else:
                                    print(f"[REMINDER] ❌ No mobile for {user}")

                            log_event(message)

                    if remaining <= 600:
                        send_reminder('10min', f"🟡 {b.get('RoomName')} free in ~10 min")

                    if remaining <= 300:
                        send_reminder('5min', f"🟠 {b.get('RoomName')} free in ~5 min")

                    if remaining <= 120:
                        send_reminder('2min', f"🔶 {b.get('RoomName')} free in ~2 min")

                    if remaining <= 60:
                        send_reminder('1min', f"🔴 {b.get('RoomName')} free in ~1 min")

                    # ── 3. Overstay warning (existing logic) ───────
                    threshold = total * 0.2
                    if (
                        remaining <= threshold
                        and remaining > 0
                        and room_id not in overstay_warned
                    ):
                        overstay_warned.add(room_id)
                        mins_left = int(remaining / 60) + 1

                        socketio.emit('overstay_warning', {
                            'roomId': room_id,
                            'secondsLeft': remaining,
                            'message': f"⚠️ {b.get('RoomName')}: only ~{mins_left} min left!"
                        })

                        log_event(f"⚠️ Overstay warning — {b.get('RoomName')} has {mins_left} min left")

                    # ── 4. Room expired → free it ───────────────────
                    if remaining == 0:
                        user_id = b.get('OccupiedBy')

                        overstay_warned.discard(room_id)
                        reminder_sent.pop(room_id, None)  # ✅ RESET REMINDERS

                        if user_id:
                            log_usage(user_id, b['RoomId'], total)
                            log_event(f"✅ {b.get('RoomName')} vacated by {user_id}")

                        b.update({
                            'Status': 'Vacant',
                            'OccupiedBy': None,
                            'LockType': None,
                            'TimeRemaining': 0
                        })

                # ── 5. Auto-assign queue ──────────────────────────
                all_full = all(b['Status'] != 'Vacant' for b in bathrooms)

                if not all_full:
                    while queue:
                        room = next(
                            (b for b in bathrooms
                             if b['Status'] == 'Vacant'
                             and b.get('LockType') != 'Outside'),
                            None
                        )
                        if not room:
                            break

                        user    = queue.pop(0)
                        user_id = user['UserId']

                        room.update({
                            'Status': 'In Use',
                            'OccupiedBy': user_id,
                            'TimeRemaining': DEFAULT_DURATION,
                            'TotalDuration': DEFAULT_DURATION,
                            'LockType': 'Inside'
                        })

                        # ✅ WhatsApp: Assigned
                        print(f"[ASSIGN] Room assigned → {user_id} → {room.get('RoomName')}")

                        mobile = get_user_mobile(user_id)
                        if mobile:
                            print(f"[ASSIGN] Sending WA → {mobile}")
                            send_whatsapp(
                                mobile,
                                f"🚿 Your turn!\nRoom {room.get('RoomName')} is ready."
                            )
                        else:
                            print(f"[ASSIGN] ❌ No mobile for {user_id}")

                        changed = True
                        log_event(f"🚿 {room.get('RoomName')} assigned to {user_id}")

                        # Notify next user (UI only)
                        if queue:
                            next_user = queue[0]['UserId']
                            socketio.emit('your_turn_soon', {
                                'userId': next_user,
                                'message': f"🔔 You're next! {room.get('RoomName')} will be free soon."
                            })

                # ── 6. Persist + broadcast ────────────────────────
                if changed:
                    set_json('bathrooms', bathrooms)
                    set_json('queue', queue)
                    broadcast()

        except Exception as e:
            print(f"[Simulation error] {e}")

# ─── Routes ─────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/state')
def state():
    return jsonify(build_state())


@app.route('/api/queue/join', methods=['POST'])
def join():
    data = request.json or {}
    user_id = data.get('userId')

    with lock:
        queue = get_json('queue', [])
        # 🚫 Restriction check
        if is_user_restricted(user_id):
            remaining = get_remaining_restriction(user_id)
            mins = remaining // 60

            return jsonify({
                'error': f'Please wait {mins} minutes before reusing.'
            }), 403

        if any(e['UserId'] == user_id for e in queue):
            return jsonify({'error': 'Already in queue'}), 400

        # Already in bathroom
        bathrooms = get_json('bathrooms', [])
        if any(b.get('OccupiedBy') == user_id for b in bathrooms):
            return jsonify({'error': 'You are already using a room'}), 400

        queue.append({'UserId': user_id})
        set_json('queue', queue)

    # ✅ WhatsApp notification
    print(f"[QUEUE] Join request → user={user_id}")
    mobile = get_user_mobile(user_id)
    if mobile:
        print(f"[QUEUE] Sending WA join message → {user_id}")
        send_whatsapp(
            mobile,
            f"🧾 Loo-Line\nYou joined the queue\nPosition: {len(queue)}"
        )

    broadcast()
    return jsonify({'status': 'joined'})


@app.route('/api/queue/leave', methods=['POST'])
def leave():
    data = request.json or {}
    user_id = data.get('userId')
    mobile = get_user_mobile(user_id)
    if mobile:
        send_whatsapp(
            mobile,
            "❌ You left the queue"
        )
    with lock:
        queue = get_json('queue', [])
        queue = [e for e in queue if e['UserId']!=user_id]
        set_json('queue', queue)

    broadcast()
    return jsonify({'status':'left'})

# ─── Frontend Improvements (Socket Sync) ──────────────
# Example JS:
# socket.on('sync_state', (data)=>{
#   updateQueueUI(data.queue);
#   updateBathroomUI(data.bathrooms);
#   updateTrafficIndicator(data.traffic);
# });

@app.route('/api/reset', methods=['POST'])
def reset_all():
    with lock:
        bathrooms = get_json('bathrooms', [])
        for b in bathrooms:
            b.update({'Status': 'Vacant', 'OccupiedBy': None,
                      'TimeRemaining': 0, 'LockType': None})
        set_json('bathrooms', bathrooms)
        set_json('queue', [])
    broadcast()
    return jsonify({'success': True})

# ─── Init ───────────────────────────────────────────


def read_json_file(filename, default):
    path = os.path.join('data', filename)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return default

def load_initial_data():
    users = read_json_file('users.json', [])
    set_json('users', users)   # ✅ always reload

    # Load bathrooms
    if not r.exists('bathrooms'):
        bathrooms = read_json_file('bathrooms.json', [])
        set_json('bathrooms', bathrooms)

    # Always initialize queue if missing
    if not r.exists('queue'):
        set_json('queue', [])

    print("✅ Data loaded into Redis")

if __name__ == '__main__':
    load_initial_data()
    threading.Thread(target=simulation, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5050)
