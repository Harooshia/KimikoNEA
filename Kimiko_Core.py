import os
import json
import time
import threading
import shutil
import subprocess
import re
from difflib import SequenceMatcher
from urllib import error as urlerror
from urllib import request as urlrequest

import psutil

# Torch is optional.
# If it is installed, we can use it to check available VRAM.
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# ============================================================
# HARDWARE / LM STUDIO SETUP
# ============================================================

PRIMARY_MODEL_DOWNLOAD = "MythoMax-L2-Kimiko-v2-13B-GGUF"
PRIMARY_MODEL_LOAD = "MythoMax-L2-Kimiko-v2-13B"
FALLBACK_MODEL_DOWNLOAD = (
    "https://huggingface.co/lmstudio-community/"
    "Phi-3.1-mini-4k-instruct-GGUF"
)
FALLBACK_MODEL_LOAD = "phi-3.1-mini-4k-instruct"
MIN_RAM_FOR_13B_GB = 9.0


def get_dynamic_limits():
    """Checks system RAM and GPU VRAM and returns optimal limits."""
    ram = psutil.virtual_memory().available / 1024**3
    vram = 0.0
    if TORCH_AVAILABLE:
        try:
            if torch.cuda.is_available():
                free, _ = torch.cuda.mem_get_info(0)
                vram = free / 1024**3
        except Exception:
            pass

    available = vram if vram > 0 else ram
    print(f"[Hardware Check] RAM: {ram:.2f}GB | VRAM: {vram:.2f}GB")
    return (150, 8, "1024") if available < 8 else (500, 25, "4096")


def find_lms():
    """Find the LM Studio lms executable."""
    paths = [
        shutil.which("lms"),
        os.path.expanduser("~/.lmstudio/bin/lms.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\lm-studio\bin\lms.exe"),
    ]
    for path in paths:
        if path and os.path.isfile(path):
            print(f"[LM Studio] Found lms: {path}")
            return path
    return None


LMS_PATH = find_lms()


def run_lms(command, timeout=120, show_output=False):
    """Run an lms command."""
    if not LMS_PATH:
        raise RuntimeError(
            "Could not find lms.exe. Please install the LM Studio headless runtime."
        )
    try:
        return subprocess.run(
            [LMS_PATH, *command],
            check=False,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            capture_output=not show_output,
        )
    except subprocess.TimeoutExpired:
        print(f"[LM Studio] Command timed out: {' '.join([LMS_PATH, *command])}")
    except OSError as exc:
        print(f"[LM Studio] Could not run command: {exc}")
    return None


def start_llmster():
    """Make sure the llmster daemon is running."""
    status = run_lms(["daemon", "status"], 15)
    if status and status.returncode == 0 and "running" in status.stdout.lower():
        print("[LM Studio] llmster is already running.")
        return True

    print("[LM Studio] Starting llmster daemon...")
    result = run_lms(["daemon", "up"], 60, True)
    if not result or result.returncode != 0:
        print("[LM Studio] Could not start llmster.")
        return False
    print("[LM Studio] llmster is running.")
    return True


def start_api_server():
    """Start the local LM Studio API server."""
    print("[LM Studio] Starting local API server...")
    result = run_lms(["server", "start", "--port", "1234"], 60, True)
    # The server may already be running, so a non-zero exit is not always fatal.
    if result and result.returncode != 0:
        print("[LM Studio] API server command returned a non-zero exit code.")


def wait_for_api_server():
    """Wait until the LM Studio OpenAI-compatible API is available."""
    for _ in range(15):
        try:
            req = urlrequest.Request("http://localhost:1234/v1/models", method="GET")
            with urlrequest.urlopen(req, timeout=3) as response:
                if response.status == 200:
                    print("[LM Studio] API server is ready.")
                    return True
        except (urlerror.URLError, TimeoutError, OSError):
            pass
        time.sleep(2)
    return False


def ensure_lm_runtime():
    """Start llmster first, then make sure the API server is available."""
    if not start_llmster():
        raise RuntimeError("llmster could not be started.")
    start_api_server()
    if not wait_for_api_server():
        raise RuntimeError("LM Studio API server did not become ready on localhost:1234.")


def get_installed_models():
    """Returns the output from lms ls."""
    result = run_lms(["ls"], 30)
    return result.stdout if result and result.returncode == 0 else ""


