import sys

if sys.version_info < (3, 6):
    raise SystemExit(
        "facial_recognition_api.py requires Python 3.6+. On Windows run: py -3 facial_recognition_api.py"
    )

from flask import Flask, request, jsonify
import cv2
import numpy as np
import json
import os

# Workaround for Python 3.14 compatibility issue with pkg_resources
# Try to import face_recognition, but if it fails, we'll provide a fallback
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
    print("[STARTUP] face_recognition library loaded successfully.")
except Exception as e:
    print("WARNING: face_recognition not available: {}".format(e))
    print("Facial recognition features will be disabled.")
    print("This is likely due to Python 3.14 compatibility issues.")
    print("Consider using Python 3.13 or earlier for full functionality.")
    FACE_RECOGNITION_AVAILABLE = False
    # Create a dummy face_recognition module
    class DummyFaceRecognition:
        @staticmethod
        def face_locations(*args, **kwargs):
            return []
        @staticmethod
        def face_encodings(*args, **kwargs):
            return []
    face_recognition = DummyFaceRecognition()

app = Flask(__name__)

# Debug: save first few frames to disk so we can inspect what the camera sees
DEBUG_FRAME_DIR = "debug_frames"
DEBUG_FRAME_COUNT = 0
DEBUG_FRAME_LIMIT = 5  # save the first 5 frames

# File to save registered users
USER_DATA_FILE = "registered_users.json"
users = []  # Global list to store user data


def load_known_faces():
    """Load known face encodings and names from a file."""
    global users
    try:
        with open(USER_DATA_FILE, "r") as file:
            data = json.load(file)
            # Convert face encodings back to NumPy arrays
            users = [{"name": user["name"], "encoding": np.array(user["encoding"])} for user in data]
            print("Loaded {} known faces.".format(len(users)))
    except FileNotFoundError:
        print("No registered users found. Starting with an empty file.")
        users = []
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in {}. Starting with an empty list.".format(USER_DATA_FILE))
        users = []
    except Exception as e:
        print("Error loading known faces:", e)
        users = []


def save_known_faces():
    """Save known face encodings and names to a file."""
    try:
        # Convert NumPy arrays to lists for JSON serialization
        data = [{"name": user["name"], "encoding": user["encoding"].tolist()} for user in users]
        with open(USER_DATA_FILE, "w") as file:
            json.dump(data, file)
        print("Known faces saved.")
    except Exception as e:
        print("Error saving known faces:", e)


@app.route("/recognize", methods=["POST"])
def recognize_faces():
    """Recognize faces and return their locations and names."""
    global DEBUG_FRAME_COUNT
    try:
        # Decode the received frame
        file = request.files["frame"]
        raw_bytes = file.read()
        np_frame = np.frombuffer(raw_bytes, np.uint8)
        frame = cv2.imdecode(np_frame, cv2.IMREAD_COLOR)

        if frame is None:
            print("[ERROR] cv2.imdecode returned None! Raw bytes length: {}".format(len(raw_bytes)))
            return jsonify({"faces": []})

        # Save first few frames to disk for visual inspection
        if DEBUG_FRAME_COUNT < DEBUG_FRAME_LIMIT:
            if not os.path.exists(DEBUG_FRAME_DIR):
                os.makedirs(DEBUG_FRAME_DIR)
            path = os.path.join(DEBUG_FRAME_DIR, "frame_{}.jpg".format(DEBUG_FRAME_COUNT))
            cv2.imwrite(path, frame)
            print("[DEBUG] Saved frame {} to {} (shape: {}, dtype: {})".format(
                DEBUG_FRAME_COUNT, path, frame.shape, frame.dtype))
            DEBUG_FRAME_COUNT += 1

        # Force a clean uint8 RGB array that dlib will accept
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame = np.array(rgb_frame, dtype=np.uint8, order='C', copy=True)

        print("[DIAG] rgb_frame: shape={}, dtype={}, contiguous={}, strides={}".format(
            rgb_frame.shape, rgb_frame.dtype, rgb_frame.flags['C_CONTIGUOUS'], rgb_frame.strides))

        # Detect faces -- try upsampled for better detection of smaller/distant faces
        face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=2)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        results = []
        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            name = "Unknown"
            # Compare face encodings
            matches = [
                face_recognition.compare_faces([user["encoding"]], face_encoding, tolerance=0.5)
                for user in users
            ]

            # Find the first match
            for i, match in enumerate(matches):
                if True in match:
                    name = users[i]["name"]
                    break

            # Add face location and name to results
            results.append({"name": name, "location": [top, right, bottom, left]})

        if results:
            print("[DETECT] {} face(s): {}".format(
                len(results), [r["name"] for r in results]))

        return jsonify({"faces": results})

    except Exception as e:
        print("[ERROR] Face recognition error: {}".format(e))
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/register", methods=["POST"])
def register_face():
    """Register a new face with a name."""
    try:
        name = request.form.get("name")
        if not name:
            return jsonify({"error": "Name is required for registration."}), 400

        file = request.files["frame"]
        np_frame = np.frombuffer(file.read(), np.uint8)
        frame = cv2.imdecode(np_frame, cv2.IMREAD_COLOR)

        # Ensure exactly 3 channels
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        # Convert BGR to RGB for face_recognition
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame = np.ascontiguousarray(rgb_frame, dtype=np.uint8)

        # Detect a single face (upsample for better detection)
        face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=2)
        if len(face_locations) != 1:
            return jsonify({"error": "Please ensure the image contains exactly one face."}), 400

        face_encoding = face_recognition.face_encodings(rgb_frame, face_locations)[0]

        # Check for duplicate names
        if any(user["name"] == name for user in users):
            return jsonify({"error": "A user with this name already exists."}), 400

        # Add the new face encoding and name
        users.append({"name": name, "encoding": face_encoding})
        save_known_faces()

        return jsonify({"message": "User '{}' registered successfully.".format(name)})

    except Exception as e:
        print("Error during registration:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/debug", methods=["GET"])
def debug_info():
    """Return debug info about the API state."""
    return jsonify({
        "face_recognition_available": FACE_RECOGNITION_AVAILABLE,
        "known_users": len(users),
        "debug_frames_saved": DEBUG_FRAME_COUNT,
        "debug_frame_dir": os.path.abspath(DEBUG_FRAME_DIR)
    })


if __name__ == "__main__":
    if os.path.exists(DEBUG_FRAME_DIR):
        for f in os.listdir(DEBUG_FRAME_DIR):
            os.remove(os.path.join(DEBUG_FRAME_DIR, f))
    load_known_faces()
    print("[STARTUP] face_recognition_available = {}".format(FACE_RECOGNITION_AVAILABLE))
    print("[STARTUP] Saving first {} frames to ./{}/".format(DEBUG_FRAME_LIMIT, DEBUG_FRAME_DIR))
    app.run(host="0.0.0.0", port=5002)
