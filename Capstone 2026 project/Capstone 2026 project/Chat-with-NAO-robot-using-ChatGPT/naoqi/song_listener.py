# -*- coding: utf-8 -*-
"""
Song Listener  --  song-recognition & GPT-choreographed dance
==============================================================
Manages the LISTEN_AND_DANCE state end-to-end:

  1. Waits for music via NAO's front microphone energy.
  2. Records a clip, transfers it via SCP, identifies the song
     through the Song Recognition API (port 5003).
  3. Sends the song name to the GPT Choreograph API (port 5001)
     to get an ordered dance sequence.
  4. Executes each dance from the registry (tone_dance.py),
     checking for stop commands between dances.
  5. After the sequence finishes: re-identify the song.
     Same song -> repeat sequence.  Different song -> new GPT call.
  6. Exits on silence timeout, stop command, error, or max duration.
"""

import os
import time
from naoqi import ALProxy
import paramiko
from scp import SCPClient
import requests

from tone_dance import get_available_dances, execute_dance, stand_pose

# =====================================================================
#  CONFIG
# =====================================================================

ROBOT_IP   = "YOUR_ROBOT_IP"
ROBOT_PORT = 9559
USERNAME   = "YOUR_USERNAME"
PASSWORD   = "YOUR_PASSWORD"

LAPTOP_IP        = os.getenv("LAPTOP_IP", "YOUR_ROBOT_IP")
SONG_API_URL     = "http://{}:5003/identify".format(LAPTOP_IP)
CHOREO_API_URL   = "http://{}:5001/choreograph".format(LAPTOP_IP)
DANCE_EXEC_URL   = "http://{}:5001/dance_executed".format(LAPTOP_IP)

POLL_INTERVAL          = 0.3
SILENCE_TIMEOUT        = 5.0
INITIAL_WAIT_TIMEOUT   = 10.0
MAX_STATE_DURATION     = 300
ENERGY_THRESHOLD       = 600

RECORD_SECONDS         = 10
RECHECK_RECORD_SECONDS = 8

REMOTE_CLIP_FILE = "/home/nao/recordings/audio/song_clip.wav"
LOCAL_CLIP_FILE  = "./song_clip.wav"

STOP_WORDS = ["stop", "stop nao", "stop dancing"]

MAX_IDENTIFY_ATTEMPTS = 2

# =====================================================================
#  Internal helpers
# =====================================================================

def _ensure_remote_dir():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ROBOT_IP, username=USERNAME, password=PASSWORD)
        ssh.exec_command("mkdir -p /home/nao/recordings/audio")
        ssh.close()
    except Exception as e:
        print("[SongListener] Warning: remote dir: {}".format(e))


def _record_clip(audio_recorder, seconds):
    """Record a WAV clip on the robot."""
    try:
        audio_recorder.stopMicrophonesRecording()
    except Exception:
        pass
    print("[SongListener] Recording {}s clip...".format(seconds))
    audio_recorder.startMicrophonesRecording(
        REMOTE_CLIP_FILE, "wav", 48000, [0, 0, 1, 0])
    time.sleep(seconds)
    audio_recorder.stopMicrophonesRecording()
    print("[SongListener] Recording done.")