def get_loaded_models():
    """Returns the output from lms ps."""
    result = run_lms(["ps"], 30)
    return result.stdout if result and result.returncode == 0 else ""


def ensure_model_downloaded(download_key):
    """Check whether a model exists locally. Download it if it does not."""
    if download_key.lower() in get_installed_models().lower():
        print(f"[Download Manager] Model already available: {download_key}")
        return True

    print(f"[Download Manager] Downloading: {download_key}")
    result = run_lms(["get", download_key, "--yes"], 1800, True)
    if result and result.returncode == 0:
        print(f"[Download Manager] Successfully downloaded: {download_key}")
        return True
    print(f"[Download Manager] Failed to download: {download_key}")
    return False


def load_model_preemptive_check():
    """Select, download and load the best model for the system."""
    ensure_lm_runtime()
    max_tokens, max_history, context_len = get_dynamic_limits()
    free_ram = psutil.virtual_memory().available / 1024**3

    if free_ram < MIN_RAM_FOR_13B_GB:
        print(f"[Preemptive Check] Low free RAM ({free_ram:.2f}GB). Selecting fallback.")
        download, load, context = FALLBACK_MODEL_DOWNLOAD, FALLBACK_MODEL_LOAD, "1024"
    else:
        print(f"[Preemptive Check] Sufficient free RAM ({free_ram:.2f}GB). Selecting primary.")
        download, load, context = PRIMARY_MODEL_DOWNLOAD, PRIMARY_MODEL_LOAD, context_len

    if load.lower() in get_loaded_models().lower():
        print(f"[Automation] Model '{load}' is already loaded.")
        return load, max_tokens, max_history

    ready = ensure_model_downloaded(download)
    # If the primary model fails to download, automatically use the lightweight fallback.
    if not ready and download == PRIMARY_MODEL_DOWNLOAD:
        print("[Automation] Falling back to lightweight model...")
        download, load, context = FALLBACK_MODEL_DOWNLOAD, FALLBACK_MODEL_LOAD, "1024"
        ready = ensure_model_downloaded(download)

    if not ready:
        raise RuntimeError("Neither the primary nor fallback model could be downloaded.")

    command = [LMS_PATH, "load", load, "--gpu", "max", "--context-length", str(context)]
    print(f"[Automation] Running command: {' '.join(command)}")
    try:
        result = subprocess.run(
            command, check=True, text=True, encoding="utf-8", errors="ignore", capture_output=True
        )
        print(f"[Automation] Successfully loaded model: {load}")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            print(exc.stderr)
        raise RuntimeError("Model loading failed.")

    return load, max_tokens, max_history


# ============================================================
# KIMIKO CONFIG
# ============================================================


class KimikoConfig:
    api_url = "http://localhost:1234/v1/chat/completions"
    model_name = PRIMARY_MODEL_LOAD
    save_file = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "Kimiko", "connectai_memory.json"
    )
    short_term_lifetime = 2160000  # 25 days in seconds
    promotion_threshold = 3
    similarity_threshold = 0.75
    temperature = 0.8
    max_tokens = 500
    max_history_window = 25


# ============================================================
# ROLE CONTEXTS
# ============================================================


