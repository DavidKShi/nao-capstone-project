# Setup Required for Capstone 2026 Project

## ✅ Already Fixed

1. **Robot IP Address**
2. **SSH Password**
3. **OpenAI API**

## ⚠️ REQUIRED: What You Need to Do

### 1. Set OpenAI API Key (CRITICAL)

The GPT functionality requires an OpenAI API key. You have two options:

**Option A: Environment Variable (Recommended)**
```bash
export OPENAI_API_KEY='your-actual-api-key-here'
```

**Option B: Create a .env file** (if using python-dotenv)
Create a file named `.env` in the `Capstone-2024` directory:
```
OPENAI_API_KEY=your-actual-api-key-here
```

**To get your API key:**
1. Go to https://platform.openai.com/api-keys
2. Sign in or create an account
3. Click "Create new secret key"
4. Copy the key (you won't be able to see it again!)

**Test it:**
```bash
cd websocket
export OPENAI_API_KEY='your-key'
python3 "flask api.py"
```

You should see the server start without the "WARNING: OPENAI_API_KEY not set" message.

### 2. Install Python Dependencies

**For Python 3 (Flask APIs):**
```bash
pip3 install flask openai face-recognition opencv-python numpy requests
```

**For Python 2.7 (NAOqi scripts):**
```bash
pip2.7 install opencv-python numpy requests paramiko scp pydub
```

**Note:** You also need the NAOqi Python SDK installed. Check if you have it:
```bash
python2.7 -c "import naoqi; print('NAOqi installed')"
```

### 3. Verify Robot Connection

Before running, make sure:
- Robot is powered on
- Robot IP is `YOUR_ROBOT_IP` (already configured)
- Your laptop and robot are on the same network
- SSH is enabled on the robot (username: `YOUR_USERNAME`, password: `YOUR_PASSWORD`)

Test SSH connection:
```bash
ssh nao@YOUR_ROBOT_IP
# Password: YOUR_PASSWORD
```

### 4. Optional: Audio Files for Dances

If you want the dances to have music, upload these files to the robot:
- `/home/nao/audio/dance1.mp3`
- `/home/nao/audio/macarena.mp3`
- `/home/nao/audio/gangnamstyle.wav`

You can skip this if you just want to test without music.

### 5. Optional: Spotify Integration

The Spotify integration in `facial_recognition_api.py` requires:
- Spotify Client ID
- Spotify Client Secret
- Redirect URI

This is optional - the main functionality works without it.

## 🚀 How to Run

1. **Start Facial Recognition API** (Terminal 1):
   ```bash
   cd Capstone-2026/websocket
   python3 facial_recognition_api.py
   ```
   Should see: "Running on http://0.0.0.0:5000"

2. **Start GPT API** (Terminal 2):
   ```bash
   cd Capstone-2026/websocket
   export OPENAI_API_KEY='your-key-here'  # Set this first!
   python3 "flask api.py"
   ```
   Should see: "Running on http://0.0.0.0:5001"

3. **Run Main Robot Program** (Terminal 3):
   ```bash
   cd Capstone-2026/naoqi
   python2.7 nao_main.py
   ```

## 🔍 Troubleshooting

**"OpenAI API key not configured" error:**
- Make sure you set `OPENAI_API_KEY` environment variable before starting the Flask API
- Check that the key is correct (no extra spaces)

**"Cannot connect to robot" error:**
- Verify robot IP is `YOUR_ROBOT_IP`
- Check robot is powered on and on the network
- Test SSH connection: `ssh nao@YOUR_ROBOT_IP`

**"Module not found" errors:**
- Install missing Python packages (see section 2 above)
- Make sure you're using the correct Python version (Python 3 for Flask, Python 2.7 for NAOqi)

**"Connection refused" when calling Flask APIs:**
- Make sure both Flask APIs are running
- Check they're on ports 5000 and 5001
- Verify your laptop firewall isn't blocking them

