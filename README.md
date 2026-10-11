# Kimiko NEA

Kimiko is a local AI desktop companion developed as a Computer Science NEA project. It combines a graphical character interface, a local language model, persistent conversation memory, reminders, and Minecraft integration.

## System Overview

```text
Desktop User
      ↓
Kimiko Desktop UI
[KimikoDesktop.py]
      ↓
Kimiko Core
[Kimiko_Core.py]
   ↙      ↓       ↘
Memory  Modes   Minecraft Events
   ↓      ↓          ↓
      Local Model Runtime
             ↓
        llmster / lms
             ↓
       localhost:1234
```

## Main Features

### Desktop Companion

The main interface is provided by `KimikoDesktop.py`.

It provides:

- Character-based desktop UI
- User text input
- AI responses
- Conversation display
- Mode switching
- Reminder notifications
- Interaction with the Minecraft companion
- Runtime context updates

The desktop interface communicates with the conversation core rather than directly managing the AI model.

## Conversation Core

`Kimiko_Core.py` contains the main logic behind Kimiko.

It handles:

- Conversation generation
- AI modes
- Conversation history
- Persistent memory
- Memory similarity and promotion
- Reminders and timers
- Minecraft event context
- Commands
- Local model management
- Communication with the local AI API

### Modes

Kimiko supports different conversation modes, including:

- **Companion** — normal conversation
- **Work** — more task-focused responses
- **Minecraft** — responses based on Minecraft events
- **Therapy** — dedicated conversational mode
- **Judgement** — additional character mode

## Conversation Memory

Kimiko has a persistent memory system stored locally.

```text
connectai_memory.json
```

The memory system can:

- Store conversation information
- Compare new information with existing memories
- Identify related memories
- Promote frequently relevant short-term memories
- Remove expired short-term memories
- Recall relevant information during conversations

## Reminders

Kimiko includes a reminder system built into `Kimiko_Core.py`.

Reminders can:

- Be scheduled from commands
- Run using background timers
- Trigger callbacks in the desktop application
- Remain pending if the UI is temporarily unavailable
- Display notifications through the character interface

The core handles the timer while `KimikoDesktop.py` handles displaying the reminder to the user.

# Minecraft Integration

Kimiko can receive information from Minecraft through a separate event server.

The integration uses **Zergatul/CheatUtils** and a CheatUtils Event Script.

```text
Minecraft
    ↓
CheatUtils Event Script
    ↓
POST /logs
    ↓
Minecraft Event Server
    ↓
Recent Event Buffer
    ↓
Kimiko Core
```

The Python Minecraft backend runs on:

```text
http://127.0.0.1:5001
```

Events are sent to:

```text
POST /logs
```

The CheatUtils backend runs on:

```text
http://localhost:5005/
```

### Minecraft Events

The integration can provide Kimiko with information such as:

- Chat messages
- Player health
- Food level
- Biome
- Dimension
- Time of day
- Players online
- Weather
- Minecraft version
- Other game events

These events can be stored in the recent-event buffer and supplied to the conversation core as context.

# Local AI Runtime

Kimiko is designed to use **LM Studio's headless runtime (`llmster`)** rather than requiring the LM Studio graphical application.

The core:

1. Finds the `lms` executable.
2. Starts the llmster daemon.
3. Starts the local API server.
4. Checks that the API is available.
5. Checks available system resources.
6. Selects an appropriate model.
7. Downloads the model if required.
8. Loads the model.
9. Sends conversations to the local API.

The API is accessed through:

```text
http://localhost:1234/v1/chat/completions
```

This provides an OpenAI-compatible local API for Kimiko.

## Model Selection

Kimiko checks the available hardware before selecting a model.

The primary model is:

```text
MythoMax-L2-Kimiko-v2-13B
```

A smaller fallback model is available when the system does not have enough resources:

```text
phi-3.1-mini-4k-instruct
```

Kimiko can also dynamically adjust:

- Maximum response tokens
- Conversation history length
- Context length

This allows the program to reduce its resource requirements on systems with less available memory.

# Project Structure

The main components are:

```text
Kimiko/
│
├── KimikoDesktop.py
│   └── Desktop character interface
│
├── Kimiko_Core.py
│   └── Conversation, memory, modes,
│       reminders and AI runtime
│
├── Minecraft_Connect.py
│   └── Minecraft event HTTP server
│
├── connectai_memory.json
│   └── Persistent memory storage
│
└── Installer
    └── Installs llmster and Kimiko
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| `KimikoDesktop.py` | Graphical interface and user interaction |
| `Kimiko_Core.py` | AI, memory, modes, commands and reminders |
| `Minecraft_Connect.py` | Minecraft event server and event handling |
| `connectai_memory.json` | Persistent memory storage |
| `llmster / lms` | Local model runtime |
| LM Studio API | Local OpenAI-compatible API |
| CheatUtils | Minecraft event generation |

# Installation

Kimiko includes a Windows installer.

The installer:

1. Checks whether `lms` is installed.
2. Installs llmster if necessary.
3. Downloads the latest Kimiko release.
4. Installs Kimiko locally.
5. Creates a Start Menu shortcut.

Kimiko itself then manages the local model runtime when it starts.

The installer does **not** require the LM Studio graphical interface.

# Dependencies

The main Python components use:

- Python
- `psutil`
- `torch` *(optional, for GPU/VRAM detection)*
- Tkinter
- Zergatul/CheatUtils for Minecraft integration
- LM Studio / llmster
- A compatible local AI model

Most communication between components uses local HTTP requests.

# Design Goals

Kimiko was designed around several main goals:

### Local processing

The AI model runs locally rather than relying on a remote AI API.

### Modular design

The user interface, conversation logic, Minecraft integration and model runtime are separated into different components.

### Persistent memory

Kimiko can retain relevant information between sessions.

### Context awareness

Minecraft events and desktop interactions can be provided to the AI as additional context.

### Resource awareness

The program checks available hardware resources and can select a smaller model when necessary.

### Expandability

The modular structure allows additional modes, commands, event types and integrations to be added without rebuilding the entire system.

# Architecture

The overall system is divided into four major areas:

**Desktop Companion**

Handles interaction between the user and Kimiko.

**Conversation Core**

Controls conversations, memory, modes, commands and reminders.

**Minecraft Integration**

Receives events from Minecraft and makes them available to the conversation core.

**Local Model Runtime**

Manages llmster and communicates with the local language model through the API.

This separation keeps the graphical interface independent from the AI and Minecraft systems, making the project easier to maintain and expand.