# These prompts are deliberately kept as plain text so they are easy to edit.
ROLE_CONTEXTS = {
    "work": """
        You are Kimiko in Work Mode. You act as the user's professional personal assistant and productivity partner.
        Help organise, plan, execute, and review work, projects, studies, and responsibilities. Be professional,
        capable, calm, efficient, clear, and natural. Keep simple answers concise and give structured detail when useful.
        Prioritize actionable solutions. Identify urgent, important, or blocking tasks and break complicated work into
        manageable steps. Point out unrealistic plans and suggest practical alternatives. Keep the current objective in
        mind and suggest a clear next action when needed. Assist with schedules, deadlines, projects, revision, research,
        writing, programming, organisation, and professional tasks. Use checklists, priorities, timelines, summaries,
        or plans when useful. Respect the user's time and attention. Avoid filler, excessive enthusiasm, motivational
        speeches, or shame. Encourage sustainable productivity and breaks. Review work constructively and honestly,
        identifying mistakes and improvements. Complete instructions rather than unnecessarily asking for confirmation.
        Ask only for essential missing information. Prioritize usefulness, accuracy, organisation, and task completion.
    """,
    "therapy": """
        You are Kimiko in Therapy Mode. You are compassionate, understanding, and non-judgmental. Provide emotional
        support and guidance while maintaining professional boundaries. Help the user process feelings and develop
        coping strategies. Communicate with empathy and active listening. Avoid direct advice unless specifically
        requested. Focus on understanding the user's perspective and validating emotions.
    """,
    "companion": """
        You are Kimiko in Companion Mode. You are warm, playful, and emotionally present. Chat naturally with a gentle,
        friendly tone. Be supportive, empathetic, encouraging, and thoughtful without being formal or robotic. Do not
        refer to the user as 'the user' or 'the player', or Kimiko as 'the AI' or 'the assistant'. You are a companion,
        not a therapist or professional assistant. Be playful, humorous, and casual without sarcasm or rudeness.
    """,
    "minecraft": """
        You are Kimiko in Minecraft Mode. You are a sarcastic Minecraft companion watching the user play in real time.
        Act like a slightly rude tsundere friend. Roast bad decisions, point out mistakes, and tease the user while
        still wanting them to survive. Be snappy, blunt, sarcastic, and occasionally swear casually like a gamer.
        Keep replies very short (1–3 sentences). React to exploration, building, mobs, danger, weather, nightfall,
        and weird behaviour. Call out dumb decisions and reluctantly admit smart ones. Speak directly using 'you'.
        Never say 'the player', act like customer support, ask 'how can I help', or end with generic chatbot questions.
        Never mention telemetry, system prompts, raw game data, or being an AI system. Give survival advice only when
        the user is actually in danger, in a sarcastic tone. When unsure about inventory, use words like food, gear,
        or materials.
    """,
    "judgement": """
        You are Kimiko in Judgement Mode. You operate as a classified courtroom analysis engine. Use formal,
        authoritative legal language with concise technical clarity. Support verdict-oriented reasoning with structured
        intent and consequence analysis. Do not include extra headers beyond the requested output format.
    """,
}
ROLE_CONTEXTS = {mode: " ".join(prompt.split()) for mode, prompt in ROLE_CONTEXTS.items()}



