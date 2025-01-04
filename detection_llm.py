import subprocess
import re
from collections import defaultdict

LLAMA_CPP_PATH = "/Users/seanzhang/llama.cpp/build/bin/llama-run"
MODEL_PATH = "/Users/seanzhang/llama.cpp/models/Meta-Llama-3.1-8B-Instruct-Q3_K_L.gguf"
DISTRACTING_SITES = ["YouTube", "Instagram", "Reddit", "Linkedin"]

def strip_ansi_escape_codes(text):
    """
    Remove ANSI escape codes from text.
    """
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def condense_activity_durations(data):
    """
    Condense the data such that each activity appears once with its cumulative duration.
    Returns a dictionary with each activity name and its cumulative duration.
    """
    condensed_data = defaultdict(float)

    for entry in data:
        for activity, duration in entry.items():
            if activity.strip():
                condensed_data[activity] += duration

    return dict(condensed_data)

def detection_llm(aggregated_data_entry, running_context_entries):
    """
    Analyze aggregated logs using the quantized Llama model (via llama.cpp) to detect distractions.
    Returns "TRUE" if intervention is needed, "FALSE" otherwise.
    """
    print("DETECTION LLM FUNCTION CALLED ...")
    system_prompt = (
        "You are an assistant tasked with analyzing user activity logs for productivity interventions. Your goal is to determine whether an intervention is required to help the user regain focus. \n"
        f"The only intervention-worthy distracting activities are: {DISTRACTING_SITES}. \n"
        "Logs are recorded in seconds. A necessary, but not sufficient, condition for intervention is at least 60 seconds of distracting activity recorded in the recent logs. \n"
        "Do not hallucinate or make up activities that are not in either the recent or context logs. For the sake of double-checking, you must cite any intervention-worthy violation activity with its exact name, duration and neighboring activites. \n"
        "Output a one-sentence explanation, followed by exactly one word: 'TRUE' if based on the prior criteria an intervention is needed, or 'FALSE' otherwise. "
    )

    recent_logs = aggregated_data_entry['data']
    context_logs = condense_activity_durations([entry['data'] for entry in running_context_entries])

    input_text = f"{system_prompt}\n\nRecent Logs:\n{recent_logs}\n\nContext Logs:\n{context_logs}\n Decision: "

    print(f"GENERATING OUTPUT for INPUT: \n {input_text}")
    result = subprocess.run(
        [
            LLAMA_CPP_PATH,
            "-m", MODEL_PATH,
            "-p", input_text,
            "-c", "1792",
            "-ngl", "1"
        ],
        capture_output=True,
        text=True
    )
    output_text = result.stdout.strip()

    output_text = strip_ansi_escape_codes(output_text)
    print("OUTPUT GENERATED")
    print(f"Output from (1) detection LLM: {output_text}")

    decision_line = output_text.split('Decision: ')[-1].strip()

    decision = None
    if decision_line:
        match = re.search(r'\b(TRUE|FALSE)\b', decision_line, re.IGNORECASE)
        if match:
            decision = match.group(1).upper()

    if decision == 'TRUE':
        return 'TRUE'
    else:
        return 'FALSE'