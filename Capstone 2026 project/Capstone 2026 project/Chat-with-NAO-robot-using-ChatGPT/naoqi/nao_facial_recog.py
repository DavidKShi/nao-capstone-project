import os
import cv2
import numpy as np
from naoqi import ALProxy
import requests
from nao_transcribe import detect_and_record_speech, transcribe_audio, transfer_file, wait_for_speech_to_finish
import time
import threading

# Greet cooldown
GREETED_USERS = {}  # dict mapping name -> last_greeted_timestamp
GREETED_USERS_LOCK = threading.Lock()
GREET_COOLDOWN = 60  # seconds before greeting the same person again

# Set to True to show the camera feed GUI window on the laptop.
# Disabled by default because the NAOqi SDK Qt libraries conflict with
# OpenCV's Qt/cocoa display on macOS, causing an abort.
SHOW_CAMERA_GUI = os.getenv("SHOW_CAMERA_GUI", "0") == "1"

# NAO Configuration
ROBOT_IP = "YOUR_ROBOT_IP"  # Replace with your NAO robot's IP
ROBOT_PORT = 9559
RESOLUTION = 2  # 640x480 resolution
FRAME_RATE = 60

# Laptop (Flask API host) IP that the robot should call.
# IMPORTANT: This must be on the same network as the robot 
LAPTOP_IP = os.getenv("LAPTOP_IP", "YOUR_ROBOT_IP")
PYTHON3_API_URL = "http://{}:5002".format(LAPTOP_IP)  # Python 3 Flask API URL


# Camera helpers (used by the state machine)

def init_camera(subscription_name="face_scan_cam"):
    """
    Subscribe to NAO's camera.
    Returns (video_proxy, video_client).
    """
    video_proxy = ALProxy("ALVideoDevice", ROBOT_IP, ROBOT_PORT)
    video_client = video_proxy.subscribeCamera(
        subscription_name, 0, RESOLUTION, 11, FRAME_RATE
    )
    return video_proxy, video_client


def cleanup_camera(video_proxy, video_client):
    """Unsubscribe from NAO's camera."""
    try:
        video_proxy.unsubscribe(video_client)
    except Exception as e:
        print("Warning: could not unsubscribe camera: {}".format(e))


def grab_and_recognize_one_frame(video_proxy, video_client):
    """
    Grab a single frame from the camera, send it to the Flask facial
    recognition API.

    Returns a list of face dicts:
        [{"name": "...", "location": [top, right, bottom, left]}, ...]
    Returns an empty list if no faces are found or an error occurs.
    """
    try:
        frame_data = video_proxy.getImageRemote(video_client)
        if frame_data is None:
            return []

        width = frame_data[0]
        height = frame_data[1]
        array = frame_data[6]
        # NAO camera color space 11 = RGB; OpenCV expects BGR for imencode
        frame_rgb = np.frombuffer(array, dtype=np.uint8).reshape((height, width, 3))
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        _, encoded_frame = cv2.imencode(".jpg", frame_bgr)
        response = requests.post(
            "{}/recognize".format(PYTHON3_API_URL),
            files={"frame": encoded_frame.tobytes()},
            timeout=5
        )

        if response.status_code == 200:
            return response.json().get("faces", [])
        else:
            print("Error from recognition API: {}".format(response.text))
            return []

    except Exception as e:
        print("Error grabbing/recognizing frame: {}".format(e))
        return []


# Decision helper

def should_interact_with_faces(face_results):
    """
    Check whether any detected faces require interaction:
      - Unknown faces always require interaction (registration prompt).
      - Known faces only require interaction if the greet cooldown has passed.
    Returns True if at least one face needs interaction.
    """
    now = time.time()
    for face in face_results:
        name = face.get("name", "")
        if name == "Unknown":
            return True
        with GREETED_USERS_LOCK:
            last_greeted = GREETED_USERS.get(name, 0)
            if now - last_greeted >= GREET_COOLDOWN:
                return True
    return False


# Interaction handlers (called by state machine)

