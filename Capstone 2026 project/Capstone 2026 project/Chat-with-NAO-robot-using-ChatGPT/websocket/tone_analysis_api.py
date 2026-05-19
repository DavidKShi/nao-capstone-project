"""
Song Recognition Flask API
===========================
Accepts short WAV/audio clips and identifies the song using the AudD
audio-fingerprinting service.

Endpoint:  POST /identify   (multipart file upload, field name: "audio")
Returns:   {"song": "Shape of You", "artist": "Ed Sheeran"}
           or {"song": null, "artist": null} when unrecognised.

Health:    GET /health

Requires:  AUDD_API_KEY environment variable (free key from https://audd.io).
Port:      5003  (same port the old tone API used)
"""

from flask import Flask, request, jsonify
import os
import tempfile
import traceback
import base64
import requests as http_requests

app = Flask(__name__)

AUDD_API_KEY = os.getenv("AUDD_API_KEY", "")
AUDD_URL = "https://api.audd.io/"

if not AUDD_API_KEY:
    print("[SongAPI] WARNING: AUDD_API_KEY not set! /identify will fail.")
    print("[SongAPI] Get a free key at https://dashboard.audd.io/")


@app.route("/identify", methods=["POST"])
def identify():
    """Accept a WAV upload and return the song title + artist."""
    try:
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        if not AUDD_API_KEY:
            return jsonify({"error": "AUDD_API_KEY not configured on server"}), 500

        audio_file = request.files["audio"]
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        audio_file.save(tmp_path)

        try:
            with open(tmp_path, "rb") as f:
                audio_bytes = f.read()

            data = {
                "api_token": AUDD_API_KEY,
                "return": "timecode",
            }
            files = {
                "file": ("clip.wav", audio_bytes, "audio/wav"),
            }

            print("[SongAPI] Sending clip to AudD ({} bytes)...".format(
                len(audio_bytes)))
            resp = http_requests.post(AUDD_URL, data=data, files=files, timeout=15)

            if resp.status_code != 200:
                print("[SongAPI] AudD HTTP {}: {}".format(
                    resp.status_code, resp.text[:300]))
                return jsonify({"song": None, "artist": None}), 200

            result = resp.json()
            print("[SongAPI] AudD response status: {}".format(
                result.get("status")))

            if result.get("status") == "success" and result.get("result"):
                song = result["result"].get("title")
                artist = result["result"].get("artist")
                print("[SongAPI] Identified: '{}' by '{}'".format(song, artist))
                return jsonify({"song": song, "artist": artist})
            else:
                print("[SongAPI] Song not recognised.")
                return jsonify({"song": None, "artist": None})

        finally:
            os.unlink(tmp_path)

    except Exception as e:
        print("[SongAPI] Error: {}".format(e))
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "song-recognition",
        "audd_key_set": bool(AUDD_API_KEY),
    })


if __name__ == "__main__":
    print("[SongAPI] Starting Song Recognition API on port 5003")
    print("[SongAPI] AudD key: {}".format(
        "set" if AUDD_API_KEY else "MISSING"))
    app.run(host="0.0.0.0", port=5003)
