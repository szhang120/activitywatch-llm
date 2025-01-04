import threading
import time
import logging
import os
import subprocess
import webbrowser
import platform
from datetime import datetime, timedelta, timezone

from log_watcher import log_watcher, running_context, running_context_lock
from detection_llm import detection_llm
from app import socketio, app
from shared_state import is_conversation_active, set_conversation_active

# UTC formatting for logs
class UTCFormatter(logging.Formatter):
    converter = time.gmtime

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, timezone.utc)
        if datefmt:
            return dt.strftime(datefmt)
        else:
            return dt.isoformat()

formatter = UTCFormatter(
    fmt='%(asctime)s %(levelname)s:%(threadName)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

file_handler = logging.FileHandler("main.log")
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.handlers = []
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# GLOBAL NOTIFICATION SUPPRESSION
notifications_suppressed = False
notifications_suppressed_until = datetime.min.replace(tzinfo=timezone.utc)
notifications_suppression_lock = threading.Lock()

def trigger_desktop_notification_with_response(title, message, timeout=30):
    """
    Sends a macOS notification with 'Accept'/'Deny' options. Returns the user's response.
    """
    script = f'''
    set userChoice to button returned of (display dialog "{message}" with title "{title}" buttons {{"Deny", "Accept"}} default button "Accept")
    return userChoice
    '''
    try:
        logging.info("Sending desktop notification for user response.")
        process = subprocess.Popen(['osascript', '-e', script],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=timeout)
        if process.returncode != 0:
            logging.error(f"AppleScript Error: {stderr.decode('utf-8').strip()}")
            return 'Deny'
        user_choice = stdout.decode('utf-8').strip()
        logging.info(f"User selected: {user_choice}")
        return user_choice
    except subprocess.TimeoutExpired:
        process.kill()
        logging.error("AppleScript timed out while waiting for user response.")
        return 'Deny'

def trigger_delay_notification_with_response(title, message, timeout=60):
    """
    Sends a macOS notification to choose delay duration with predefined options or custom input.
    Returns the delay duration in minutes as an integer.
    """
    delay_minutes = None

    script = f'''
    set delayChoice to button returned of (display dialog "{message}" with title "{title}" buttons {{"5 mins", "15 mins", "Custom"}} default button "5 mins")
    return delayChoice
    '''
    try:
        logging.info("Sending desktop notification for delay duration selection.")
        process = subprocess.Popen(['osascript', '-e', script],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=timeout)
        if process.returncode != 0:
            logging.error(f"AppleScript Error: {stderr.decode('utf-8').strip()}")
            return 5
        delay_choice = stdout.decode('utf-8').strip()
        logging.info(f"User selected delay choice: {delay_choice}")

        if delay_choice == "Custom":
            custom_script = f'''
            set userInput to text returned of (display dialog "Enter delay duration in minutes:" with title "{title}" default answer "10")
            return userInput
            '''
            try:
                logging.info("Sending desktop notification for custom delay input.")
                custom_process = subprocess.Popen(['osascript', '-e', custom_script],
                                                    stdout=subprocess.PIPE,
                                                    stderr=subprocess.PIPE)
                custom_stdout, custom_stderr = custom_process.communicate(timeout=timeout)
                if custom_process.returncode != 0:
                    logging.error(f"AppleScript Error: {custom_stderr.decode('utf-8').strip()}")
                    return 5
                custom_input = custom_stdout.decode('utf-8').strip()
                try:
                    delay_minutes = int(custom_input)
                    logging.info(f"Custom delay input: {delay_minutes} minutes")
                except ValueError:
                    delay_minutes = 5
                    logging.warning(f"Invalid custom delay input: '{custom_input}'. Defaulting to 5 minutes.")
            except subprocess.TimeoutExpired:
                custom_process.kill()
                logging.error("AppleScript timed out while waiting for custom delay input.")
                return 5
        else:
            try:
                delay_minutes = int(delay_choice.split()[0])
                logging.info(f"Parsed delay minutes: {delay_minutes} minutes")
            except ValueError:
                delay_minutes = 5
                logging.warning(f"Invalid delay choice: '{delay_choice}'. Defaulting to 5 minutes.")
    except subprocess.TimeoutExpired:
        process.kill()
        logging.error("AppleScript timed out while waiting for delay duration selection.")
        return 5

    logging.info(f"Delay set to {delay_minutes} minute(s).")
    return delay_minutes

def intervention_handler():
    """
    Runs detection LLM logic. On "TRUE", checks if notifications are suppressed or if a conversation is active. 
    Sends notification accordingly.
    """
    global notifications_suppressed, notifications_suppressed_until

    logging.info("Entering intervention_handler.")

    with running_context_lock:
        if not running_context:
            logging.warning("No aggregated data available.")
            return
        aggregated_data_entry = running_context[-1]
        running_context_entries = running_context[:-1] if len(running_context) > 1 else []
        logging.debug(f"Aggregated Data Entry: {aggregated_data_entry}")
        logging.debug(f"Running Context Entries: {running_context_entries}")

    # Check global permission, optionally run Detection LLM.
    if is_conversation_active():
        logging.info("Detected a conversation is active - Skipping Detection LLM invocation.")
        return
    else:
        decision = detection_llm(aggregated_data_entry, running_context_entries)
        logging.info(f"Detection LLM decision: {decision}")

    if decision == 'TRUE':
        now_utc = datetime.now(timezone.utc)

        if is_conversation_active():
            logging.info("Conversation is active - skipping user prompt or notifications.")
            return

        with notifications_suppression_lock:
            if notifications_suppressed and now_utc < notifications_suppressed_until:
                logging.info(
                    f"Detection is TRUE, but notifications are suppressed until "
                    f"{notifications_suppressed_until.isoformat()} UTC. Skipping notification."
                )
                return
            else:
                if notifications_suppressed and now_utc >= notifications_suppressed_until:
                    notifications_suppressed = False
                    notifications_suppressed_until = datetime.min.replace(tzinfo=timezone.utc)
                    logging.info("Notifications were suppressed, but suppression window ended. Re-enabling notifications.")

        title = "Productivity Alert"
        message = "We detected a dip in your productivity. Would you like to chat about it?"
        user_response = trigger_desktop_notification_with_response(title, message)

        if user_response == 'Accept':
            logging.info("User accepted the invitation to chat.")
            set_conversation_active(True)
            logging.info("New conversation started and set to active.")
            webbrowser.open('http://localhost:5050')
            logging.info("Chat interface opened successfully.")

        else:
            logging.info("User selected 'Deny'. Prompting for delay duration.")
            delay_title = "Notification Delay"
            delay_message = "Choose how long you want to delay future productivity alerts:"
            delay_minutes = trigger_delay_notification_with_response(delay_title, delay_message)

            if delay_minutes:
                with notifications_suppression_lock:
                    notifications_suppressed = True
                    notifications_suppressed_until = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
                    logging.info(
                        f"Notifications suppressed until {notifications_suppressed_until.isoformat()} UTC "
                        f"(for {delay_minutes} minute(s))."
                    )
            else:
                with notifications_suppression_lock:
                    notifications_suppressed = True
                    notifications_suppressed_until = datetime.now(timezone.utc) + timedelta(minutes=5)
                    logging.warning(
                        f"Failed to parse delay. Defaulting to 5 minutes. "
                        f"Notifications suppressed until {notifications_suppressed_until.isoformat()} UTC."
                    )
    else:
        logging.info("Detection LLM decision is not 'TRUE'. No action taken.")

def intervention_monitor():
    """
    Background thread, runs intervention_handler(). 
    """
    logging.info("Intervention Monitor thread started.")

    while True:
        logging.info("Checking for possible intervention.")
        intervention_handler()
        time.sleep(300)

if __name__ == "__main__":
    # Log Watcher
    watcher_thread = threading.Thread(target=log_watcher, name="LogWatcherThread")
    watcher_thread.start()
    logging.info("Log Watcher started.")

    # Intervention Monitor
    intervention_thread = threading.Thread(target=intervention_monitor, name="InterventionMonitorThread")
    intervention_thread.start()
    logging.info("Intervention Monitor started.")

    # Conversational Agent
    logging.info("Starting Flask app for the Conversational Agent.")
    socketio.run(app, host='0.0.0.0', port=5050, debug=False)