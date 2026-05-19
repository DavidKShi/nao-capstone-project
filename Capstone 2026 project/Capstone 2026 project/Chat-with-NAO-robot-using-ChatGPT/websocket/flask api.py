from flask import Flask, request, jsonify
import os
import json
import traceback

# Try to import OpenAI - supports both old and new API
try:
    from openai import OpenAI
    OPENAI_NEW_API = True
except ImportError:
    try:
        import openai
        OPENAI_NEW_API = False
    except ImportError:
        print("ERROR: OpenAI library not installed. Run: pip3 install openai")
        exit(1)

app = Flask(__name__)

# ---------------------------------------------------------------------------
#  Dance play-count tracker (persisted to disk)
# ---------------------------------------------------------------------------
DANCE_COUNTS_FILE = os.path.join(os.path.dirname(__file__), "dance_counts.json")

def _load_dance_counts():
    try:
        with open(DANCE_COUNTS_FILE, "r") as f:
            return json.load(f)
    except (IOError, ValueError):
        return {}

def _save_dance_counts(counts):
    try:
        with open(DANCE_COUNTS_FILE, "w") as f:
            json.dump(counts, f, indent=2)
    except IOError as e:
        print("[DanceCounts] Save error: {}".format(e))

dance_counts = _load_dance_counts()
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    print("API key is missing")

# Initialize OpenAI client based on API version
if OPENAI_NEW_API:
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
    else:
        client = None
else:
    if OPENAI_API_KEY:
        openai.api_key = OPENAI_API_KEY
    else:
        openai.api_key = ""


# System prompt: tells GPT it is a NAO robot
SYSTEM_PROMPT = (
    "You are NAO, a friendly humanoid robot made by SoftBank Robotics. "
    "You are physically present in the room, interacting with people face to face. "
    "You have a small white body, cameras for eyes, and you can walk, dance, and gesture. "
    "Always respond as NAO the robot, never as ChatGPT or an AI language model. "
    "Keep your answers to 3 sentences or less. Be warm, playful, and helpful."
)


@app.route('/chat', methods=['POST'])
def chat():
    if not OPENAI_API_KEY:
        return jsonify({"error": "API key not configured."}), 500

    user_input = request.json.get("input")
    if not user_input:
        return jsonify({"error": "No input provided."}), 400

    # Accept optional conversation history from the caller.
    # If provided, we continue the conversation; otherwise start fresh.
    user_name = request.json.get("user_name")
    history = request.json.get("history", [])
    if not history:
        system_content = SYSTEM_PROMPT
        if user_name:
            system_content += (
                " The person you are currently talking to is named {}."
                " Use their name naturally in conversation."
            ).format(user_name)
        history = [{"role": "system", "content": system_content}]

    history.append({"role": "user", "content": user_input})

    try:
        if OPENAI_NEW_API:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=history
            )
            reply = response.choices[0].message.content
        else:
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=history
            )
            reply = response['choices'][0]['message']['content']

        history.append({"role": "assistant", "content": reply})

        return jsonify({"response": reply, "history": history})

    except Exception as e:
        print("Error calling OpenAI API:", e)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

CHOREOGRAPH_SYSTEM_PROMPT = (
    "You are a dance choreographer for a NAO humanoid robot. "
    "Given a song name, artist, and the play-count of every available dance, "
    "choose exactly 3 dances that match the song's energy, mood, tempo, and style.\n\n"
    "VARIETY RULES (strict):\n"
    "1. At least 2 of the 3 dances MUST be among the LEAST-played dances "
    "(those with the lowest play counts).\n"
    "2. Never pick the same dance more than once in a single sequence.\n"
    "3. Strongly prefer dances that have been played fewer times overall.\n"
    "4. Only choose a high-count dance if it is an exceptionally good fit "
    "for this specific song AND the other 2 slots are already low-count dances.\n\n"
    "SONG-SPECIFIC RULE (strict):\n"
    "5. NEVER include the \"saxophone\" dance in your picks. "
    "It is handled separately and must not appear in your response.\n\n"
    "Return ONLY a JSON array of exactly 3 unique dance name strings, nothing else. "
    "Example: [\"tai_chi\", \"elephant\", \"disco\"]"
)


def _call_gpt(messages):
    """Shared helper to call GPT and return the reply text."""
    if OPENAI_NEW_API:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        return response.choices[0].message.content
    else:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages
        )
        return response['choices'][0]['message']['content']