def _transfer_clip():
    """SCP the clip from the robot to the laptop."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ROBOT_IP, username=USERNAME, password=PASSWORD)
        with SCPClient(ssh.get_transport()) as scp:
            scp.get(REMOTE_CLIP_FILE, LOCAL_CLIP_FILE)
        ssh.close()
        return True
    except Exception as e:
        print("[SongListener] SCP error: {}".format(e))
        return False


def _identify_song():
    """POST the local clip to the Song Recognition API.
    Returns (song_title, artist) or (None, None)."""
    if not os.path.exists(LOCAL_CLIP_FILE):
        return None, None
    try:
        with open(LOCAL_CLIP_FILE, "rb") as f:
            resp = requests.post(SONG_API_URL, files={"audio": f}, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("song"), data.get("artist")
        print("[SongListener] Song API HTTP {}: {}".format(
            resp.status_code, resp.text[:200]))
    except Exception as e:
        print("[SongListener] Song API error: {}".format(e))
    return None, None


def _get_choreography(song, artist):
    """Ask GPT for a dance sequence. Returns list of dance name strings or None."""
    dances = get_available_dances()
    payload = {
        "song": song,
        "artist": artist or "Unknown",
        "available_dances": dances,
    }
    try:
        resp = requests.post(CHOREO_API_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            seq = resp.json().get("sequence")
            if seq:
                return seq
        print("[SongListener] Choreograph API HTTP {}: {}".format(
            resp.status_code, resp.text[:200]))
    except Exception as e:
        print("[SongListener] Choreograph API error: {}".format(e))
    return None


def _report_dance_executed(dance_name):
    """Tell the Flask API that a dance was actually performed."""
    try:
        requests.post(DANCE_EXEC_URL, json={"dance": dance_name}, timeout=3)
    except Exception:
        pass


def _check_stop_command(memory):
    """Return True if ALSpeechRecognition detected a stop phrase."""
    try:
        word_data = memory.getData("WordRecognized")
        if word_data and len(word_data) >= 2:
            word = word_data[0].lower().strip()
            confidence = word_data[1]
            if word in STOP_WORDS and confidence > 0.4:
                print("[SongListener] Stop heard: '{}' (conf {:.2f})".format(
                    word, confidence))
                return True
    except Exception:
        pass
    return False


def _cleanup_speech(speech_rec, active):
    if active and speech_rec:
        try:
            speech_rec.pause(True)
            speech_rec.unsubscribe("DanceStopDetection")
        except Exception:
            pass


def _is_silent(audio_device):
    """Quick silence check."""
    return audio_device.getFrontMicEnergy() < ENERGY_THRESHOLD


# =====================================================================
#  Public entry point
# =====================================================================

def listen_and_dance():
    """
    Run the full LISTEN_AND_DANCE behaviour.
    Blocks until an exit condition is met, then returns so the state
    machine can transition back to IDLE.
    """
    print("\n" + "=" * 55)
    print("  STATE: LISTEN_AND_DANCE")
    print("=" * 55)

    # -- proxies -------------------------------------------------------
    tts            = ALProxy("ALTextToSpeech",  ROBOT_IP, ROBOT_PORT)
    motion         = ALProxy("ALMotion",        ROBOT_IP, ROBOT_PORT)
    audio_recorder = ALProxy("ALAudioRecorder", ROBOT_IP, ROBOT_PORT)
    audio_device   = ALProxy("ALAudioDevice",   ROBOT_IP, ROBOT_PORT)
    memory         = ALProxy("ALMemory",        ROBOT_IP, ROBOT_PORT)

    # -- stop-word detection -------------------------------------------
    stop_detect_active = False
    speech_rec = None
    try:
        speech_rec = ALProxy("ALSpeechRecognition", ROBOT_IP, ROBOT_PORT)
        speech_rec.pause(True)
        speech_rec.setLanguage("English")
        speech_rec.setVocabulary(STOP_WORDS, False)
        speech_rec.pause(False)
        speech_rec.subscribe("DanceStopDetection")
        try:
            memory.insertData("WordRecognized", [])
        except Exception:
            pass
        stop_detect_active = True
        print("[SongListener] Stop-word detection enabled")
    except Exception as e:
        print("[SongListener] Stop detection unavailable: {}".format(e))

    _ensure_remote_dir()
    try:
        audio_recorder.stopMicrophonesRecording()
    except Exception:
        pass

    # -- announce ------------------------------------------------------
    tts.say("Let's dance! Play some music!")
    print("[SongListener] Waiting for music (up to {}s)...".format(
        int(INITIAL_WAIT_TIMEOUT)))

    # -- wait for initial music ----------------------------------------
    music_detected = False
    t0 = time.time()
    while time.time() - t0 < INITIAL_WAIT_TIMEOUT:
        if not _is_silent(audio_device):
            music_detected = True
            break
        time.sleep(POLL_INTERVAL)

    if not music_detected:
        print("[SongListener] No music heard. Returning to IDLE.")
        tts.say("I don't hear any music. Maybe next time!")
        _cleanup_speech(speech_rec, stop_detect_active)
        return

    print("[SongListener] Music detected!")

    # -- identify the song ---------------------------------------------
    song, artist = None, None
    for attempt in range(MAX_IDENTIFY_ATTEMPTS):
        _record_clip(audio_recorder, RECORD_SECONDS)
        if not _transfer_clip():
            continue
        song, artist = _identify_song()
        if song:
            break
        if attempt < MAX_IDENTIFY_ATTEMPTS - 1:
            tts.say("I don't recognize this song yet, let me try again.")

    if not song:
        tts.say("I can't figure out what's playing. Maybe next time!")
        print("[SongListener] Could not identify song. Exiting.")
        _cleanup_speech(speech_rec, stop_detect_active)
        return

    announced_songs = set()
    song_key = song.lower()
    announced_songs.add(song_key)
    tts.say("I know this song! It's {} by {}. Let me dance!".format(song, artist or "unknown"))
    print("[SongListener] Song: '{}' by '{}'".format(song, artist))

    # -- get choreography from GPT -------------------------------------
    sequence = _get_choreography(song, artist)
    if not sequence:
        tts.say("I couldn't think of a dance for this song.")
        print("[SongListener] No choreography returned. Exiting.")
        _cleanup_speech(speech_rec, stop_detect_active)
        return

    print("[SongListener] Dance sequence: {}".format(sequence))

    # -- main dance loop -----------------------------------------------
    state_start = time.time()
    stopped = False

    try:
        while True:
            # --- max-duration guard ---
            if time.time() - state_start > MAX_STATE_DURATION:
                print("[SongListener] Max duration reached. Exiting.")
                break

            # --- execute the dance sequence ---
            for dance_name in sequence:
                # Check stop before each dance
                if stop_detect_active and _check_stop_command(memory):
                    stopped = True
                    break

                if execute_dance(motion, dance_name):
                    _report_dance_executed(dance_name)
                time.sleep(0.5)

            if stopped:
                print("[SongListener] Stop command received.")
                stand_pose(motion)
                tts.say("Okay, stopping!")
                break

            # --- sequence finished, check if music still playing ---
            print("[SongListener] Sequence finished. Checking if music continues...")

            silence_start = None
            music_still = False
            check_t0 = time.time()
            while time.time() - check_t0 < SILENCE_TIMEOUT:
                if not _is_silent(audio_device):
                    music_still = True
                    break
                time.sleep(POLL_INTERVAL)

            if not music_still:
                print("[SongListener] Silence detected. Exiting dance state.")
                break

            # --- re-identify song to see if it changed ---
            _record_clip(audio_recorder, RECHECK_RECORD_SECONDS)
            if not _transfer_clip():
                print("[SongListener] SCP failed on re-check, repeating old sequence.")
                continue

            new_song, new_artist = _identify_song()

            if not new_song:
                print("[SongListener] Could not identify song on re-check. "
                      "Repeating previous sequence.")
                continue

            if new_song.lower() == song.lower():
                print("[SongListener] Same song still playing. Repeating sequence.")
            else:
                print("[SongListener] New song detected: '{}' by '{}'".format(
                    new_song, new_artist))
                song, artist = new_song, new_artist
                song_key = song.lower()
                if song_key not in announced_songs:
                    announced_songs.add(song_key)
                    tts.say("New song! {} by {}!".format(song, artist or "unknown"))
                new_seq = _get_choreography(song, artist)
                if new_seq:
                    sequence = new_seq
                    print("[SongListener] New sequence: {}".format(sequence))
                else:
                    print("[SongListener] GPT didn't return a sequence, "
                          "reusing previous.")

    except KeyboardInterrupt:
        print("[SongListener] Interrupted.")
    except Exception as e:
        print("[SongListener] Loop error: {}".format(e))

    # -- teardown ------------------------------------------------------
    try:
        audio_recorder.stopMicrophonesRecording()
    except Exception:
        pass
    if not stopped:
        tts.say("That was fun! Back to listening mode.")
    _cleanup_speech(speech_rec, stop_detect_active)
    print("[SongListener] LISTEN_AND_DANCE exited.\n")
