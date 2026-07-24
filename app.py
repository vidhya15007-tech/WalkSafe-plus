from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import smtplib
from email.mime.text import MIMEText
import heapq
import math
import os
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from email_validator import validate_email, EmailNotValidError

app = Flask(__name__)
app.secret_key = 'walksafe_secret_key'

# ==========================================================
# Admin credentials
# ==========================================================
admins = {
    "vidhya": "admin@123",
    "admin2": "admin@123"
}

# ==========================================================
# Graph (DSA Implementation: Dijkstra’s Algorithm)
# ==========================================================
graph = {
    "Chennai Central": {"T Nagar": 4, "Mylapore": 3, "Vepery": 5},
    "T Nagar": {"Anna Nagar": 6, "Adyar": 5, "Mylapore": 4, "Chennai Central": 4},
    "Mylapore": {"Adyar": 4, "Guindy": 5, "Chennai Central": 3, "T Nagar": 4},
    "Anna Nagar": {"Koyambedu": 3, "Vepery": 4, "T Nagar": 6},
    "Adyar": {"Besant Nagar": 3, "Guindy": 2, "T Nagar": 5, "Mylapore": 4},
    "Guindy": {"Koyambedu": 4, "Adyar": 2, "Mylapore": 5},
    "Koyambedu": {"Vepery": 2, "Anna Nagar": 3, "Guindy": 4, "Chennai Central": 6},
    "Vepery": {"Chennai Central": 5, "Anna Nagar": 4, "Koyambedu": 2},
    "Besant Nagar": {"Adyar": 3}
}

CHENNAI_LOCATIONS = sorted(graph.keys())
CHENNAI_COORDS = {
    "Chennai Central": [13.0827, 80.2707],
    "T Nagar": [13.0408, 80.2331],
    "Mylapore": [13.0404, 80.2560],
    "Anna Nagar": [13.0840, 80.2108],
    "Adyar": [13.0059, 80.2549],
    "Guindy": [13.0102, 80.2129],
    "Koyambedu": [13.0728, 80.2101],
    "Vepery": [13.0866, 80.2525],
    "Besant Nagar": [12.9983, 80.2708],
}

ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c * 1000


def find_nearest_node(lat, lng):
    if not lat or not lng:
        return None
    best_node = None
    best_distance = float('inf')
    for node, coords in CHENNAI_COORDS.items():
        distance = haversine(lat, lng, coords[0], coords[1])
        if distance < best_distance:
            best_distance = distance
            best_node = node
    return best_node


def dijkstra(graph, start, end):
    if start not in graph or end not in graph:
        return [], float('inf')

    queue = [(0, start)]
    distances = {node: float('inf') for node in graph}
    distances[start] = 0
    parent = {node: None for node in graph}

    while queue:
        current_dist, current_node = heapq.heappop(queue)
        if current_dist > distances[current_node]:
            continue
        for neighbor, weight in graph[current_node].items():
            distance = current_dist + weight
            if distance < distances[neighbor]:
                distances[neighbor] = distance
                parent[neighbor] = current_node
                heapq.heappush(queue, (distance, neighbor))

    if not math.isfinite(distances[end]):
        return [], float('inf')

    path, node = [], end
    while node is not None:
        path.append(node)
        node = parent[node]
    path.reverse()
    return path, distances[end]


def build_route_steps(path):
    if len(path) < 2:
        return []
    steps = []
    for index in range(len(path) - 1):
        start_point = path[index]
        end_point = path[index + 1]
        steps.append({
            "from": start_point,
            "to": end_point,
            "label": f"Move from {start_point} to {end_point}"
        })
    return steps