def handle_recognition_results(names):
    """
    Process recognition results and interact with the user.
    Called by the state machine when entering FACIAL_RECOGNITION state.

    names: list of name strings (e.g. ["Osama", "Unknown"]).
    """
    tts = ALProxy("ALTextToSpeech", ROBOT_IP, ROBOT_PORT)

    if "Unknown" in names:
        tts.say("Hello! I don't recognize you. Would you like to register?")

        print("Called detect_and_record...\n")
        # Get user response
        detect_and_record_speech(
            audio_recorder=ALProxy("ALAudioRecorder", ROBOT_IP, ROBOT_PORT),
            audio_device=ALProxy("ALAudioDevice", ROBOT_IP, ROBOT_PORT)
        )
        print("Listening for user response...\n")
        print("Transferring recorded audio file...\n")
        transfer_file()
        user_res = transcribe_audio()
        print("User response: {}\n".format(user_res))

        # Process user response
        if user_res and user_res.lower() in [
            "yes", "yeah", "yup", "sure", "ok", "okay", "please",
            "yeah sure", "yes please", "yes sure", "yes okay", "yeah okay"
        ]:
            tts.say("Great! What is your name.")
            detect_and_record_speech(
                audio_recorder=ALProxy("ALAudioRecorder", ROBOT_IP, ROBOT_PORT),
                audio_device=ALProxy("ALAudioDevice", ROBOT_IP, ROBOT_PORT)
            )
            print("Listening for user's name...\n")
            print("Transferring recorded audio file for name...\n")
            transfer_file()
            user_name = transcribe_audio()
            print("Capturing name: {}\n".format(user_name))
            if user_name:
                tts.say("Thank you, {}. Please look at the camera for registration.".format(user_name))
                wait_for_speech_to_finish(tts)
                register_user(name=user_name)
            else:
                tts.say("I didn't get your name. Please try later.")
        else:
            tts.say("Alright, maybe next time")

    else:
        # Greet known users (respecting the cooldown)
        with GREETED_USERS_LOCK:
            now = time.time()
            for name in names:
                last_greeted = GREETED_USERS.get(name, 0)
                if now - last_greeted >= GREET_COOLDOWN:
                    tts.say("Hello, {}! Welcome back.".format(name))
                    wait_for_speech_to_finish(tts)
                    GREETED_USERS[name] = now


def register_user(name="New user"):
    """
    Capture a frame and send it to the Flask API to register a new user.
    Opens its own camera subscription so it does not conflict with the
    face-scan worker.
    """
    video_proxy = ALProxy("ALVideoDevice", ROBOT_IP, ROBOT_PORT)
    video_client = video_proxy.subscribeCamera(
        "registration_cam", 0, RESOLUTION, 11, FRAME_RATE
    )

    try:
        # Capture a frame
        frame_data = video_proxy.getImageRemote(video_client)
        if frame_data is None:
            print("Error capturing frame for registration\n")
            return

        # Extract image properties
        width = frame_data[0]
        height = frame_data[1]
        array = frame_data[6]
        # NAO camera color space 11 = RGB; OpenCV expects BGR for imencode
        frame_rgb = np.frombuffer(array, dtype=np.uint8).reshape((height, width, 3))
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        # Convert to JPEG for transmission
        _, encoded_frame = cv2.imencode(".jpg", frame_bgr)

        # Send frame and name to the Flask API
        response = requests.post(
            "{}/register".format(PYTHON3_API_URL),
            files={"frame": encoded_frame.tobytes()},
            data={"name": name},
        )

        if response.status_code == 200:
            print("User registered successfully: {}\n".format(response.json()["message"]))
            tts = ALProxy("ALTextToSpeech", ROBOT_IP, ROBOT_PORT)
            tts.say("Registration successful. Welcome, {}.".format(name))
            wait_for_speech_to_finish(tts)
        else:
            print("Error in registration response: {}\n".format(response.text))
    except Exception as e:
        print("Error during user registration: {}\n".format(e))
    finally:
        video_proxy.unsubscribe(video_client)
