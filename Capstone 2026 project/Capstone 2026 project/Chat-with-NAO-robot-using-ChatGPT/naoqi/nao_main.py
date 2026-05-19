"""
NAO State Machine Controller
=============================
States:
  IDLE                  - Listen for wake words + scan for faces simultaneously.
  CONVERSATIONAL        - Process a voice command / GPT question (exclusive).
  FACIAL_RECOGNITION    - Greet a known user or register an unknown one (exclusive).
  LISTEN_AND_DANCE      - Listen to music, analyse tone, dance accordingly (exclusive).

Transitions:
  IDLE  --wake word detected--->  CONVERSATIONAL      --done-->  IDLE
  IDLE  --face detected-------->  FACIAL_RECOGNITION  --done-->  IDLE
  IDLE  --dance command-------->  LISTEN_AND_DANCE    --done-->  IDLE
"""

from naoqi import ALProxy
from nao_transcribe import (
    detect_and_record_speech,
    transcribe_audio,
    send_to_flask_api,
    speak_response,
    transfer_file,
    wait_for_speech_to_finish
)
import threading
import time

try:
    from Queue import Queue, Empty   # Python 2
except ImportError:
    from queue import Queue, Empty   # Python 3

from speech import detect_wake_word_speech
from nao_facial_recog import (
    init_camera,
    grab_and_recognize_one_frame,
    cleanup_camera,
    should_interact_with_faces,
    handle_recognition_results,
    GREETED_USERS,
    GREETED_USERS_LOCK
)

# Configuration
ROBOT_IP = "YOUR_ROBOT_IP"  # Replace with your NAO robot's IP
ROBOT_PORT = 9559
LOCAL_FILE = "./speech.wav"

# Tracks the most recently recognized known user (set by face_scan_worker).
# Read by handle_conversational_state so GPT knows who it's talking to.
last_recognized_user = None
last_recognized_user_lock = threading.Lock()

# State constants
STATE_IDLE = "IDLE"
STATE_CONVERSATIONAL = "CONVERSATIONAL"
STATE_FACIAL_RECOGNITION = "FACIAL_RECOGNITION"
STATE_LISTEN_AND_DANCE = "LISTEN_AND_DANCE"


# =============================================================================
#  Command functions (called from the CONVERSATIONAL state)
#  Add new commands here -- they are automatically available via COMMAND_MAP.
# =============================================================================

# Map of command keywords -> handler functions.
# Each handler receives (audio_tts, question_text).
COMMAND_MAP = {
}


# =============================================================================
#  Worker threads (run during IDLE, paused during active states)
# =============================================================================

def wake_word_worker(event_queue, stop_event):
    """
    Background thread: continuously listens for wake words AND dance commands.
    Puts ("WAKE_WORD",) or ("DANCE_COMMAND",) in the queue accordingly.
    Respects stop_event to pause/resume cleanly.
    """
    while True:
        if stop_event.is_set():
            time.sleep(0.3)
            continue

        result = detect_wake_word_speech(stop_event=stop_event)

        if result and not stop_event.is_set():
            if result == "dance":
                event_queue.put(("DANCE_COMMAND",))
            else:
                event_queue.put(("WAKE_WORD",))
            time.sleep(1)


FACE_CONFIRM_THRESHOLD = 3   # require N consecutive frames with faces before triggering

