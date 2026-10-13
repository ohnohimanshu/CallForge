# CallForge — Real-Time AI Calling Agents & Telephony Platform

**CallForge** is a production-grade, local, full-duplex real-time AI voice calling platform and multi-agent telephony runtime. Powered by Asterisk PBX for carrier-grade SIP/PJSIP trunking, CallForge delivers an ultra-low-latency conversational audio pipeline (**Silero VAD → faster-whisper STT → Speculative RAG & Dynamic Tools → Local Ollama LLM → Streaming Piper TTS**) coupled with a modern React web control plane.

> 📢 **Pitching or Evaluating CallForge?** See [PROJECT_OVERVIEW_AND_PITCH.md](file:///home/himanshu/Downloads/calling_agent/PROJECT_OVERVIEW_AND_PITCH.md) for the complete pitch deck, unit economics ($4.99/mo DID margin), investor presentation scripts, and technical deep dive!

---

## Table of Contents

- [Key Capabilities & Features](#key-capabilities--features)
  - [1. Real-Time Conversational Voice Pipeline](#1-real-time-conversational-voice-pipeline)
  - [2. Cross-Call Memory & Caller Recognition](#2-cross-call-memory--caller-recognition)
  - [3. Agent Studio & Multi-Agent Runtime](#3-agent-studio--multi-agent-runtime)
  - [4. Direct DID Phone Number Purchasing & Provisioning](#4-direct-did-phone-number-purchasing--provisioning)
  - [5. Live Appointment Booking & Google Sheets Webhooks](#5-live-appointment-booking--google-sheets-webhooks)
  - [6. Outbound Campaign Engine & Auto-Dialer](#6-outbound-campaign-engine--auto-dialer)
  - [7. Speculative Multi-Branch Response Generation](#7-speculative-multi-branch-response-generation)
  - [8. On-The-Fly Voice Cloning for Personas](#8-on-the-fly-voice-cloning-for-personas)
  - [9. Interactive Web Voice Simulator](#9-interactive-web-voice-simulator)
  - [10. Document RAG (Retrieval-Augmented Generation)](#10-document-rag-retrieval-augmented-generation)
  - [11. Prosody Tracking, Emotion Intelligence & Backchanneling](#11-prosody-tracking-emotion-intelligence--backchanneling)
  - [12. Multilingual Voice Routing (English & Hindi)](#12-multilingual-voice-routing-english--hindi)
  - [13. Smart Human Handoff & Dialogue Policies](#13-smart-human-handoff--dialogue-policies)
  - [14. Live Wallboard, Analytics & Call Recordings](#14-live-wallboard-analytics--call-recordings)
  - [15. Multi-Tenant User Authentication & Web Portal](#15-multi-tenant-user-authentication--web-portal)
- [Architecture](#architecture)
  - [Audio & Telephony Pipeline](#audio--telephony-pipeline)
  - [Cross-Call Memory Flow](#cross-call-memory-flow)
- [Quick Start](#quick-start)
  - [1. Prerequisites](#1-prerequisites)
  - [2. Installation](#2-installation)
  - [3. Ollama Setup (Multi-Caller Concurrency)](#3-ollama-setup-multi-caller-concurrency)
  - [4. Running CallForge](#4-running-callforge)
  - [5. Testing the Agent](#5-testing-the-agent)
  - [6. Asterisk Telephony Setup](#6-asterisk-telephony-setup)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Configuration Reference](#configuration-reference)
- [License](#license)

---

## Key Capabilities & Features

### 1. Real-Time Conversational Voice Pipeline
- **Full-Duplex Telephony**: Communicates with Asterisk over TCP using the AudioSocket protocol (8kHz 16-bit mono linear PCM frames at 20ms intervals).
- **Sub-Second Latency**: Optimized pipeline yields sub-second conversational turn-around times on standard CPU/GPU consumer hardware without cloud API dependencies.
- **Robust Barge-In & Interruption Handling**: Instantly stops agent speech and clears outbound audio buffers the moment caller speech is detected above configurable VAD probability (`VAD_BARGE_IN_SPEECH_THRESHOLD`) and RMS amplitude (`VAD_BARGE_IN_MIN_RMS`) thresholds.

### 2. Cross-Call Memory & Caller Recognition
- **Stateful Caller Profiles**: Automatically identifies callers via `${CALLERID(num)}` (or simulator ID), indexing names, lifetime call count, timestamps, sentiment trajectory, and structured outcome dispositions.
- **Context Injection Before Greeting**: Injects past conversational context (*"Caller called 2 days ago about dental cleaning, preferred morning slots, expressed frustration regarding pricing"*) into the LLM system context before the initial greeting plays.
- **Personalized Recognition Openings**: Personas greet returning callers naturally (*"Welcome back, Sarah! Are you calling to check on the estimate we discussed yesterday?"* / *"नमस्ते राहुल जी! फिर से संपर्क करने के लिए धन्यवाद..."*).
- **Rapport & De-escalation Memory**: Persists emotional trajectory across interactions; if a caller experienced frustration in earlier calls, the persona automatically adopts an empathetic, reassuring tone.

### 3. Agent Studio & Multi-Agent Runtime
- **Visual Persona Designer**: Build, configure, and customize agent personas with prompt templates, greeting text, speaking speed (`length_scale`), pitch shift factor, and voice models.
- **Multi-Agent Isolation**: Run multiple agents simultaneously on independent AudioSocket ports (`9092`, `9093`, ...) mapped to distinct Asterisk dialplan extensions (`2000`, `2001`, ...).
- **Hot Deployment & Live Reload**: Deploy, stop, or reconfigure agent lines on the fly from the web console without restarting Asterisk or dropping other active calls.
- **A/B Testing Engine**: Deploy prompt, model, or voice variants side-by-side with configurable traffic-split percentages to evaluate conversation performance.

### 4. Direct DID Phone Number Purchasing & Provisioning ($4.99/mo)
- **Carrier Inventory Search**: Search live phone numbers across multiple countries (US, GB, IN, CA, etc.) and specific area codes via Telnyx or Twilio.
- **Built-In Sandbox Mode**: Automatically falls back to a realistic simulated demo pool when live carrier keys are not configured, enabling risk-free local testing without credit cards.
- **Automated Dialplan Binding**: The instant a number is purchased, CallForge dynamically generates Asterisk dialplan routing rules in `extensions_agents.conf` and hot-reloads Asterisk (`asterisk -rx "dialplan reload"`).
- **Sub-500ms Inbound Answering**: Inbound calls hitting the assigned number from any phone network are automatically bridged via AudioSocket directly to the agent's dedicated Python runtime port.
- **Profitable Unit Economics**: Built-in retail subscription pricing ($4.99/mo) provides an 80% gross profit margin over wholesale carrier costs (~$1.00/mo).

### 5. Live Appointment Booking & Google Sheets Webhooks
- **Real-Time Calendar Availability**: Connects directly to Google Apps Script or custom webhooks to query live appointment dates and open time slots mid-call.
- **Spoken Entity Normalization**: Parses conversational time expressions (e.g., `"ten in the morning"`, `"2 30 PM"` → `10:00 AM`, `02:30 PM`) and validates against open slots.
- **Spoken Phone Number Extraction**: Robust parser converts spoken digit streams, digit groups (*"double five"*, *"triple zero"*), and Hindi number words (*"शून्य"*, *"पांच"*) into standardized E.164 phone formats.
- **Partial-Digit Recovery**: Detects incomplete phone numbers caused by caller pauses or VAD cut-offs, prompts the caller for remaining digits, and stitches them seamlessly across turns.
- **Direct Sheet Confirmation**: Automatically writes confirmed reservations with client name, phone number, timestamp, and notes back to the spreadsheet.

### 6. Outbound Campaign Engine & Auto-Dialer
- **Automated Dialing Campaigns**: Launch automated outbound campaigns linked to any deployed agent persona.
- **Lead List Management**: Import lead contact lists via CSV or JSON with custom metadata and variable substitution.
- **Pacing, Concurrency & Retry Controls**: Configure dial concurrency, call timeouts, retry intervals, and maximum retry attempts for busy or unanswered leads.
- **Campaign Wallboard**: Live progress tracking of pending, dialing, completed, and failed leads with real-time conversion rates.

### 7. Speculative Multi-Branch Response Generation
- **Predictive Branching During Speech**: Analyzes partial speech recognition tokens while the caller is still speaking to predict 2–3 high-probability utterance completions using semantic, intent, and domain heuristics.
- **Parallel Background LLM Streams**: Fires asynchronous LLM generation streams for candidate branches before caller turn completion.
- **Zero-Latency Turn Commitment**: When VAD detects turn closure, fuzzy matches the final transcript against candidate branches. If matched, the pre-generated response commits immediately, achieving **near-0ms perceived TTFT (Time-To-First-Token)**.
- **Automatic Fallback**: Unmatched candidate streams are cancelled to conserve resources, falling back seamlessly to standard streaming generation.

### 8. On-The-Fly Voice Cloning for Personas
- **One-Click Audio Cloning**: Upload a 5–15 second reference audio sample (WAV, MP3, OGG, FLAC) to clone custom vocal timbre, pitch, and resonance.
- **Acoustic Profiling Engine**: Extracts fundamental frequency ($F_0$ via normalized autocorrelation), formant scale factors, and spectral centroids.
- **Dual Synthesis Architecture**: Integrates with local XTTS-v2 when available, alongside a built-in zero-dependency high-fidelity acoustic timbre transfer engine that runs out of the box.
- **In-Browser Audio Preview**: Audition uploaded reference samples and preview synthesized test phrases directly in the web UI.

### 9. Interactive Web Voice Simulator
- **Browser-Based Microphone Testing**: Test agents directly inside the browser using WebSockets and Web Audio API—no softphone or Asterisk setup needed.
- **Live Latency & Transcript Waterfall**: Inspect live STT transcripts, pipeline latency breakdowns (STT, LLM TTFT, TTS), speculative match status, and tool execution events in real time.
- **Simulated Caller Identity**: Test cross-call memory and personalization by switching caller phone numbers in the simulator.

### 10. Document RAG (Retrieval-Augmented Generation)
- **Multi-Format Document Ingestion**: Upload PDF, DOCX, XLSX, TXT, and Markdown files into per-agent isolated ChromaDB vector stores.
- **Speculative Retrieval**: Initiates vector similarity search during partial STT to make relevant context available before the LLM prompt is finalized.
- **Grounded Responses**: Restricts answers to uploaded documentation with automatic citation and fallback handling.

### 11. Prosody Tracking, Emotion Intelligence & Backchanneling
- **Acoustic Backchanneling**: Emits natural, non-intrusive vocal acknowledgments (*"Mmhmm"*, *"Right"*, *"I see"*, *"हाँ"*, *"जी"*) during caller breathing micro-pauses (300–600ms) without taking the conversational floor.
- **Acoustic Emotion Detection**: Analyzes audio frame RMS energy, energy variance, zero-crossing rate (ZCR), and speaking cadence (WPM) to classify caller state: `agitated`, `calm`, `fast`, or `neutral`.
- **Dynamic Chameleon Voice**: Dynamically scales Piper TTS pacing (`length_scale`), warmth (`noise_scale`), and volume to match caller prosody.
- **Empathetic LLM Steering**: Injects dynamic prompt directives to de-escalate frustrated callers before generating responses.

### 12. Multilingual Voice Routing (English & Hindi)
- **Automatic Language Detection**: Detects caller language per turn with confidence-based fallback.
- **Dynamic Piper Voice Routing**: Seamlessly switches synthesis between English models (`en_US-lessac-medium`, `en_US-kristin-medium`, `en_US-ryan-medium`, `en_US-amy-medium`) and Hindi models (`hi_IN-priyamvada-medium`).

### 13. Smart Human Handoff & Dialogue Policies
- **Intent-Based Handoff**: Detects escalation phrases (*"talk to a human"*, *"connect to an agent"*, *"insaan se baat karayein"*) with boundary checks to prevent false triggers.
- **Asterisk Channel Transfer**: Seamlessly bridges or transfers callers to human agent queues or extensions (e.g. extension `1001`) via Asterisk AMI/ARI.
- **Slot-Filling State Machine**: Tracks structured slots (name, date, time, phone number, issue description) across turns until requirements are satisfied.

### 14. Live Wallboard, Analytics & Call Recordings
- **Mission Control Wallboard**: Live dashboard displaying active calls, channel states, line occupancy, SIP trunk status, and latency distributions.
- **Conversation Intelligence**: Automatic post-call sentiment analysis (`positive`, `neutral`, `frustrated`) and disposition tagging (`Appointment Booked`, `Lead Captured`, `Escalated to Human`, `Information Provided`, `Dropped / Hangup`).
- **Session Audio Recordings**: Automatically archives 8kHz 16-bit mono WAV recordings per session, playable directly from the call history view.

### 15. Multi-Tenant User Authentication & Web Portal
- **User Authentication**: Secure token-based login and signup with session persistence.
- **Award-Level Landing Page**: Modern, responsive landing page featuring an interactive live call demo, ROI savings calculator, animated waveform canvas, and feature highlights.

---

## Architecture

### Audio & Telephony Pipeline

```
SIP Caller (Softphone / Trunk / Mobile)
                 │
                 ▼
        Asterisk PBX (PJSIP)
                 │ (AudioSocket TCP: 8kHz 16-bit PCM frames @ 20ms)
                 ▼
        CallForge Runtime Line (Port 9092+)
┌────────────────────────────────────────────────────────────────────────┐
│                              CallPipeline                              │
│                                                                        │
│   Silero VAD (Pooled) ────► faster-whisper (Warm STT)                  │
│                                      │                                 │
│                                      ▼                                 │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                 Speculative RAG & Tool Engine                  │   │
│   │  • ChromaDB Document RAG   • Google Sheets Appointment Booking │   │
│   │  • Cross-Call Memory       • Prosody & Emotion Tracking        │   │
│   │  • Slot Filling Tracker    • Acoustic Backchanneling           │   │
│   └──────────────────────────────────┬─────────────────────────────┘   │
│                                      │                                 │
│                                      ▼                                 │
│                         Local Ollama LLM (Streaming)                   │
│                                      │                                 │
│                                      ▼                                 │
│                     Piper TTS (Chunked Streaming Audio)                │
└──────────────────────────────────────┬─────────────────────────────────┘
                                       │ (Outbound 20ms audio frames)
                                       ▼
                              Asterisk Channel ──► Caller
```

### Cross-Call Memory Flow

```
Incoming Call
     │
     ▼
Extract Caller ID (e.g. +14155552671)
     │
     ├───────────────────────────────────────────────────────┐
     ▼                                                       ▼
[New Caller]                                          [Returning Caller]
Set default greeting                             Load Profile from SQLite
                                                 Inject prior call summary,
                                                 sentiment & outcomes into LLM
                                                             │
                                                             ▼
                                                 Personalized recognition greeting
                                                 ("Welcome back John...")
     │                                                       │
     └──────────────────────────┬────────────────────────────┘
                                ▼
                      Conversational Turn Loop
                                │
                                ▼
                       Call Termination
                                │
                                ▼
            Analyze Sentiment, Dispositions & Summary
                                │
                                ▼
            Persist Updated Profile in Caller Store
```

---

## Quick Start

### 1. Prerequisites

- **Operating System**: Linux (x86_64, Ubuntu 20.04+ recommended)
- **Python**: Python 3.10 or higher
- **Node.js**: Node.js 18+ and npm
- **Asterisk PBX**: Local installation or Docker container (`asterisk-server/docker-compose.yml`)
- **Ollama**: Local Ollama instance running:
  - LLM model: `llama3.2:3b-instruct-q4_K_M` (or `qwen2.5:3b-instruct-q4_0`)
  - Embeddings model: `nomic-embed-text`
- **Piper Voice Models**: Stored in `models/piper/` (e.g. `en_US-lessac-medium.onnx`, `hi_IN-priyamvada-medium.onnx`)

---

### 2. Installation

```bash
# 1. Clone the repository and create a Python virtual environment
git clone https://github.com/yourusername/calling_agent.git
cd calling_agent
python3 -m venv .venv
source .venv/bin/activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Build the React Web Control Plane
cd web
npm install
npm run build
cd ..

# 4. Initialize environment variables
cp env.example .env
```

---

### 3. Ollama Setup (Multi-Caller Concurrency)

Pull the recommended models:
```bash
ollama pull llama3.2:3b-instruct-q4_K_M
ollama pull nomic-embed-text
```

#### Enable Multi-Caller Parallelism:
By default, Ollama executes requests sequentially (`OLLAMA_NUM_PARALLEL=1`). For simultaneous conversations across concurrent callers:
```bash
sudo systemctl edit ollama.service
```
Add:
```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
```
Then restart Ollama:
```bash
sudo systemctl restart ollama
```

---

### 4. Running CallForge

Start the main application:
```bash
python3 main.py
```

The system will initialize:
- **Web UI & REST API**: `https://localhost:8080` (or `http://localhost:8080` depending on `SSL_KEYFILE` setting)
- **Agent AudioSocket Lines**: Starting on port `9092` (one dedicated port per deployed agent)

> 💡 **Accessing from another device on the same Wi-Fi?** Use your machine's current LAN IP (e.g. `https://10.132.27.21:8080`). If your Wi-Fi IP changes, update your browser address accordingly to prevent `net::ERR_ADDRESS_UNREACHABLE`.

On first run, CallForge automatically creates and deploys a **Default Agent** on extension **2000** (port `9092`).

---

### 5. Testing the Agent

#### Option A: In-Browser Simulator (No Telephony Required)
1. Open `https://localhost:8080` in your web browser.
2. Sign in or click **Launch Console**.
3. Open the **Simulator** from the navigation bar.
4. Select an agent, enter a caller ID, and click **Start Call** to speak directly via your microphone and speakers.

#### Option B: Softphone / Asterisk Calling
Configure any SIP softphone (Zoiper, Linphone, MicroSIP):
- **SIP Server**: `<your-server-ip>:5060` (UDP)
- **Username**: `guest`
- **Password**: `guestpass123`
- **Dial**: `2000` (Default Agent), `2001` (Mika), or any configured extension.

---

### 6. Asterisk Telephony Setup

Pre-configured Asterisk configuration files are located in `asterisk-server/`.

If running Asterisk directly on your host:
```bash
# Reload PJSIP configuration and dialplan
asterisk -rx "module reload res_pjsip.so"
asterisk -rx "dialplan reload"
```

#### Dialplan Integration:
CallForge dynamically generates and maintains agent dialplan entries in `asterisk-server/extensions_agents.conf`. Include it in `/etc/asterisk/extensions.conf`:
```ini
#include "/path/to/calling_agent/asterisk-server/extensions_agents.conf"
```

---

## Project Structure

```
calling_agent/
├── api/                                # FastAPI REST control plane
│   ├── routes/
│   │   ├── agents.py                   # Agent CRUD, personas, voice assignment & A/B variants
│   │   ├── auth.py                     # User authentication, signup & session tokens
│   │   ├── callers.py                  # Caller profiles & cross-call memory retrieval
│   │   ├── calls.py                    # Call history, transcripts & audio recordings
│   │   ├── campaigns.py                # Outbound campaigns, lead lists & auto-dialing
│   │   ├── documents.py                # RAG document upload, indexing & vector store
│   │   ├── meta.py                     # System health, voice sample preview & webhook test
│   │   ├── phone_numbers.py            # Real DID search, carrier purchase & dialplan binding
│   │   ├── simulator.py                # WebSocket browser audio testing endpoint
│   │   └── wallboard.py                # Live wallboard metrics & channel telemetry
│   ├── schemas.py                      # Pydantic request & response schemas
│   └── __init__.py                     # FastAPI app factory, middleware & SPA serving
├── asterisk-server/                    # Asterisk configuration (pjsip.conf, extensions.conf)
├── callforge/
│   ├── ingest/
│   │   └── documents.py                # Document parsers (PDF, DOCX, XLSX, TXT)
│   ├── runtime/
│   │   ├── agent_runtime.py            # Multi-agent port listeners & lifecycle manager
│   │   ├── asterisk_manager.py         # Asterisk AMI/ARI channel control & human transfer
│   │   ├── campaign_engine.py          # Outbound campaign dialer & retry manager
│   │   ├── dialogue.py                 # Slot-filling state machine & prompt directives
│   │   ├── dialplan.py                 # Dynamic Asterisk dialplan generator
│   │   ├── tools.py                    # Google Sheets tools & spoken entity parsers
│   │   └── voices.py                   # Voice path resolver & catalog metadata
│   └── store/
│       ├── db.py                       # SQLite database layer & platform repository
│       └── models.py                   # Data models (Agent, Call, CallerProfile, Campaign)
├── models/
│   └── piper/                          # Piper ONNX voice models and JSON configs
├── platform_data/                      # SQLite DB, WAV recordings, uploaded documents
├── processing/
│   ├── audio_buffer.py                 # Ring buffers & audio frame chunking
│   ├── canned_responses.py             # Pre-synthesized backchannels & acoustic fillers
│   ├── conversational_flow.py          # Turn-taking state machine & pause detection
│   ├── prosody.py                      # RMS, ZCR, speaking rate & emotion classifier
│   └── vad.py                          # Pooled Silero VAD detector & barge-in logic
├── services/
│   ├── caller_memory_service.py        # Cross-call profile analysis & context generation
│   ├── llm_service.py                  # Local Ollama streaming client & warm-up
│   ├── rag_service.py                  # ChromaDB vector store & semantic search
│   ├── speculative_service.py          # Speculative multi-branch LLM execution engine
│   ├── stt_service.py                  # faster-whisper CTranslate2 transcription engine
│   ├── telephony_provider.py           # DID carrier provider (Telnyx/Twilio/Sandbox)
│   ├── tts_service.py                  # Streaming Piper TTS & pitch-shift processor
│   └── voice_clone_service.py          # Acoustic profiling & reference audio cloning
├── telephony/
│   ├── protocol.py                     # AudioSocket binary protocol frame serialization
│   └── server.py                       # AudioSocket TCP server & session handler
├── web/                                # React + Vite frontend control plane
│   ├── src/
│   │   ├── components/                 # Shell, AuthModal, SimulatorModal
│   │   ├── pages/                      # LandingPage, Dashboard, Agents, Calls, Campaigns, Wallboard
│   │   ├── api.ts                      # Frontend API client
│   │   ├── auth.tsx                    # Auth state provider
│   │   └── toast.tsx                   # Toast notification system
│   ├── index.html                      # HTML root template
│   ├── package.json                    # Frontend dependencies & scripts
│   └── vite.config.ts                  # Vite build configuration
├── config.py                           # Typed Pydantic application settings
├── main.py                             # Process entry point: runtime + HTTP control plane
├── pipeline.py                         # Real-time full-duplex conversational audio pipeline
└── requirements.txt                    # Python package dependencies
```

---

## API Reference

CallForge exposes a comprehensive REST and WebSocket API at `http://localhost:8080/api`:

### Authentication & Users (`/api/auth`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/signup` | Register a new user account |
| `POST` | `/api/auth/login` | Authenticate and obtain session token |
| `GET` | `/api/auth/me` | Retrieve authenticated user profile |

### Agents (`/api/agents`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/agents` | List all configured agents |
| `POST` | `/api/agents` | Create a new agent persona |
| `GET` | `/api/agents/{id}` | Get agent details and configuration |
| `PUT` | `/api/agents/{id}` | Update agent settings, prompt, or voice |
| `DELETE` | `/api/agents/{id}` | Delete an agent |
| `POST` | `/api/agents/{id}/deploy` | Deploy agent on AudioSocket port & extension |
| `POST` | `/api/agents/{id}/stop` | Stop an active agent line |
| `POST` | `/api/agents/{id}/clone-voice` | Upload reference WAV to clone persona voice |

### Phone Numbers & DIDs (`/api/phone-numbers`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/phone-numbers/pricing` | View retail pricing and currency info |
| `GET` | `/api/phone-numbers/search` | Search available numbers by country and area code |
| `POST` | `/api/agents/{id}/phone-number/buy` | Purchase and bind a phone number to an agent |
| `DELETE` | `/api/agents/{id}/phone-number` | Release an assigned phone number |

### Call History & Transcripts (`/api/calls`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/calls` | List call sessions with pagination & filtering |
| `GET` | `/api/calls/{id}` | Get full call session details, latency & transcript |
| `GET` | `/api/calls/{id}/recording` | Stream or download call WAV recording |

### Cross-Call Memory (`/api/callers`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/callers` | List tracked caller profiles and recent topics |
| `GET` | `/api/callers/{phone}` | Get detailed profile, sentiment & call history for a number |
| `DELETE` | `/api/callers/{phone}` | Remove a caller's memory profile |

### Outbound Campaigns (`/api/campaigns`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/campaigns` | List all outbound campaigns |
| `POST` | `/api/campaigns` | Create a new campaign with lead list |
| `GET` | `/api/campaigns/{id}` | Get campaign status and lead progress |
| `POST` | `/api/campaigns/{id}/start` | Start or resume campaign dialing |
| `POST` | `/api/campaigns/{id}/pause` | Pause campaign dialing |
| `POST` | `/api/campaigns/{id}/stop` | Stop campaign |

### Knowledge Base RAG (`/api/documents`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/documents` | List indexed documents for an agent |
| `POST` | `/api/documents/upload` | Upload & index PDF, DOCX, XLSX, or TXT |
| `DELETE` | `/api/documents/{id}` | Delete a document from the vector store |

### System & Telephony Utilities (`/api`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | System health and live runtime status |
| `GET` | `/api/options` | Available models, voices, and suggested extensions |
| `GET` | `/api/voice-sample` | Synthesize and preview a voice sample |
| `POST` | `/api/tools/test-webhook` | Test Google Sheets webhook connectivity |
| `POST` | `/api/telephony/reload-asterisk` | Hot-reload Asterisk dialplan & modules |
| `GET` | `/api/wallboard/stats` | Real-time system metrics & channel occupancy |
| `WS` | `/api/simulator/ws` | WebSocket endpoint for in-browser audio simulation |

---

## Configuration Reference

Key tunable parameters in `.env`:

| Setting | Default | Description |
|---|---|---|
| **Telephony** | | |
| `TELEPHONY_HOST` | `0.0.0.0` | Bind address for AudioSocket TCP server |
| `TELEPHONY_PORT` | `9092` | Base port for agent AudioSocket listeners |
| `TELEPHONY_MAX_CONCURRENT_CALLS` | `2` | Max concurrent calls per agent line |
| `TELEPHONY_OUTBOUND_QUEUE_MAX_FRAMES` | `200` | Max buffered outbound audio frames |
| **VAD & Turn-Taking** | | |
| `VAD_SPEECH_THRESHOLD` | `0.48` | Silero VAD speech probability threshold |
| `VAD_MIN_SILENCE_MS` | `550` | Trailing silence duration to close a turn |
| `VAD_PRE_SPEECH_PADDING_MS` | `300` | Pre-roll audio padding to prevent clipped onsets |
| `VAD_MIN_SPEECH_MS` | `150` | Minimum duration to qualify as genuine speech |
| `VAD_MAX_UTTERANCE_MS` | `20000` | Maximum speech segment duration |
| `VAD_BARGE_IN_SPEECH_THRESHOLD` | `0.48` | Speech probability to trigger barge-in |
| `VAD_BARGE_IN_MIN_SPEECH_MS` | `180` | Sustained speech duration to confirm barge-in |
| `VAD_BARGE_IN_MIN_RMS` | `75.0` | Minimum RMS amplitude to trigger barge-in |
| **Speech-to-Text (STT)** | | |
| `STT_MODEL_SIZE` | `small` | faster-whisper model (`small`, `base`, `medium`) |
| `STT_DEVICE` | `cpu` | Inference device (`cpu`, `cuda`) |
| `STT_COMPUTE_TYPE` | `int8` | CTranslate2 quantization (`int8`, `float16`) |
| `STT_BEAM_SIZE` | `1` | Beam size (1 = greedy search for lowest latency) |
| `STT_NO_SPEECH_PROB_REJECT_THRESHOLD` | `0.6` | Rejection threshold for hallucinated non-speech |
| `STT_LANGUAGE_PROBABILITY_REJECT_THRESHOLD` | `0.5` | Minimum confidence for detected language |
| **Language Model (LLM)** | | |
| `LLM_BASE_URL` | `http://127.0.0.1:11434` | Ollama HTTP endpoint |
| `LLM_MODEL` | `llama3.2:3b-instruct-q4_K_M` | Ollama model tag |
| `LLM_TEMPERATURE` | `0.6` | Sampling temperature |
| `LLM_NUM_PREDICT` | `110` | Maximum tokens generated per turn |
| `LLM_KEEP_ALIVE` | `30m` | Duration to keep model warm in memory |
| `LLM_REQUEST_TIMEOUT_S` | `45.0` | Generation request timeout in seconds |
| `LLM_INITIAL_SILENCE_TIMEOUT_S` | `3.0` | Silence duration before proactive greeting |
| **Text-to-Speech (TTS)** | | |
| `TTS_VOICE_MODEL_PATH` | `models/piper/en_US-lessac-medium.onnx` | Default English Piper voice model |
| `TTS_VOICE_MODEL_PATH_HI` | `models/piper/hi_IN-priyamvada-medium.onnx` | Default Hindi Piper voice model |
| `TTS_LENGTH_SCALE` | `1.12` | Phoneme length scale (>1 = slower, clearer speech) |
| `TTS_NOISE_SCALE` | `0.5` | Piper noise scale (lower = clearer synthesis) |
| `TTS_NOISE_W_SCALE` | `0.7` | Phoneme-width noise scale |
| `TTS_VOLUME` | `1.05` | Audio gain before resampling |
| `TTS_PITCH_SHIFT_FACTOR` | `1.0` | Pitch shift multiplier (1.0 = normal, 1.15 = lighter) |

---

## License

CallForge is released under the [MIT License](LICENSE).
