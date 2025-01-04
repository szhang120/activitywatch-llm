import requests
import time
import sqlite3
import threading
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

ACTIVITYWATCH_SERVER = 'http://localhost:5600'
WINDOW_BUCKET = 'aw-watcher-window_MacBookAir.fios-router.home'
AFK_BUCKET = 'aw-watcher-afk_MacBookAir.fios-router.home'

FETCH_INTERVAL = 30
TIME_WINDOW = 60 * 5
CONTEXT_WINDOW = 60 * 15

conn = sqlite3.connect('activity_logs.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS aggregated_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    data TEXT NOT NULL
)
''')
conn.commit()

logging.info("Resetting aggregated_logs table on startup.")
cursor.execute('DELETE FROM aggregated_logs')
conn.commit()

running_context = []
running_context_lock = threading.Lock()

def fetch_events(bucket_id, start_iso, end_iso):
    """
    Fetch events from the specified ActivityWatch bucket within the given time range.
    """
    url = f"{ACTIVITYWATCH_SERVER}/api/0/buckets/{bucket_id}/events"
    params = {"start": start_iso, "end": end_iso}
    headers = {'Cache-Control': 'no-cache'}

    response = requests.get(url, params=params, headers=headers, timeout=10)
    response.raise_for_status()

    return response.json()

def filter_non_afk_events(window_events, afk_events):
    """
    Filter window events to include only those during non-AFK periods.
    """
    not_afk_periods = [event for event in afk_events if event['data'].get('status') == 'not-afk']
    filtered_events = []

    for event in window_events:
        event_start = datetime.fromisoformat(event['timestamp'])
        event_end = event_start + timedelta(seconds=event['duration'])

        for period in not_afk_periods:
            period_start = datetime.fromisoformat(period['timestamp'])
            period_end = period_start + timedelta(seconds=period['duration'])

            if event_start < period_end and event_end > period_start:
                filtered_events.append(event)
                break

    return filtered_events

def aggregate_durations(events):
    """
    Aggregate time spent on each activity.
    """
    durations = defaultdict(float)
    for event in events:
        title = event.get('data', {}).get('title', 'Unknown')
        duration = event.get('duration', 0)
        durations[title] += duration
    return dict(durations)

def maintain_running_context(aggregated_data):
    """
    Maintain running context -- no overlap with recent.
    """
    with running_context_lock:
        running_context.append(aggregated_data)
        current_time = datetime.now(timezone.utc) - timedelta(seconds=TIME_WINDOW)
        cutoff_time = current_time - timedelta(seconds=CONTEXT_WINDOW)

        while running_context and datetime.fromisoformat(running_context[0]['end_time']) < cutoff_time:
            running_context.pop(0)

def store_aggregated_data(start_time, end_time, aggregated_data):
    """
    Store the aggregated data in the SQLite database.
    """
    cursor.execute('''
        INSERT INTO aggregated_logs (start_time, end_time, data)
        VALUES (?, ?, ?)
    ''', (start_time.isoformat(), end_time.isoformat(), str(aggregated_data)))
    conn.commit()


def log_watcher():
    """
    Main function for processing logs.
    """
    logging.info("Starting ActivityWatch Log Watcher...")
    last_fetched_time = datetime.now(timezone.utc) - timedelta(seconds=TIME_WINDOW)

    while True:
        end_time = datetime.now(timezone.utc)
        start_time = last_fetched_time

        logging.info(f"Fetching events from {start_time.isoformat()} to {end_time.isoformat()}")

        start_iso = start_time.isoformat()
        end_iso = end_time.isoformat()

        window_events = fetch_events(WINDOW_BUCKET, start_iso, end_iso)
        afk_events = fetch_events(AFK_BUCKET, start_iso, end_iso)

        if window_events is None or afk_events is None:
            logging.error("Failed to fetch events. Retrying...")
            time.sleep(FETCH_INTERVAL)
            continue

        filtered_events = filter_non_afk_events(window_events, afk_events)

        aggregated_data = aggregate_durations(filtered_events)
        aggregated_data_entry = {
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'data': aggregated_data
        }

        maintain_running_context(aggregated_data_entry)
        store_aggregated_data(start_time, end_time, aggregated_data)
        logging.info(f"Aggregated data from {start_time.isoformat()} to {end_time.isoformat()} stored.")
        last_fetched_time = end_time

        time.sleep(FETCH_INTERVAL)

if __name__ == "__main__":
    watcher_thread = threading.Thread(target=log_watcher)
    watcher_thread.daemon = True
    watcher_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down Log Watcher.")
        conn.close()