def _parse_dance_sequence(reply, available_dances):
    """Extract a JSON array from GPT's reply and validate dance names."""
    text = reply.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    sequence = json.loads(text)
    if not isinstance(sequence, list) or len(sequence) == 0:
        raise ValueError("GPT returned empty or non-list: {}".format(reply))

    available_set = set(available_dances)
    valid = [d for d in sequence if d in available_set]
    if not valid:
        raise ValueError("No valid dances in GPT response: {}".format(sequence))
    return valid[:3]


def _is_epic_sax_guy(song, artist):
    """Check if the identified track is Epic Sax Guy or a close variant."""
    s = (song or "").lower()
    a = (artist or "").lower()
    sax_titles = ["epic sax guy", "epicsaxguy", "run away", "sax guy"]
    sax_artists = ["sunstroke project", "sunstroke", "epic sax guy"]
    return any(t in s for t in sax_titles) or any(ar in a for ar in sax_artists)


@app.route('/choreograph', methods=['POST'])
def choreograph():
    """Return an ordered dance sequence for a given song."""
    global dance_counts
    if not OPENAI_API_KEY:
        return jsonify({"error": "API key not configured."}), 500

    song = request.json.get("song")
    artist = request.json.get("artist", "Unknown")
    available_dances = request.json.get("available_dances", [])

    if not song:
        return jsonify({"error": "No song provided."}), 400
    if not available_dances:
        return jsonify({"error": "No available_dances provided."}), 400

    if _is_epic_sax_guy(song, artist) and "saxophone" in available_dances:
        print("[Choreograph] Epic Sax Guy detected -> saxophone only")
        return jsonify({"sequence": ["saxophone"]})

    gpt_dances = [d for d in available_dances if d != "saxophone"]
    counts_for_prompt = {d: dance_counts.get(d, 0) for d in gpt_dances}
    sorted_counts = sorted(counts_for_prompt.items(), key=lambda x: x[1])

    user_msg = (
        "Song: \"{song}\" by {artist}.\n"
        "Available dances with play counts (lower = less used, prioritize these):\n"
        "{counts}\n\n"
        "Remember: at least 2 of your 3 picks MUST come from the least-played dances. "
        "All 3 must be different. Return ONLY a JSON array."
    ).format(
        song=song,
        artist=artist,
        counts="\n".join("  {} : {} plays".format(d, c) for d, c in sorted_counts),
    )

    messages = [
        {"role": "system", "content": CHOREOGRAPH_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    MAX_ATTEMPTS = 2
    for attempt in range(MAX_ATTEMPTS):
        try:
            reply = _call_gpt(messages)
            print("[Choreograph] GPT reply (attempt {}): {}".format(
                attempt + 1, reply.strip()))
            sequence = _parse_dance_sequence(reply, gpt_dances)
            print("[Choreograph] Sequence: {}".format(sequence))
            print("[Choreograph] Dance counts before: {}".format(
                json.dumps(counts_for_prompt)))
            return jsonify({"sequence": sequence})
        except (json.JSONDecodeError, ValueError) as e:
            print("[Choreograph] Parse error (attempt {}): {}".format(
                attempt + 1, e))
            if attempt < MAX_ATTEMPTS - 1:
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content":
                    "That was not valid JSON. Return ONLY a JSON array of "
                    "dance names from: {}".format(json.dumps(gpt_dances))
                })
            else:
                return jsonify({"error": "Could not parse GPT response",
                                "raw": reply}), 500
        except Exception as e:
            print("[Choreograph] Error: {}".format(e))
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Unexpected failure"}), 500


@app.route('/dance_executed', methods=['POST'])
def dance_executed():
    """Called by song_listener after each dance is actually performed."""
    global dance_counts
    dance_name = request.json.get("dance")
    if dance_name:
        dance_counts[dance_name] = dance_counts.get(dance_name, 0) + 1
        _save_dance_counts(dance_counts)
        print("[DanceCounts] {} -> {}".format(dance_name, dance_counts[dance_name]))
    return jsonify({"counts": dance_counts})


@app.route('/dance_counts', methods=['GET'])
def get_dance_counts():
    """View current dance play counts."""
    return jsonify(dance_counts)


@app.route('/dance_counts/reset', methods=['POST'])
def reset_dance_counts():
    """Reset all dance play counts to zero."""
    global dance_counts
    dance_counts = {}
    _save_dance_counts(dance_counts)
    print("[DanceCounts] All counts reset.")
    return jsonify({"message": "Dance counts reset.", "counts": dance_counts})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)