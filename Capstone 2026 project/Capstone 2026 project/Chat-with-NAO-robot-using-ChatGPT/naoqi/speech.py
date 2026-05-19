from naoqi import ALProxy
import time

# List of wake words (removed "hello no" and "hey no" as they false-trigger
# from the robot's own speech, e.g. "Hello, I don't recognize you")
WAKE_WORDS = ["hey nao", "hello nao", "hey now", "hello now"]

DANCE_WORDS = ["dance", "lets dance", "dance nao", "dance now"]

ROBOT_IP = "YOUR_ROBOT_IP"  # Your constant robot IP


def detect_wake_word_speech(robot_ip=ROBOT_IP, robot_port=9559,
                            wake_words=None, dance_words=None,
                            stop_event=None):
    """
    Listens for wake words OR dance commands using ALSpeechRecognition.

    Returns:
        "wake"  -- a conversational wake word was detected
        "dance" -- a dance command was detected
        None    -- nothing detected (stop_event fired or error)
    """
    if wake_words is None:
        wake_words = WAKE_WORDS
    if dance_words is None:
        dance_words = DANCE_WORDS

    all_words = list(wake_words) + list(dance_words)
    wake_set  = set(w.lower() for w in wake_words)
    dance_set = set(w.lower() for w in dance_words)

    try:
        speech_rec = ALProxy("ALSpeechRecognition", robot_ip, robot_port)
        memory = ALProxy("ALMemory", robot_ip, robot_port)
        tts = ALProxy("ALTextToSpeech", robot_ip, robot_port)

        speech_rec.pause(True)
        speech_rec.setLanguage("English")
        speech_rec.setVocabulary(all_words, False)
        speech_rec.setParameter("Sensitivity", 0.8)
        speech_rec.pause(False)

        subscription_name = "WakeWordDetection"
        speech_rec.subscribe(subscription_name)

        try:
            memory.insertData("WordRecognized", [])
        except Exception:
            pass

        print("Listening for commands: {}".format(", ".join(all_words)))
        time.sleep(1.0)

        while True:
            if stop_event and stop_event.is_set():
                try:
                    speech_rec.pause(True)
                    speech_rec.unsubscribe(subscription_name)
                except Exception:
                    pass
                return None

            try:
                word_data = memory.getData("WordRecognized")
            except Exception:
                time.sleep(0.3)
                continue

            if word_data and len(word_data) >= 2:
                word = word_data[0]
                confidence = word_data[1]
                if word:
                    word = word.lower().strip()
                    if confidence > 0.5:
                        category = None
                        if word in dance_set:
                            category = "dance"
                        elif word in wake_set:
                            category = "wake"

                        if category:
                            print("Detected '{}' -> {} (conf {:.2f})".format(
                                word, category, confidence))
                            try:
                                memory.insertData("WordRecognized", [])
                            except Exception:
                                pass
                            speech_rec.pause(True)
                            speech_rec.unsubscribe(subscription_name)

                            if category == "wake":
                                tts.say("Yes?")
                            else:
                                tts.say("Ooh, dance time!")
                            return category
            time.sleep(0.1)

    except Exception as e:
        print("Error in wake/dance word detection: {}".format(e))
        return None


if __name__ == "__main__":
    ROBOT_IP = "172.20.10.7"

    result = detect_wake_word_speech(ROBOT_IP)
    if result == "wake":
        print("Wake word detected!")
    elif result == "dance":
        print("Dance command detected!")
    else:
        print("Nothing detected.")
