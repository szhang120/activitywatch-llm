import threading

conversation_active = False
conversation_lock = threading.Lock()

def set_conversation_active(active: bool):
    """
    Set the conversation_active flag.
    """
    global conversation_active
    with conversation_lock:
        conversation_active = active

def is_conversation_active() -> bool:
    """
    Check if a conversation is currently active.
    """
    global conversation_active
    with conversation_lock:
        return conversation_active
