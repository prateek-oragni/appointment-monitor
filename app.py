import json
import threading
import time
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, send_from_directory, render_template_string

from monitor import check_page, log_result, DATA_DIR, LOG_FILE

app = Flask(__name__)

CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "1800"))

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Gentle Dental Monitor</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="60">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; padding: 20px; }
        h1 { margin-bottom: 20px; }
        .status-badge { display: inline-block; padding: 8px 16px; border-radius: 6px; font-weight: bold; font-size: 1.2em; margin-bottom: 20px; }
        .status-online { background: #d4edda; color: #155724; }
        .status-offline { background: #f8d7da; color: #721c24; }
        .status-error { background: #fff3cd; color: #856404; }
        .status-unknown { background: #e2e3e5; color: #383d41; }
        .stats { display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
        .stat { background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 150px; }
        .stat-value { font-size: 1.5em; font-weight: bold; }
        .stat-label { color: #666; font-size: 0.9em; }
        table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
        th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; }
        .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
        .dot-online { background: #28a745; }
        .dot-offline { background: #dc3545; }
        .dot-error { background: #ffc107; }
        .dot-unknown { background: #6c757d; }
        img { max-width: 100%; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .screenshot-section { margin-top: 20px; }
    </style>
</head>
<body>
    <h1>Gentle Dental Booking Monitor</h1>

    {% if latest %}
    <div class="status-badge status-{{ latest.status }}">
        {{ latest.status | upper }}
    </div>
    <p style="margin-bottom:20px; color:#666;">Last check: {{ latest.timestamp }} &mdash; {{ latest.detail }}</p>
    {% else %}
    <div class="status-badge status-unknown">NO DATA YET</div>
    <p style="margin-bottom:20px; color:#666;">Waiting for first check...</p>
    {% endif %}

    <div class="stats">
        <div class="stat"><div class="stat-value">{{ total }}</div><div class="stat-label">Total Checks</div></div>
        <div class="stat"><div class="stat-value">{{ uptime_pct }}%</div><div class="stat-label">Uptime</div></div>
        <div class="stat"><div class="stat-value">{{ online }}</div><div class="stat-label">Online</div></div>
        <div class="stat"><div class="stat-value">{{ offline }}</div><div class="stat-label">Offline</div></div>
        <div class="stat"><div class="stat-value">{{ errors }}</div><div class="stat-label">Errors</div></div>
    </div>

    <h2 style="margin-bottom:10px;">Check History</h2>
    <table>
        <thead><tr><th>Time</th><th>Status</th><th>Detail</th><th>Screenshot</th></tr></thead>
        <tbody>
        {% for c in checks | reverse %}
        <tr>
            <td>{{ c.timestamp }}</td>
            <td><span class="dot dot-{{ c.status }}"></span>{{ c.status }}</td>
            <td>{{ c.detail }}</td>
            <td>{% if c.screenshot %}<a href="/screenshots/{{ c.screenshot }}">view</a>{% endif %}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>

    {% if latest_screenshot %}
    <div class="screenshot-section">
        <h2 style="margin-bottom:10px;">Latest Screenshot</h2>
        <img src="/screenshots/{{ latest_screenshot }}" alt="Latest screenshot">
    </div>
    {% endif %}
</body>
</html>
"""


def load_checks():
    if not LOG_FILE.exists():
        return []
    entries = []
    for line in LOG_FILE.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def get_latest_screenshot():
    ss_dir = DATA_DIR / "screenshots"
    if not ss_dir.exists():
        return None
    files = sorted(ss_dir.glob("screenshot_*.png"))
    return files[-1].name if files else None


def monitor_loop():
    while True:
        result = check_page(headless=True)
        ss_name = None
        ss_dir = DATA_DIR / "screenshots"
        if ss_dir.exists():
            files = sorted(ss_dir.glob("screenshot_*.png"))
            if files:
                ss_name = files[-1].name
        result["screenshot"] = ss_name
        log_result(result)
        time.sleep(CHECK_INTERVAL)


@app.route("/")
def dashboard():
    checks = load_checks()
    total = len(checks)
    online = sum(1 for c in checks if c.get("status") == "online")
    offline = sum(1 for c in checks if c.get("status") == "offline")
    errors = sum(1 for c in checks if c.get("status") == "error")
    uptime_pct = round(100 * online / total, 1) if total else 0
    latest = checks[-1] if checks else None
    latest_screenshot = get_latest_screenshot()

    return render_template_string(
        DASHBOARD_HTML,
        latest=latest,
        checks=checks,
        total=total,
        online=online,
        offline=offline,
        errors=errors,
        uptime_pct=uptime_pct,
        latest_screenshot=latest_screenshot,
    )


@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    return send_from_directory(DATA_DIR / "screenshots", filename)


@app.route("/api/status")
def api_status():
    checks = load_checks()
    total = len(checks)
    online = sum(1 for c in checks if c.get("status") == "online")
    uptime_pct = round(100 * online / total, 1) if total else 0
    return jsonify({
        "current_status": checks[-1]["status"] if checks else "unknown",
        "last_check": checks[-1]["timestamp"] if checks else None,
        "uptime_pct": uptime_pct,
        "total_checks": total,
        "checks": checks,
    })


if __name__ == "__main__":
    (DATA_DIR / "screenshots").mkdir(parents=True, exist_ok=True)

    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=8080)
