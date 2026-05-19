# NAO Interactive Social Robot — Capstone Project

An autonomous, multi-modal humanoid robot system built on the NAO platform that can recognize users, hold natural conversations, and perform dynamic dance routines based on environmental inputs.

The system integrates computer vision, speech processing, and large language model intelligence to create a fully interactive human-robot experience.

---

# Project Overview

This project implements an intelligent state-driven control system for a NAO humanoid robot with three core behavioral modes:

## Idle State
- Continuously monitors its environment
- Detects faces and recognizes registered users
- Provides personalized greetings

## Conversation State
- Engages in natural language dialogue using AI-powered responses
- Context-aware conversational flow

## Dance State
- Automatically triggers choreographed dance routines when music is detected
- Executes predefined motion sequences

The robot dynamically transitions between states based on voice commands.

---

# Key Features

## Face Detection & Recognition
- Real-time face detection using computer vision
- User registration and identity recognition
- Personalized greetings for known users

## AI-Powered Conversation
- Natural language interaction using the OpenAI API
- Context-aware responses for fluid conversations
- Voice-based interaction pipeline

## Autonomous Dance System
- Music detection triggers behavioral transitions
- Predefined dance routines executed by NAO
- Smooth transitions between idle and entertainment modes

## State Machine Architecture
- Finite State Machine (FSM) design for behavior control
- Three core states: Idle, Conversation, Dance
- Event-driven transitions based on sensor inputs

## Multimodal Interaction
- Combines speech recognition, computer vision, and audio analysis
- Real-time decision-making for natural human-robot interaction

---

# System Architecture

```
                          +--------------------+
                          |    Idle State      |
                          | Face Recognition   |
                          | Listening Mode     |
                          +---------+----------+
                                    |
                +-------------------+-------------------+
                |                                       |
    Voice Command ("Hey NAO")               Voice Command ("Dance NAO")
                |                                       |
                v                                       v
      +--------------------+                 +---------------------+
      | Conversation State |                 |   Dance State       |
      | AI Chat (OpenAI)   |                 | Choreographed Moves |
      +--------------------+                 +---------------------+
                |                                       |
                |                                       |
    Voice Command ("Goodbye")               Voice Command ("Stop NAO")
                |                                       |
                +-------------------+-------------------+
                                    |
                                    v
                             Return to Idle
```

---

# Tech Stack

- Python
- NAO Robot SDK (NAOqi Framework)
- OpenCV (Computer Vision)
- Speech Recognition (Google Speech / offline engine)
- Audio Processing (music detection)
- OpenAI API
- Finite State Machine (FSM) design pattern

---

# How It Works

1. Robot starts in Idle State
2. Continuously scans for faces:
   - Recognized users → personalized greeting
   - Unknown users → registration prompt
3. Listens for voice commands:
   - “Hey NAO” → Conversation State
   - “Dance NAO” → Dance State
4. Conversation state generates AI responses using ChatGPT
5. Dance state executes predefined motion sequences
6. System returns to idle state after hearing "Goodbye" in conversation state or "Stop NAO" in dance state

---

# State Machine Design

The system is built using a Finite State Machine (FSM):

## States
- Idle State → Default monitoring mode
- Conversation State → AI chat interaction
- Dance State → Motion playback mode

## Transitions triggered by:
- Voice commands
- Face recognition events
- Audio/music detection

---

# Team & Collaboration

Developed as a group capstone project with responsibilities shared across:
- Computer vision integration
- Robot behavior programming
- ChatGPT integrated conversation system design
- Audio processing & state control

---

# Demo

https://youtu.be/x-_MvlWAx-c

---

# License

This project is intended for academic and portfolio use.

# Authors

Developed by David Shi, Ousama Alabdullah, Humaira Saddat