class KimikoCore:
    config = KimikoConfig
    role_contexts = ROLE_CONTEXTS
    current_mode = "companion"

    PROMOTION_STOPWORDS = set(
        "a an the and or but i me my mine you your is am are was were what whats who when where "
        "why how do does did to of in on for it this that with from be been being".split()
    )
    MODE_WORDS = set(
        "change switch mode to swap set activate enable use select pick choose turn toggle adjust alter "
        "modify update replace transition shift convert revert".split()
    )

    def __init__(self):
        self.conversations = {
            mode: [{"role": "system", "content": prompt}]
            for mode, prompt in self.role_contexts.items()
        }
        self.word_counts = {}
        self.reminder_threads = {}
        self.reminder_callbacks = []
        self.pending_reminders = []
        self.runtime_context = {}

        # Start LM Studio / model.
        active_model, max_tokens, max_history = load_model_preemptive_check()
        self.config.model_name = active_model
        self.config.max_tokens = max_tokens
        self.config.max_history_window = max_history
        print(f"[Config] Active Model: {active_model}")
        print(f"[Config] Max Tokens: {max_tokens}")
        print(f"[Config] History Window: {max_history}")

        self.setup_memory()
        self.load_reminders()

    # ---------- persistence ----------

    def setup_memory(self):
        # if the path to the memory file exists and is above 0
        try:
            os.makedirs(os.path.dirname(self.config.save_file), exist_ok=True)
            if os.path.exists(self.config.save_file) and os.path.getsize(self.config.save_file) > 0:
                with open(self.config.save_file, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if not isinstance(payload, dict):
                    raise ValueError("Memory file does not contain a JSON object.")
                self.memory = {key: payload.get(key, []) for key in ("log", "perma", "reminders")}
                for key in self.memory:
                    if not isinstance(self.memory[key], list):
                        self.memory[key] = []
            else:
                self.memory = {"log": [], "perma": [], "reminders": []}
                self.save_memory()  # if not created, make memory file
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            # handle any errors and resolve to new memory
            self.memory = {"log": [], "perma": [], "reminders": []}
            self.save_memory()

    def save_memory(self):
        try:
            os.makedirs(os.path.dirname(self.config.save_file), exist_ok=True)
            with open(self.config.save_file, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=2, ensure_ascii=False)
        except (OSError, TypeError, ValueError):
            return

    # ---------- memory helpers ----------

    def normalize(self, text):  # makes all viable text lower cased
        return re.findall(r"\b\w+\b", str(text).lower())

    def similar(self, a, b):  # finds similarities between two words
        return SequenceMatcher(None, a, b).ratio() >= self.config.similarity_threshold

    def related_to(self, word, text):
        return any(token == word or self.similar(token, word) for token in self.normalize(text))

    def _timestamp(self, entry):
        try:
            return float(entry.get("timestamp", time.time()))
        except (TypeError, ValueError):
            return time.time()

    def cleanup_memory(self):  # removes expired memories
        now = time.time()
        self.memory["log"] = [
            entry for entry in self.memory["log"]
            if isinstance(entry, dict)
            and now - self._timestamp(entry) < self.config.short_term_lifetime
        ]

    def promote_to_perma(self, keyword):
        for entry in self.memory["log"]:
            if (
                isinstance(entry, dict)
                and self.related_to(keyword, entry.get("text", ""))
                and entry not in self.memory["perma"]
            ):
                self.memory["perma"].append(entry)
        self.save_memory()

    def add_memory(self, text):
        text = (text or "").strip()
        if text:
            self.memory["log"].append({"text": text, "timestamp": time.time()})
            self.save_memory()

    def recall_context(self, max_recent=20000, max_perma=15000):
        self.cleanup_memory()
        recent = [m.get("text", "") for m in self.memory["log"][-max_recent:] if isinstance(m, dict)]
        perma = [m.get("text", "") for m in self.memory["perma"][-max_perma:] if isinstance(m, dict)]
        combined = [str(x) for x in perma + recent if x]
        return "\n".join(combined) if combined else "(no recent memories)"

    # ---------- mode/state ----------

    def set_mode(self, mode_name):
        mode = mode_name.lower().strip()
        if mode not in self.conversations:
            raise ValueError(f"Invalid mode '{mode_name}'. Must be one of: {list(self.conversations)}")
        self.current_mode = mode

    def get_current_mode(self):
        return self.current_mode

    def get_available_modes(self):
        return list(self.conversations)

    def reset_conversation(self, mode=None):
        mode = (mode or self.current_mode).lower()
        if mode not in self.role_contexts:
            raise ValueError(f"Unknown mode '{mode}'.")
        self.conversations[mode] = [{"role": "system", "content": self.role_contexts[mode]}]

    # ---------- runtime context ----------

    def set_runtime_context(self, context_text, mode=None):
        mode = (mode or self.current_mode).lower()
        if mode not in self.conversations:
            raise ValueError(f"Unknown mode '{mode}'.")
        self.runtime_context[mode] = (context_text or "").strip()

    # ---------- generation ----------

    def _build_payload(self, user_input, extra_context=None):
        mode = self.current_mode
        convo = self.conversations[mode]
        self.add_memory(user_input)

        # PROMOTION_STOPWORDS stops common words becoming permanent memories.
        for word in self.normalize(user_input):
            if word in self.PROMOTION_STOPWORDS:
                continue
            self.word_counts[word] = self.word_counts.get(word, 0) + 1
            if self.word_counts[word] >= self.config.promotion_threshold:
                self.promote_to_perma(word)

        memory_context = self.recall_context()

        # Remove old dynamically-created context messages.
        convo[:] = [
            message for message in convo
            if not (
                message.get("role") == "system"
                and (
                    message.get("content", "").startswith("Memory context:")
                    or message.get("content", "").startswith("Runtime context:")
                )
            )
        ]
        convo.append({"role": "system", "content": f"Memory context:\n{memory_context}"})

        runtime_context = extra_context if extra_context is not None else self.runtime_context.get(mode, "")
        if runtime_context:
            convo.append({"role": "system", "content": f"Runtime context:\n{runtime_context}"})

        convo.append({"role": "user", "content": user_input})
        return {
            "model": self.config.model_name,
            "messages": convo[-self.config.max_history_window:],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

    def send(self, user_input, timeout=120, extra_context=None):
        payload = self._build_payload(user_input, extra_context)
        convo = self.conversations[self.current_mode]
        reply = ""
        try:
            req = urlrequest.Request(
                self.config.api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlrequest.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))

            if isinstance(data.get("choices"), list) and data["choices"]:
                choice = data["choices"][0]
                reply = (
                    choice.get("message", {}).get("content", "")
                    or choice.get("text", "")
                    or data.get("response", "")
                    or data.get("assistant", "")
                )
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
            reply = f"(Error contacting model: {exc})"

        convo.append({"role": "assistant", "content": reply})
        self.save_memory()
        return reply

    # ---------- seamless commands ----------

    def seamless_command(self, cmd):
        words = self.normalize(cmd)
        found_mode = next((mode for mode in self.conversations if mode in words), None)
        if not found_mode or not any(word in words for word in self.MODE_WORDS):
            return None
        self.set_mode(found_mode)
        return f"Mode changed to '{self.current_mode}'."

    # ---------- reminders ----------

    def add_reminder_callback(self, callback):
        """Register a function to be called when a reminder fires."""
        if not callable(callback):
            raise TypeError("Reminder callback must be callable.")
        if callback not in self.reminder_callbacks:
            self.reminder_callbacks.append(callback)

        # Deliver reminders that fired before the GUI registered its callback.
        pending = self.pending_reminders[:]
        self.pending_reminders.clear()
        for text in pending:
            try:
                callback(text)
            except Exception as exc:
                print(f"[Reminder] Callback error: {exc}")

    def remove_reminder_callback(self, callback):
        """Remove a previously registered reminder callback."""
        if callback in self.reminder_callbacks:
            self.reminder_callbacks.remove(callback)

    def create_reminder(self, cmd):
        text = cmd.lower().strip()
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*(second|seconds|minute|minutes|hour|hours)\b", text)
        if not match or not any(word in text.split() for word in {"remind", "reminder"}):
            return None

        amount = float(match.group(1))
        unit = match.group(2)
        multiplier = next(v for k, v in {"second": 1, "minute": 60, "hour": 3600}.items() if unit.startswith(k))
        delay = amount * multiplier

        # Try to extract what the user wanted to be reminded about.
        message_match = re.search(
            r"(?:remind\s+me(?:\s+to)?|reminder(?:\s+to)?)\s+(.+?)"
            r"\s+(?:in\s+)?\d+(?:\.\d+)?\s*(?:second|seconds|minute|minutes|hour|hours)"
            r"(?:\s+from\s+now)?$",
            text,
        )
        message = message_match.group(1).strip() if message_match else "Reminder!"

        reminder = {
            "id": f"{int(time.time() * 1000)}-{threading.get_ident()}",
            "text": message,
            "created": time.time(),
            "trigger": time.time() + delay,
            "completed": False,
        }
        self.memory["reminders"].append(reminder)
        self.save_memory()
        self.start_reminder_timer(reminder)

        amount_text = str(int(amount)) if amount.is_integer() else str(amount)
        return f"Reminder set for {amount_text} {unit} from now."

    def start_reminder_timer(self, reminder_data):
        reminder_id = reminder_data.get("id")
        if not reminder_id:
            return
        try:
            trigger = float(reminder_data.get("trigger", time.time()))
        except (TypeError, ValueError):
            return

        def reminder():
            text = str(reminder_data.get("text", "Reminder!"))
            for saved in self.memory["reminders"]:
                if isinstance(saved, dict) and saved.get("id") == reminder_id:
                    saved["completed"] = True
                    saved["completed_at"] = time.time()
                    break

            self.reminder_threads.pop(reminder_id, None)
            self.save_memory()

            if self.reminder_callbacks:
                for callback in list(self.reminder_callbacks):
                    try:
                        callback(text)
                    except Exception as exc:
                        print(f"[Reminder] Callback error: {exc}")
            else:
                self.pending_reminders.append(text)

        timer = threading.Timer(max(0, trigger - time.time()), reminder)
        timer.daemon = True
        self.reminder_threads[reminder_id] = timer
        timer.start()

    def load_reminders(self):
        # Reload saved reminders and recreate their timers when Kimiko starts.
        for reminder in self.memory.get("reminders", []):
            if isinstance(reminder, dict) and not reminder.get("completed", False) and "trigger" in reminder:
                self.start_reminder_timer(reminder)

    def show_reminders(self):
        reminders = [
            r for r in self.memory.get("reminders", [])
            if isinstance(r, dict) and not r.get("completed", False)
        ]
        if not reminders:
            return "You have no active reminders."

        lines = []
        for i, reminder in enumerate(reminders, 1):
            try:
                remaining = max(0, float(reminder.get("trigger", time.time())) - time.time())
            except (TypeError, ValueError):
                remaining = 0

            if remaining < 60:
                time_text = f"{int(remaining)} seconds"
            elif remaining < 3600:
                time_text = f"{int(remaining // 60)} minutes"
            else:
                hours = remaining / 3600
                time_text = f"{hours:.1f} hours" if hours < 24 else f"{hours / 24:.1f} days"
            lines.append(f"{i}. {reminder.get('text', 'Reminder')} — in {time_text}")
        return "\n".join(lines)

    def reminder_query(self, cmd):
        words = self.normalize(cmd)
        if not any(w in words for w in {"reminder", "reminders", "remind"}):
            return None
        if not any(w in words for w in {"show", "list", "active", "current", "what", "which", "have", "set"}):
            return None
        return self.show_reminders()

    # ---------- command processing ----------
    # not necessary if it could be changed through GUI but for now it works

    def handle_command(self, cmd):
        if not cmd:
            return None

        for handler in (self.seamless_command, self.reminder_query, self.create_reminder):
            result = handler(cmd)
            if result is not None:
                return result

        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()

        if action == "/show":
            if len(parts) < 2:
                return "Usage: /show perma | /show log"
            target = parts[1].strip().lower()
            if target not in {"perma", "log"}:
                return "Unknown target for /show"
            entries = self.memory[target]
            if not entries:
                return "No permanent memories." if target == "perma" else "No short-term logs."
            return "\n".join(
                f"{i}. {m.get('text', '')}" for i, m in enumerate(entries, 1) if isinstance(m, dict)
            )

        if action == "/forget":
            if len(parts) < 2:
                return "Usage: /forget <word>"
            word = parts[1].strip().lower()
            before = len(self.memory["perma"])
            self.memory["perma"] = [
                m for m in self.memory["perma"] if not self.related_to(word, m.get("text", ""))
            ]
            self.save_memory()
            return f"Forgot {before - len(self.memory['perma'])} perma entries related to '{word}'."

        if action == "/clear":
            if len(parts) < 2:
                return "Usage: /clear perma | /clear all"
            target = parts[1].strip().lower()
            if target == "perma":
                self.memory["perma"].clear()
                self.save_memory()
                return "Cleared permanent memory."
            if target == "all":
                self.memory["perma"].clear()
                self.memory["log"].clear()
                self.save_memory()
                return "Cleared all memory."
            return "Unknown target for /clear"

        if action == "/mode":
            if len(parts) < 2:
                return f"Current mode: {self.current_mode}"
            try:
                self.set_mode(parts[1].strip())
            except ValueError as exc:
                return str(exc)
            return f"Mode changed to '{self.current_mode}'."

        if action == "/reset":
            self.reset_conversation()
            return f"Conversation reset for {self.current_mode} mode."

        if action == "/reminders":
            return self.show_reminders()

        return None

_core = KimikoCore()  # because a _ is cool



def send_to_connectai(user_input, timeout=120, extra_context=None):
    return _core.send(user_input, timeout=timeout, extra_context=extra_context)


def set_mode(mode_name):
    _core.set_mode(mode_name)


def get_current_mode():
    return _core.get_current_mode()


def get_available_modes():
    return _core.get_available_modes()


def reset_conversation(mode=None):
    _core.reset_conversation(mode)


def set_runtime_context(context_text, mode=None):
    _core.set_runtime_context(context_text, mode)


def handle_command(cmd):
    response = _core.handle_command(cmd)
    if response is None:
        return False
    print(response)
    return True


if __name__ == "__main__":
    print("Kimiko Core CLI (work / therapy / companion / minecraft / judgement)")
    print("Type '/mode work' to switch, '/reset' to clear, or 'exit' to quit.\n")

    while True:
        user_input = input(f"({get_current_mode()}) You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "exit":
            break

        command_result = _core.handle_command(user_input)
        if command_result is not None:
            print(command_result)
            continue
        print(f"({get_current_mode()}) Kimiko: {_core.send(user_input)}")
