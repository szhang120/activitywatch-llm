import re
import sqlite3
import subprocess

LLAMA_CPP_PATH = "/Users/seanzhang/llama.cpp/build/bin/llama-run"
MODEL_PATH = "/Users/seanzhang/llama.cpp/models/Meta-Llama-3.1-8B-Instruct-IQ2_M.gguf"
SUMMARY_MODEL_PATH = "/Users/seanzhang/llama.cpp/models/Meta-Llama-3.1-8B-Instruct-IQ2_M.gguf"

def retrieve_all_knowledge():
    """
    Returns all knowledge entries as a list of content strings.
    """
    conn = sqlite3.connect('knowledge_base.db')
    cursor = conn.cursor()

    cursor.execute('SELECT content FROM knowledge')
    knowledge_entries = cursor.fetchall()
    conn.close()
    return [entry[0] for entry in knowledge_entries]

def retrieve_all_knowledge_with_ids():
    """
    Returns all knowledge entries as a list of (id, content) tuples.
    """
    conn = sqlite3.connect('knowledge_base.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, content FROM knowledge')
    rows = cursor.fetchall()
    conn.close()
    return rows

def knowledge_count():
    """
    Returns the total number of entries in the knowledge base.
    """
    conn = sqlite3.connect('knowledge_base.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM knowledge')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def insert_knowledge_entry(content):
    """
    Inserts a single row of knowledge content. 
    Category column is unused, so store 'N/A' or blank.
    """
    conn = sqlite3.connect('knowledge_base.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO knowledge (content, category) VALUES (?, ?)",
        (content, "N/A")
    )
    conn.commit()
    conn.close()

def delete_knowledge_by_id(knowledge_id):
    """
    Deletes a single knowledge entry by its numeric id.
    """
    conn = sqlite3.connect('knowledge_base.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM knowledge WHERE id = ?", (knowledge_id,))
    conn.commit()
    conn.close()

def strip_ansi_escape_codes(text):
    """
    Remove ANSI escape codes from text.
    """
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def generate_personalized_response(user_input, knowledge_entries):
    # Build the prompt
    prompt = (
        "You are an assistant helping the user improve their productivity.\n"
        "The user has experienced decreased productivity recently.\n"
    )
    if knowledge_entries:
        prompt += (
            "Here are some key facts to keep in mind about the user, "
            "such as their traits, habits, and situation:\n"
        )
        for entry in knowledge_entries:
            prompt += f"- {entry}\n"
    prompt += (
        f"\nEngage/Respond to the user in one single response to help them get back on track. "
        f"Only respond as the Assistant. Do not include any text for the user. "
        f"Your complete response must be under 500 tokens. "
        f"If the user indicates a desire to end the conversation or go leave to do work, "
        f"then end with a concluding remark that includes one authentic relevant Chinese proverb, "
        f"in both authentic Mandarin Chinese characters and pinyin.\n\n"
        f"User: {user_input}\nAssistant:"
    )

    print(f"CONVERSATIONAL AGENT: GENERATING RESPONSE for prompt: {prompt}")

    result = subprocess.run(
        [
            LLAMA_CPP_PATH,
            "-m", MODEL_PATH,
            "-p", prompt,
            "-c", "900",
            "-ngl", "1"
        ],
        capture_output=True,
        text=True
    )

    response = result.stdout.strip()
    response_cleaned = strip_ansi_escape_codes(response)

    if "Assistant:" in response_cleaned:
        assistant_reply = response_cleaned.split('Assistant:')[-1].strip()
    else:
        assistant_reply = response_cleaned.strip()

    print(f"CONVERSATIONAL AGENT: RESPONSE = {response_cleaned}")
    print(f"CONVERSATIONAL AGENT: REPLY = {assistant_reply}")

    return assistant_reply

def summarize_conversation(conversation_history):
    print(f"Summary: Conversation History: {conversation_history}")

    conversation_text = ''
    for speaker, text in conversation_history:
        conversation_text += f"{speaker}: {text}\n"

    print(f"Summary: Conversation Text: {conversation_text}")

    prompt = (
        "Here is a conversation between a user seeking advice and a productivity assistant. "
        "Concisely yet correctly summarize any key insights about the user, which may be helpful "
        "to the assistant in serving the user's requests in the future. "
        "If there is not at least one specific such detail or trait mentioned by the user that would "
        "be important for future tasks, do not generate anything."
        "Your complete response must be under 40 tokens in length. "
        "Focus on key or important details mentioned by the user about their goals, habits, beliefs, or progress made.\n\n"
        f"{conversation_text}\n\nSummary:"
    )
    print("CONVERSATIONAL AGENT: SUMMARIZING CONVERSATION")
    result = subprocess.run(
        [
            LLAMA_CPP_PATH,
            "-m", SUMMARY_MODEL_PATH,
            "-p", prompt,
            "-c", "3072",
            "-ngl", "1"
        ],
        capture_output=True,
        text=True
    )

    response = result.stdout.strip()
    response_cleaned = strip_ansi_escape_codes(response)

    if "Summary:" in response_cleaned:
        summary_text = response_cleaned.split('Summary:')[-1].strip()
    else:
        summary_text = response_cleaned.strip()
    print(f"SUMMARY WRITTEN: {summary_text}")
    return summary_text