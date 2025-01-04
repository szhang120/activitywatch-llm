from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit
import logging
import os

from conversational_agent_backend import (
    retrieve_all_knowledge_with_ids,
    knowledge_count,
    generate_personalized_response,
    summarize_conversation,
    insert_knowledge_entry,
    delete_knowledge_by_id
)

from shared_state import set_conversation_active, is_conversation_active

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secret_key')
app.config['SESSION_TYPE'] = 'filesystem'

socketio = SocketIO(app, ping_timeout=120, ping_interval=25)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

# Global conversation_history that resets on new conversation or end_chat
conversation_history = []

@app.route('/')
def index():
    """
    Renders the chat interface. If the global conversation is empty,
    start a new conversation and mark it as active. Also pass in
    knowledge_count for display logic (9-entry limit).
    """
    global conversation_history
    try:
        if not conversation_history:
            assistant_prompt = (
                "Hi, I've noticed you might be having trouble focusing. "
                "Could you tell me what's on your mind?"
            )
            conversation_history.append(["Assistant", assistant_prompt])
            set_conversation_active(True)
            logging.info("New conversation started and set to active.")

        current_knowledge_count = knowledge_count()

        return render_template(
            'chat.html',
            conversation_history=conversation_history,
            knowledge_count=current_knowledge_count
        )
    except Exception as e:
        logging.error(f"Error rendering chat interface: {e}", exc_info=True)
        return "An error occurred while loading the chat interface.", 500


@socketio.on('user_message')
def handle_user_message(json):
    """
    Handles inbound user messages from the chat interface,
    generates a response, and emits it back to the client.
    """
    global conversation_history
    try:
        user_input = json.get('message', '').strip()
        if not user_input:
            emit('assistant_message', {'message': "I didn't catch that. Can you rephrase?"})
            logging.debug("Received empty user input; prompted for rephrasing.")
            return

        logging.debug(f"Current conversation history before update: {conversation_history}")

        conversation_history.append(["User", user_input])
        logging.debug(f"Updated conversation history with user message: {conversation_history}")

        knowledge_entries_with_ids = retrieve_all_knowledge_with_ids()
        knowledge_only = [item[1] for item in knowledge_entries_with_ids]

        agent_response = generate_personalized_response(user_input, knowledge_only)
        logging.info(f"Assistant response generated: {agent_response}")

        conversation_history.append(["Assistant", agent_response])
        logging.debug(f"Updated conversation history with assistant response: {conversation_history}")

        emit('assistant_message', {'message': agent_response})
    except Exception as e:
        logging.error(f"Error handling user message: {e}", exc_info=True)
        emit('assistant_message', {'message': "An error occurred while processing your request."})


@app.route('/end_chat_no_save', methods=['POST'])
def end_chat_no_save():
    """
    Ends the chat WITHOUT saving any summary to the knowledge base.
    """
    global conversation_history
    try:
        logging.info("Ending chat with NO saving.")
        conversation_history.clear()
        set_conversation_active(False)
        return "Chat ended successfully, without saving."
    except Exception as e:
        logging.error(f"Error ending chat without saving: {e}", exc_info=True)
        return "An error occurred while ending the chat (no save).", 500

@app.route('/end_chat_save', methods=['POST'])
def end_chat_save():
    """
    Summarizes the conversation, then attempts to save it to the knowledge base.
    If the knowledge base is not at the limit (9 entries), we insert and end.
    If it IS at the limit, we redirect the user to a memory management page
    where they can choose to delete some entries or abandon saving.
    """
    global conversation_history
    try:
        logging.info("Ending chat WITH saving.")
        summary = summarize_conversation(conversation_history).strip()
        logging.info(f"Generated summary for saving: {summary}")

        if not summary:
            logging.info("Empty summary. Nothing to store. Ending chat.")
            conversation_history.clear()
            set_conversation_active(False)
            return "Chat ended successfully, no summary."

        if knowledge_count() < 9:
            insert_knowledge_entry(summary)
            logging.info("Inserted new summary into knowledge base (fewer than 9 entries).")

            conversation_history.clear()
            set_conversation_active(False)
            return "Chat ended successfully, after saving summary."
        else:
            session['pending_summary'] = summary
            logging.info("Knowledge base at 9. Redirecting to memory management.")
            return redirect(url_for('manage_memory'))

    except Exception as e:
        logging.error(f"Error ending chat with saving: {e}", exc_info=True)
        return "An error occurred while ending the chat (save).", 500

@app.route('/manage_memory')
def manage_memory():
    """
    Shows the user the existing 9 knowledge entries and the new summary.
    Allows them to select some knowledge to delete, or skip saving the new summary.
    """
    try:
        summary = session.get('pending_summary', '')
        if not summary:
            return redirect(url_for('index'))
        knowledge_list = retrieve_all_knowledge_with_ids()
        return render_template('manage_memory.html', knowledge_list=knowledge_list, summary=summary)
    except Exception as e:
        logging.error(f"Error loading manage_memory page: {e}", exc_info=True)
        return "An error occurred while managing memory.", 500


@app.route('/manage_memory_action', methods=['POST'])
def manage_memory_action():
    """
    Handles user actions from the memory management page.
    - If they clicked "Never Mind", we discard the pending summary and keep the existing 9.
    - If they clicked "Delete Selected & Save New Summary", we delete the chosen items, then insert the new summary.
    """
    global conversation_history
    try:
        action = request.form.get('action')
        summary = session.get('pending_summary', '')

        if action == 'never_mind':
            logging.info("User chose to NOT replace any memory. Discarding new summary.")

            session.pop('pending_summary', None)

            conversation_history.clear()
            set_conversation_active(False)
            return "Chat ended successfully, after no update was made."
        
        elif action == 'save_delete':
            if not summary:
                return redirect(url_for('index'))

            delete_ids = request.form.getlist('delete_ids')
            logging.info(f"Deleting the following knowledge IDs: {delete_ids}")
            for knowledge_id in delete_ids:
                delete_knowledge_by_id(knowledge_id)

            insert_knowledge_entry(summary)

            session.pop('pending_summary', None)

            conversation_history.clear()
            set_conversation_active(False)
            return "Chat ended successfully, after new summary."

        else:
            set_conversation_active(False)
            return "Chat ended unexpectedly."

    except Exception as e:
        set_conversation_active(False)
        logging.error(f"Error handling manage_memory_action: {e}", exc_info=True)
        return "An error occurred while processing your memory management action.", 500


@socketio.on('disconnect')
def handle_disconnect():
    """
    Handles client disconnections.
    """
    if not is_conversation_active():
        logging.info("Client disconnected voluntarily.")
    else:
        logging.warning("Client disconnected unexpectedly while conversation is active.")