def face_scan_worker(event_queue, stop_event):
    """
    Background thread: continuously grabs camera frames and checks for faces.
    When an actionable face is confirmed across several consecutive frames,
    places a ("FACE_DETECTED", names) event in the queue.
    Releases the camera when paused and re-opens it when resumed.
    """
    global last_recognized_user
    video_proxy = None
    video_client = None
    consecutive_detections = 0
    last_names = []
    frame_count = 0
    log_interval = 50  # print a status line every N frames

    while True:
        try:
            # If paused, release the camera and wait
            if stop_event.is_set():
                if video_proxy is not None:
                    cleanup_camera(video_proxy, video_client)
                    video_proxy = None
                    video_client = None
                consecutive_detections = 0
                last_names = []
                time.sleep(0.3)
                continue

            # Open camera if needed
            if video_proxy is None:
                video_proxy, video_client = init_camera()
                print("[FaceWorker] Camera subscribed.\n")

            # Grab one frame and check for faces
            face_results = grab_and_recognize_one_frame(video_proxy, video_client)
            frame_count += 1

            if face_results:
                names = [f["name"] for f in face_results]
                print("[FaceWorker] Frame {}: detected {} face(s): {}\n".format(
                    frame_count, len(face_results), names))

                known = [n for n in names if n != "Unknown"]
                if known:
                    with last_recognized_user_lock:
                        last_recognized_user = known[0]

                if should_interact_with_faces(face_results):
                    consecutive_detections += 1
                    last_names = names
                else:
                    # Faces found but no interaction needed (cooldown)
                    consecutive_detections = 0
                    last_names = []
            else:
                # No faces in this frame - reset counter
                consecutive_detections = 0
                last_names = []

            # Periodic heartbeat so we know the worker is alive
            if frame_count % log_interval == 0:
                print("[FaceWorker] Processed {} frames, consecutive detections: {}\n".format(
                    frame_count, consecutive_detections))

            # Trigger only after N consecutive frames confirm a face
            if consecutive_detections >= FACE_CONFIRM_THRESHOLD and not stop_event.is_set():
                print("[FaceWorker] Face confirmed after {} frames, triggering event.\n".format(
                    consecutive_detections))
                event_queue.put(("FACE_DETECTED", last_names))
                consecutive_detections = 0
                last_names = []
                time.sleep(1)

            time.sleep(0.1)  # Small delay between frames to avoid overloading

        except Exception as e:
            print("Face scan worker error: {}\n".format(e))
            # Reset camera on error
            if video_proxy is not None:
                try:
                    cleanup_camera(video_proxy, video_client)
                except Exception:
                    pass
                video_proxy = None
                video_client = None
            consecutive_detections = 0
            last_names = []
            time.sleep(1)


# =============================================================================
#  State handlers
# =============================================================================

GOODBYE_PHRASES = [
    "goodbye", "bye", "see you later", "see you", "i'm leaving",
    "im leaving", "that's all", "thats all", "thanks bye",
    "i have to go", "talk to you later", "catch you later",
    "good night", "goodnight", "bye bye", "bye nao",
]

MAX_SILENCE_RETRIES = 2  # how many times we tolerate no-speech before exiting


def _is_goodbye(text):
    """Return True if the transcribed text contains a goodbye phrase."""
    lower = text.lower().strip()
    for phrase in GOODBYE_PHRASES:
        if phrase in lower:
            return True
    return False


def handle_conversational_state():
    """
    CONVERSATIONAL state
    --------------------
    Loops a record -> transcribe -> respond cycle, keeping full conversation
    history for GPT context.  Exits when the user says goodbye, after
    repeated silence, or on error.
    """
    audio_recorder = ALProxy("ALAudioRecorder", ROBOT_IP, ROBOT_PORT)
    audio_device = ALProxy("ALAudioDevice", ROBOT_IP, ROBOT_PORT)
    audio_tts = ALProxy("ALTextToSpeech", ROBOT_IP, ROBOT_PORT)

    with last_recognized_user_lock:
        current_user = last_recognized_user

    if current_user:
        audio_tts.say("Hi {}! How can I help you?".format(current_user))
    else:
        audio_tts.say("How can I help you?")
    wait_for_speech_to_finish(audio_tts)

    conversation_history = []  # accumulates messages; reset on exit
    silence_retries = 0

    while True:
        # -- Record --
        print("Listening for your question...\n")
        detect_and_record_speech(audio_recorder, audio_device)
        print("Recording complete.\n")

        # -- Transfer --
        print("Transferring audio file...\n")
        transfer_ok = transfer_file()
        print("File transfer complete.\n")

        # -- Transcribe --
        question = transcribe_audio() if transfer_ok else None

        if not question:
            silence_retries += 1
            if silence_retries >= MAX_SILENCE_RETRIES:
                print("[Conversational] No speech {} times, exiting.\n".format(
                    silence_retries))
                audio_tts.say("I haven't heard anything, I'll go back to listening mode.")
                wait_for_speech_to_finish(audio_tts)
                break
            audio_tts.say("I didn't catch that. Could you say it again?")
            wait_for_speech_to_finish(audio_tts)
            continue

        silence_retries = 0
        print("User said: {}\n".format(question))

        # -- Check for goodbye --
        if _is_goodbye(question):
            print("[Conversational] Goodbye detected.\n")
            audio_tts.say("Goodbye! It was nice talking to you!")
            wait_for_speech_to_finish(audio_tts)
            break

        # -- Check for special commands --
        found_command = False
        for command, func in COMMAND_MAP.items():
            if command in question.lower():
                func(audio_tts, question)
                found_command = True
                break

        if found_command:
            audio_tts.say("Anything else I can help with?")
            wait_for_speech_to_finish(audio_tts)
            continue

        # -- General GPT question (with conversation history) --
        result = send_to_flask_api(question, history=conversation_history,
                                   user_name=current_user)
        if result is not None:
            response, conversation_history = result
        else:
            response = None

        if response:
            try:
                print("GPT response: {}\n".format(
                    response.encode("utf-8") if isinstance(response, unicode) else response
                ))
            except Exception:
                print("GPT response received.\n")
            speak_response(audio_tts, response)
            wait_for_speech_to_finish(audio_tts)
        else:
            audio_tts.say("I couldn't get a response. Could you try again?")
            wait_for_speech_to_finish(audio_tts)

    print("[Conversational] Conversation ended. History cleared.\n")