def build_visual_route(start_coords, end_coords, path_nodes):
    if not start_coords or not end_coords:
        return []
    coordinates = [start_coords]
    if path_nodes and len(path_nodes) > 1:
        for node in path_nodes[1:-1]:
            if node in CHENNAI_COORDS:
                coordinates.append(CHENNAI_COORDS[node])
    coordinates.append(end_coords)

    if ORS_API_KEY:
        try:
            payload = {"coordinates": [[coords[1], coords[0]] for coords in coordinates]}
            req = Request(
                "https://api.openrouteservice.org/v2/directions/foot-walking/geojson",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
            )
            with urlopen(req, timeout=10) as response:
                data = json.load(response)
                if data.get("features"):
                    return [[point[1], point[0]] for point in data["features"][0]["geometry"]["coordinates"]]
        except Exception as exc:
            print(f"ORS route failed: {exc}")
    return [[coord[0], coord[1]] for coord in coordinates]


def calculate_route_metrics(start_coords, end_coords, path_nodes):
    if not start_coords or not end_coords:
        return 0.0, 0
    coords = [start_coords]
    if path_nodes and len(path_nodes) > 1:
        for node in path_nodes[1:-1]:
            if node in CHENNAI_COORDS:
                coords.append(CHENNAI_COORDS[node])
    coords.append(end_coords)

    total_distance_km = 0.0
    for current, next_point in zip(coords, coords[1:]):
        total_distance_km += haversine(current[0], current[1], next_point[0], next_point[1]) / 1000.0
    time_minutes = max(1, int(round(total_distance_km / 5.0 * 60)))
    return round(total_distance_km, 2), time_minutes


