import os
import requests
from naoqi import ALProxy
import paramiko
from scp import SCPClient
import speech_recognition as sr
import time

ROBOT_IP = "YOUR_ROBOT_IP"
ROBOT_PORT = 9559
USERNAME = "YOUR_USERNAME"
PASSWORD = "YOUR_PASSWORD"

REMOTE_FILE = "/home/nao/recordings/audio/speech.wav"
LOCAL_FILE = "./speech.wav"

LAPTOP_IP = os.getenv("LAPTOP_IP", "YOUR_IP")
API_URL = "http://{}:5001/chat".format(LAPTOP_IP)

RMS_THRESHOLD = 700
SILENCE_THRESHOLD = 4


def wait_for_speech_to_finish(tts):
    """
    Dynamically wait for the NAO robot to finish speaking using ALTextToSpeech/TextDone event.
    """
    memory = ALProxy("ALMemory", ROBOT_IP, ROBOT_PORT)
    event_name = "ALTextToSpeech/TextDone"

    # Wait until the TextDone event is triggered
    print("Waiting for TextDone event...\n")
    while True:
        try:
            if memory.getData(event_name, 0):  # Check event data
                print("Speech finished.\n")
                break
        except RuntimeError as e:
            print("Error checking TextDone event:".format(e) + "\n")
            break


def remove_old_remote_file():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ROBOT_IP, username=USERNAME, password=PASSWORD)
        # Execute the command to remove the file
        stdin, stdout, stderr = ssh.exec_command("rm -f {}".format(REMOTE_FILE))
        # Wait for the command to complete
        stdout.channel.recv_exit_status()
        ssh.close()
        print("Old remote file removed successfully.")
    except Exception as e:
        print("Error removing remote file: {}".format(e))


def ensure_remote_directory():
    """Make sure the recordings directory exists on the robot."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ROBOT_IP, username=USERNAME, password=PASSWORD)
        remote_dir = os.path.dirname(REMOTE_FILE)
        ssh.exec_command("mkdir -p {}".format(remote_dir))
        ssh.close()
    except Exception as e:
        print("Warning: could not create remote directory: {}".format(e))


def detect_and_record_speech(audio_recorder, audio_device):
    try:
        audio_recorder.stopMicrophonesRecording()

        if os.path.exists(LOCAL_FILE):
            os.remove(LOCAL_FILE)

        ensure_remote_directory()
        remove_old_remote_file()

        print("Listening for speech...\n")
        silent_time = 0
        is_recording = False

        wait_timeout = 10
        waited = 0
        while waited < wait_timeout:
            rms = audio_device.getFrontMicEnergy()
            if rms >= RMS_THRESHOLD:
                break
            time.sleep(0.3)
            waited += 0.3
        else:
            print("No speech detected within {} seconds, giving up.\n".format(wait_timeout))
            return

        print("Speech detected! Starting recording...\n")
        try:
            audio_recorder.startMicrophonesRecording(
                REMOTE_FILE, "wav", 16000, [0, 0, 1, 0]
            )
            is_recording = True
        except RuntimeError as e:
            print("Error starting recording: {}\n".format(e))
            return 

        while is_recording:
            rms = audio_device.getFrontMicEnergy()
            if rms < RMS_THRESHOLD:
                silent_time += 1 # increment silence timer
            else:
                silent_time = 0  

            if silent_time >= SILENCE_THRESHOLD:  # stops after silence threshold
                print("Silence detected, stopping recording...\n")
                audio_recorder.stopMicrophonesRecording()
                time.sleep(0.5)                      
                is_recording = False
                return

            time.sleep(1) # delay for 1 second
    except Exception as e:
        print("Error during recording:{}".format(e) + "\n")


def transfer_file():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ROBOT_IP, username=USERNAME, password=PASSWORD)

        with SCPClient(ssh.get_transport()) as scp:
            scp.get(REMOTE_FILE, LOCAL_FILE)
        print("File transferred successfully to:{}".format(LOCAL_FILE))
        return True
    except Exception as e:
        print("Error during file transfer:{}".format(e) + "\n")
        return False


def transcribe_audio():
    if not os.path.exists(LOCAL_FILE):
        print("No audio file found at {} - skipping transcription.\n".format(LOCAL_FILE))
        return None
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(LOCAL_FILE) as source:
            audio_data = recognizer.record(source)
        print("Transcribing audio...")
        transcription = recognizer.recognize_google(audio_data)
        print("Transcription:", transcription)
        return transcription
    except sr.UnknownValueError:
        print("Could not understand the audio.")
        return None
    except sr.RequestError as e:
        print("Error with the speech recognition service:", e)
        return None



def send_to_flask_api(user_input, history=None, user_name=None):
    """
    Send user_input to the GPT Flask API.
    If history (list of message dicts) is provided, the API will use it
    for conversational context.
    If user_name is provided, the API injects the user's identity into the
    system prompt so GPT knows who it is talking to.
    Returns (reply_text, updated_history) when history is provided,
    or just reply_text for backward compatibility when history is None.
    """
    try:
        payload = {"input": user_input}
        if history is not None:
            payload["history"] = history
        if user_name:
            payload["user_name"] = user_name

        response = requests.post(API_URL, json=payload)
        if response.status_code == 200:
            data = response.json()
            openai_response = data.get("response")
            if openai_response:
                try:
                    print("OpenAI Response:{}\n".format(openai_response.encode("utf-8")))
                except (UnicodeEncodeError, UnicodeDecodeError):
                    print("OpenAI Response: (contains special characters, see robot speech)\n")

            if history is not None:
                return openai_response, data.get("history", history)
            return openai_response
        else:
            print("Error with Flask API: {}, {}".format(response.status_code, response.text))
            if history is not None:
                return None, history
            return None
    except requests.RequestException as e:
        print("Error connecting to Flask API:{}\n".format(e))
        if history is not None:
            return None, history
        return None


def speak_response(audio_tts, response):
    try:
        print("Speaking response...\n")
        if isinstance(response, unicode):
            audio_tts.say(response.encode("utf-8"))
        else:
            audio_tts.say(str(response))
    except Exception as e:
        print("Error during text-to-speech: {}".format(e))