def handle_facial_recognition_state(names):
    """
    FACIAL_RECOGNITION state
    -------------------------
    Greet known users or prompt unknown users to register.
    names: list of name strings from the detected faces.
    """
    handle_recognition_results(names)


def handle_listen_and_dance_state():
    """
    LISTEN_AND_DANCE state
    -----------------------
    Hand off to song_listener which monitors audio, analyses tone,
    and drives the matching dance routine until an exit condition is met.
    """
    from song_listener import listen_and_dance
    listen_and_dance()


# =============================================================================
#  Main state machine loop
# =============================================================================

def main():
    print("=" * 60)
    print("  NAO State Machine")
    print("  States: IDLE | CONVERSATIONAL | FACIAL_RECOGNITION")
    print("          LISTEN_AND_DANCE")
    print("=" * 60)

    # Slight head tilt so the camera faces forward (no posture reset)
    try:
        motion = ALProxy("ALMotion", ROBOT_IP, ROBOT_PORT)
        motion.setAngles("HeadPitch", -0.2, 0.5)
    except Exception as e:
        print("Warning: could not set head angle: {}".format(e))

    # Shared objects
    event_queue = Queue()
    stop_event = threading.Event()  # Set = workers pause, Clear = workers run

    # Start worker threads
    wake_thread = threading.Thread(target=wake_word_worker, args=(event_queue, stop_event))
    face_thread = threading.Thread(target=face_scan_worker, args=(event_queue, stop_event))
    wake_thread.daemon = True
    face_thread.daemon = True
    wake_thread.start()
    face_thread.start()

    current_state = STATE_IDLE
    print("\nState: {}\n".format(current_state))

    # Main loop
    while True:
        try:
            # Wait for an event from either worker
            try:
                event = event_queue.get(timeout=1.0)
            except Empty:
                continue

            # Pause all workers
            stop_event.set()
            time.sleep(0.5)

            # Drain any stale events that queued up
            while not event_queue.empty():
                try:
                    event_queue.get_nowait()
                except Empty:
                    break

            # Handle the event
            if event[0] == "WAKE_WORD":
                current_state = STATE_CONVERSATIONAL
                print("\n>>> State: {} -> {}\n".format(STATE_IDLE, current_state))
                handle_conversational_state()

            elif event[0] == "FACE_DETECTED":
                current_state = STATE_FACIAL_RECOGNITION
                print("\n>>> State: {} -> {}\n".format(STATE_IDLE, current_state))
                handle_facial_recognition_state(event[1])

            elif event[0] == "DANCE_COMMAND":
                current_state = STATE_LISTEN_AND_DANCE
                print("\n>>> State: {} -> {}\n".format(STATE_IDLE, current_state))
                handle_listen_and_dance_state()

            # Return to IDLE
            current_state = STATE_IDLE
            print("\n>>> State: {}\n".format(current_state))

            # Resume workers
            stop_event.clear()

        except KeyboardInterrupt:
            print("\nShutting down NAO State Machine...\n")
            stop_event.set()
            break


if __name__ == "__main__":
    main()