def fetch_safety_points(lat, lng, radius=1500):
    if not lat or not lng:
        return {"police": [], "hospitals": []}

    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="police"](around:{radius},{lat},{lng});
      way["amenity"="police"](around:{radius},{lat},{lng});
      relation["amenity"="police"](around:{radius},{lat},{lng});
      node["amenity"="hospital"](around:{radius},{lat},{lng});
      way["amenity"="hospital"](around:{radius},{lat},{lng});
      relation["amenity"="hospital"](around:{radius},{lat},{lng});
    );
    out center;
    """

    try:
        req = Request(OVERPASS_URL, data=query.encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=12) as response:
            payload = json.load(response)
    except (URLError, HTTPError, ValueError) as exc:
        print(f"Overpass lookup failed: {exc}")
        return {"police": [], "hospitals": []}

    police = []
    hospitals = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        item_type = tags.get("amenity")
        if not item_type:
            continue
        lat_val = element.get("lat") or element.get("center", {}).get("lat")
        lon_val = element.get("lon") or element.get("center", {}).get("lon")
        if lat_val is None or lon_val is None:
            continue
        distance = haversine(float(lat), float(lng), float(lat_val), float(lon_val))
        info = {
            "name": tags.get("name") or ("Police Station" if item_type == "police" else "Hospital"),
            "lat": float(lat_val),
            "lng": float(lon_val),
            "distance": round(distance),
        }
        if item_type == "police":
            police.append(info)
        elif item_type == "hospital":
            hospitals.append(info)

    police = sorted(police, key=lambda item: item["distance"])[:6]
    hospitals = sorted(hospitals, key=lambda item: item["distance"])[:6]
    return {"police": police, "hospitals": hospitals}

# ==========================================================
# Users storage
# ==========================================================
def load_users():
    try:
        with open("users.json", "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users):
    with open("users.json", "w") as f:
        json.dump(users, f, indent=4)

# ==========================================================
# Email sending utility
# ==========================================================
def send_email(to_email, subject, body):
    sender_email = os.environ.get("WALKSAFE_EMAIL") or os.environ.get("EMAIL_ADDRESS") or os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("WALKSAFE_EMAIL_PASSWORD") or os.environ.get("EMAIL_PASSWORD") or os.environ.get("SMTP_PASSWORD")

    if not sender_email or not sender_password:
        error_msg = "Email sending skipped: WALKSAFE_EMAIL and WALKSAFE_EMAIL_PASSWORD environment variables are not set."
        print(f"Error: {error_msg}")
        return False, error_msg

    try:
        valid = validate_email(to_email)
        to_email = valid.email
    except EmailNotValidError as e:
        print(f"Invalid email: {to_email} - {e}")
        return False, f"Invalid email: {e}"

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True, "Sent"
    except Exception as e:
        print(f"Error sending email to {to_email}: {e}")
        return False, str(e)

# ==========================================================
# Routes
# ==========================================================
@app.route('/')
def index():
    return render_template("index.html")

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        users = load_users()
        username = request.form['username']
        password = request.form['password']
        contact1 = request.form['contact1']
        contact2 = request.form['contact2']

        if username in users:
            return render_template("signup.html", error="Username already exists!")

        contacts = [contact1, contact2]
        users[username] = {
            "password": password,
            "contacts": contacts,
            "feedback": [],
            "routes": [],
            "alerts": []
        }
        save_users(users)

        subject = "WalkSafe Signup Confirmation"
        body = f"{username} has signed up for WalkSafe. You are listed as an emergency contact."
        email_results = []
        for contact in contacts:
            success, msg = send_email(contact, subject, body)
            email_results.append((contact, success, msg))

        failed = [(c, m) for c, s, m in email_results if not s]
        if failed:
            error_msg = "Signup successful, but failed to send email to: " + ", ".join([f"{c} ({m})" for c, m in failed]) + ". Please check email sender configuration or try again."
            return render_template("signup.html", error=error_msg)

        return redirect(url_for('login'))

    return render_template("signup.html")

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        users = load_users()
        username = request.form['username']
        password = request.form['password']

        if username in users and users[username]['password'] == password:
            session['user'] = username
            return redirect(url_for('input_page'))

        return "Invalid credentials!"
    return render_template("login.html")

@app.route('/admin_login', methods=['POST'])
def admin_login():
    username = request.form['admin_username']
    password = request.form['admin_password']
    if username in admins and admins[username] == password:
        session['admin'] = username
        return redirect(url_for('admin_page'))
    return "Invalid admin credentials!"

@app.route('/admin')
def admin_page():
    if 'admin' not in session:
        return redirect(url_for('index'))
    users = load_users()
    stats = {
        "users": len(users),
        "feedbacks": sum(len(data.get('feedback', [])) for data in users.values()),
        "alerts": sum(len(data.get('alerts', [])) for data in users.values()),
        "routes": sum(len(data.get('routes', [])) for data in users.values()),
    }
    return render_template("admin.html", users=users, admin=session['admin'], stats=stats)

@app.route('/input', methods=['GET','POST'])
def input_page():
    if 'user' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        source = request.form['source']
        destination = request.form['destination']
        current_lat = request.form.get('current_lat')
        current_lng = request.form.get('current_lng')

        if source not in graph or destination not in graph:
            return render_template("input.html", locations=CHENNAI_LOCATIONS, error="Please choose only Chennai locations shown below.")

        session['source'] = source
        session['destination'] = destination
        session['gps_lat'] = float(current_lat) if current_lat else None
        session['gps_lng'] = float(current_lng) if current_lng else None
        session['gps_used'] = bool(current_lat and current_lng)
        return redirect(url_for('routes_page'))
    return render_template("input.html", locations=CHENNAI_LOCATIONS)

@app.route('/routes')
def routes_page():
    if 'user' not in session:
        return redirect(url_for('login'))

    source = session.get('source')
    destination = session.get('destination')

    if source not in graph or destination not in graph:
        return redirect(url_for('input_page'))

    gps_lat = session.get('gps_lat')
    gps_lng = session.get('gps_lng')
    gps_used = bool(session.get('gps_used')) and gps_lat is not None and gps_lng is not None

    route_source = source
    start_coords = CHENNAI_COORDS.get(source)
    if gps_used:
        nearest_node = find_nearest_node(float(gps_lat), float(gps_lng))
        if nearest_node:
            route_source = nearest_node
            start_coords = CHENNAI_COORDS[nearest_node]

    path, distance = dijkstra(graph, route_source, destination)
    steps = build_route_steps(path)
    safe_distance = distance if math.isfinite(distance) else 0

    route_start_coords = [float(gps_lat), float(gps_lng)] if gps_used else start_coords
    route_end_coords = CHENNAI_COORDS[destination]
    visual_route = build_visual_route(route_start_coords, route_end_coords, path)
    route_distance_km, route_time_minutes = calculate_route_metrics(route_start_coords, route_end_coords, path)

    session['route_path'] = path
    session['route_distance'] = safe_distance
    session['route_steps'] = steps
    session['route_visual'] = visual_route
    session['route_distance_km'] = route_distance_km
    session['route_time_minutes'] = route_time_minutes
    session['route_source'] = route_source
    session['route_start_coords'] = route_start_coords
    session['route_end_coords'] = route_end_coords
    session['gps_used'] = gps_used

    users = load_users()
    users[session['user']]['routes'].append({
        "source": source,
        "destination": destination,
        "path": path,
        "distance": round(route_distance_km, 2),
        "time": route_time_minutes,
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "gps_used": gps_used,
    })
    save_users(users)

    return render_template(
        "routes.html",
        source=source,
        destination=destination,
        path=path,
        distance=safe_distance,
        route_distance_km=route_distance_km,
        route_time_minutes=route_time_minutes,
        gps_used=gps_used,
    )

@app.route('/map')
def map_page():
    if 'user' not in session:
        return redirect(url_for('login'))

    source = session.get('source')
    destination = session.get('destination')

    if source not in graph or destination not in graph:
        return redirect(url_for('input_page'))

    route_path = session.get('route_path') or []
    route_steps = session.get('route_steps') or []
    route_distance = session.get('route_distance')
    route_visual = session.get('route_visual') or []
    route_distance_km = session.get('route_distance_km', 0)
    route_time_minutes = session.get('route_time_minutes', 0)
    gps_used = bool(session.get('gps_used'))

    if not route_path or not isinstance(route_distance, (int, float)) or not math.isfinite(route_distance):
        route_path, route_distance = dijkstra(graph, source, destination)
        route_steps = build_route_steps(route_path)
        session['route_path'] = route_path
        session['route_distance'] = route_distance if math.isfinite(route_distance) else 0
        session['route_steps'] = route_steps

    route_distance = route_distance if isinstance(route_distance, (int, float)) and math.isfinite(route_distance) else 0
    start_coords = session.get('route_start_coords') or CHENNAI_COORDS.get(source)
    end_coords = session.get('route_end_coords') or CHENNAI_COORDS.get(destination)

    return render_template(
        "map.html",
        source=source,
        destination=destination,
        route_path=route_path,
        route_steps=route_steps,
        route_distance=route_distance,
        route_visual=route_visual,
        route_distance_km=route_distance_km,
        route_time_minutes=route_time_minutes,
        coordinates=CHENNAI_COORDS,
        start_coords=start_coords,
        end_coords=end_coords,
        gps_used=gps_used,
    )

@app.route('/api/safety')
def safety_api():
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    return jsonify(fetch_safety_points(lat, lng))

@app.route('/feedback', methods=['GET','POST'])
def feedback_page():
    if 'user' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        feedback = request.form['feedback']
        users = load_users()
        users[session['user']]['feedback'].append(feedback)
        save_users(users)
        return redirect(url_for('final_page'))
    return render_template("feedback.html")

@app.route('/final')
def final_page():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template("final.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/alert', methods=['POST'])
def alert():
    username = session.get('user')
    if not username:
        return jsonify({"status": "failed", "reason": "No user logged in"})

    users = load_users()
    if username in users:
        contacts = users[username]['contacts']
        subject = "WalkSafe Emergency Alert"
        body = f"Emergency! {username} triggered WalkSafe alert."
        email_results = []
        for contact in contacts:
            success, msg = send_email(contact, subject, body)
            email_results.append((contact, success, msg))

        failed = [c for c, s, m in email_results if not s]
        users[username]['alerts'].append(f"Emergency email sent to {contacts}. Failed: {failed if failed else 'None'}")
        save_users(users)

        if failed:
            return jsonify({
                "status": "partial",
                "failed": failed,
                "reason": "Some contacts could not receive the alert.",
                "message": "Emergency alert was sent to available contacts. A few contacts were unreachable."
            })

        return jsonify({
            "status": "success",
            "message": "Emergency alert successfully sent to all your trusted contacts."
        })

    return jsonify({"status": "failed", "reason": "User not found"})

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, debug=True)
