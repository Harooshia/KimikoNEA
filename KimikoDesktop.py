"""Tkinter desktop companion UI for Kimiko."""

from __future__ import annotations


from pathlib import Path
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
import sys

from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from .Kimiko_Core import KimikoCore
    from .Minecraft_Connect import MinecraftEventServer
except ImportError:
    from Kimiko_Core import KimikoCore
    from Minecraft_Connect import MinecraftEventServer

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None


class KimikoDesktopGhost:
    def __init__(self):
        self.root = tk.Tk()

        self.core = KimikoCore()

        self.core.add_reminder_callback(
            self._on_reminder
        )
        self.root.title("Kimiko")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.key_color = "#ff00ff"
        self.root.configure(bg=self.key_color)
        self.root.wm_attributes("-transparentcolor", self.key_color)

        self.width = 420
        self.height = 340
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        self.drag_zone_w = int(self.screen_w * 0.45)
        self.drag_zone_h = int(self.screen_h * 0.42)
        self.drag_min_x = self.screen_w - self.drag_zone_w
        self.drag_max_x = self.screen_w - self.width - 8
        self.drag_min_y = self.screen_h - self.drag_zone_h
        self.drag_max_y = self.screen_h - self.height - 8

        self.visible_x = self.screen_w - self.width - 24
        self.hidden_x = self.screen_w + 4
        self.y = self.screen_h - self.height - 48
        self.current_x = self.visible_x

        self.is_collapsed = False
        self.is_bubble_open = False
        self.is_animating = False
        self.is_dragging = False

        self.drag_start_mouse = (0, 0)
        self.drag_start_pos = (0, 0)

        self.response_queue = queue.Queue()

        self.minecraft_server_host = os.environ.get("KIMIKO_MINECRAFT_SERVER_HOST", "127.0.0.1")
        self.minecraft_server_port = int(os.environ.get("KIMIKO_MINECRAFT_SERVER_PORT", "5001"))
        self.minecraft_poll_interval = float(os.environ.get("KIMIKO_MINECRAFT_POLL_INTERVAL", "1.5"))
        self.minecraft_poll_url = f"http://{self.minecraft_server_host}:{self.minecraft_server_port}/events/recent"
        self.minecraft_last_event_id = 0
        self.minecraft_server = MinecraftEventServer(
            host=self.minecraft_server_host,
            port=self.minecraft_server_port,
        )
        self.minecraft_listener_thread = None
        self.minecraft_listener_stop = threading.Event()

        self.last_interaction_ts = time.time()
        self.sleep_timeout_seconds = 45
        self.is_sleeping = False

        self.image_pairs = self._load_image_pairs()
        self.expression_order = ["happy", "nervous", "worried"]
        self.active_expression = self._pick_default_expression()

        self.talk_open = False
        self.is_talking = False

        self.root.geometry(f"{self.width}x{self.height}+{self.current_x}+{self.y}")
        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            bg=self.key_color,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._create_dock_handle()
        self._create_context_menu()
        self._setup_bindings()
        self._create_bubble()
        self._draw_character()

        self.root.after(90, self._poll_queue)
        self.root.after(140, self._talk_tick)
        self.root.after(1000, self._idle_tick)

    def _prepare_binary_alpha_image(self, img):
        if Image is None:
            return img
        rgba = img.convert("RGBA")
        px = rgba.load()
        width, height = rgba.size
        key_r, key_g, key_b = 255, 0, 255
        for y in range(height):
            for x in range(width):
                r, g, b, a = px[x, y]
                px[x, y] = (key_r, key_g, key_b, 255) if a < 170 else (r, g, b, 255)
        return rgba

    def _fit_image(self, img):
        if Image is None:
            return img
        max_w = int(self.width * 0.88)
        max_h = int(self.height * 0.88)
        src_w, src_h = img.size
        if src_w <= 0 or src_h <= 0:
            return img
        scale = min(max_w / src_w, max_h / src_h)
        new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
        return img.resize(new_size, Image.Resampling.LANCZOS)

    def _load_image_file(self, path):
        if Image is not None and ImageTk is not None:
            try:
                pil_img = Image.open(path).convert("RGBA")
                pil_img = self._fit_image(pil_img)
                pil_img = self._prepare_binary_alpha_image(pil_img)
                return ImageTk.PhotoImage(pil_img)
            except Exception:
                return None
        try:
            return tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None

    def _load_image_pairs(self):
        folder = Path(__file__).resolve().parent
        files = sorted(folder.glob("*.png"))
        grouped = {}
        for file in files:
            stem = file.stem.lower()
            if stem.endswith("_open"):
                key, mouth = stem[:-5], "open"
            elif stem.endswith("_closed"):
                key, mouth = stem[:-7], "closed"
            elif stem.endswith("-open"):
                key, mouth = stem[:-5], "open"
            elif stem.endswith("-closed"):
                key, mouth = stem[:-7], "closed"
            else:
                continue

            img = self._load_image_file(file)
            if img is None:
                continue
            grouped.setdefault(key, {})[mouth] = img

        pairs = {}
        for key, slot in grouped.items():
            closed = slot.get("closed")
            opened = slot.get("open")
            if closed is None and opened is not None:
                closed = opened
            if opened is None and closed is not None:
                opened = closed
            if closed or opened:
                pairs[key] = (closed, opened)
        return pairs

    def _pick_default_expression(self):
        for name in self.expression_order:
            if name in self.image_pairs:
                return name
        return next(iter(self.image_pairs.keys()), "fallback")

    def _select_idle_expression(self):
        if self.is_sleeping and "worried" in self.image_pairs:
            return "worried"
        if self.core.get_current_mode() == "minecraft" and "nervous" in self.image_pairs:
            return "nervous"
        if "happy" in self.image_pairs:
            return "happy"
        return self._pick_default_expression()

    def _create_dock_handle(self):
        self.dock = tk.Toplevel(self.root)
        self.dock.withdraw()
        self.dock.overrideredirect(True)
        self.dock.attributes("-topmost", True)
        self.dock.configure(bg=self.key_color)
        self.dock.wm_attributes("-transparentcolor", self.key_color)

        self.dock_canvas = tk.Canvas(self.dock, width=26, height=110, bg=self.key_color, highlightthickness=0)
        self.dock_canvas.pack(fill="both", expand=True)
        self.dock_canvas.create_rectangle(3, 5, 24, 105, fill="#d9d4ff", outline="#8e84d2", width=2)
        self.dock_canvas.create_text(14, 54, text="◀", font=("Segoe UI", 11, "bold"), fill="#4a417e")

        self.dock_canvas.bind("<Button-1>", self.on_dock_click)
        self.dock_canvas.bind("<Button-3>", self.on_dock_right_click)
        self.dock_canvas.bind("<Button-2>", self.on_dock_right_click)

    def _place_dock_handle(self):
        x = self.screen_w - 26
        y = int(self.y + (self.height - 110) / 2)
        y = max(0, min(self.screen_h - 110, y))
        self.dock.geometry(f"26x110+{x}+{y}")

    def _create_context_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0, bg="#f4f3ff", fg="#29254a", activebackground="#dcd8ff")
        self.menu.add_command(label="Open Chat", command=self.toggle_bubble)
        self.menu.add_command(label="Dock / Undock", command=self.toggle_dock)
        self.menu.add_separator()

        self.mode_menu = tk.Menu(self.menu, tearoff=0, bg="#f4f3ff", fg="#29254a", activebackground="#dcd8ff")
        self.menu.add_cascade(label="Mode", menu=self.mode_menu)
        self._reload_mode_menu()

        self.menu.add_separator()
        self.menu.add_command(label="Reset Conversation", command=self._reset_conversation)
        self.menu.add_command(label="Quit", command=self._shutdown_application)

    def _reload_mode_menu(self):
        self.mode_menu.delete(0, "end")
        for mode in self.core.get_available_modes():
            self.mode_menu.add_command(label=f"Mode: {mode.title()}", command=lambda m=mode: self._set_mode(m))

    def _setup_bindings(self):
        self.canvas.bind("<Enter>", self.on_hover_enter)
        self.canvas.bind("<Leave>", self.on_hover_leave)
        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Button-2>", self.on_right_click)

    def _create_bubble(self):
        self.bubble = tk.Toplevel(self.root)
        self.bubble.withdraw()
        self.bubble.overrideredirect(True)
        self.bubble.attributes("-topmost", True)
        self.bubble.configure(bg="#ebe7ff")

        container = tk.Frame(self.bubble, bg="#ebe7ff", bd=2, relief="solid", highlightbackground="#9f96e4")
        container.pack(fill="both", expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        msg_frame = tk.Frame(container, bg="#ebe7ff")
        msg_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 6))
        msg_frame.grid_columnconfigure(0, weight=1)
        msg_frame.grid_rowconfigure(0, weight=1)

        self.dialog_text = tk.Text(
            msg_frame,
            wrap="word",
            bg="#f4f1ff",
            fg="#2f2a56",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10),
            height=8,
            padx=10,
            pady=8,
            insertbackground="#2f2a56",
        )
        self.dialog_text.grid(row=0, column=0, sticky="nsew")

        scroll = tk.Scrollbar(msg_frame, orient="vertical", command=self.dialog_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.dialog_text.configure(yscrollcommand=scroll.set)
        self.dialog_text.insert("1.0", "Hi! Right-click me for options.")
        self.dialog_text.configure(state="disabled")

        input_row = tk.Frame(container, bg="#ebe7ff")
        input_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

        self.entry = tk.Entry(input_row, font=("Segoe UI", 10), relief="solid", bd=1)
        self.entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.entry.bind("<Return>", self.on_submit)

        self.send_btn = tk.Button(
            input_row,
            text="Send",
            command=self.on_submit,
            bg="#d9d4ff",
            fg="#322c61",
            relief="flat",
            padx=10,
        )
        self.send_btn.pack(side="left", padx=(6, 0))

    def _set_dialog_text(self, message):
        self.dialog_text.configure(state="normal")
        self.dialog_text.delete("1.0", "end")
        self.dialog_text.insert("1.0", message)
        self.dialog_text.see("end")
        self.dialog_text.configure(state="disabled")

    def _start_minecraft_event_listener(self):
        if self.minecraft_listener_thread and self.minecraft_listener_thread.is_alive():
            return
        self.minecraft_listener_stop.clear()
        self.minecraft_listener_thread = threading.Thread(target=self._poll_minecraft_events_loop, daemon=True)
        self.minecraft_listener_thread.start()

    def _stop_minecraft_event_listener(self):
        self.minecraft_listener_stop.set()
        if self.minecraft_listener_thread and self.minecraft_listener_thread.is_alive():
            self.minecraft_listener_thread.join(timeout=2)
        self.minecraft_listener_thread = None

    def _poll_minecraft_events_loop(self):
        while not self.minecraft_listener_stop.is_set():
            try:
                query = urlparse.urlencode({"after_id": self.minecraft_last_event_id})
                with urlrequest.urlopen(f"{self.minecraft_poll_url}?{query}", timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                new_events = payload.get("events", [])
                if new_events:
                    for event in new_events:
                        self.minecraft_last_event_id = max(self.minecraft_last_event_id, int(event.get("id", 0)))
                    self._process_minecraft_events(new_events)
            except (urlerror.URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError):
                pass
            self.minecraft_listener_stop.wait(self.minecraft_poll_interval)

    def _extract_player_chat_from_context(self, context_text):
        match = re.search(r'player said "([^"]+)"', context_text)
        return match.group(1).strip() if match else ""

    def _process_minecraft_events(self, events):
        latest_event_text = ""
        should_alert_night = False

        for event in events:
            text = str(event.get("text", "")).strip()
            if not text:
                continue
            latest_event_text = text
            self.core.add_memory(f"[Minecraft] {text}")
            if event.get("kind") == "night_start":
                should_alert_night = True

        if not latest_event_text:
            return

        self.core.set_runtime_context(latest_event_text, mode="minecraft")

        if should_alert_night and "worried" in self.image_pairs:
            self.active_expression = "worried"
            self.root.after(0, self._draw_character)

        if self.core.get_current_mode() != "minecraft":
            return

        player_chat = self._extract_player_chat_from_context(latest_event_text)
        user_input = player_chat or "Any updates for me?"
        threading.Thread(
            target=self._queue_minecraft_reaction,
            args=(user_input, latest_event_text),
            daemon=True,
        ).start()

    def _queue_minecraft_reaction(self, user_input, context_text):
        reply = self.core.send(user_input, extra_context=context_text)
        self.response_queue.put(reply)

    def _sync_minecraft_mode_runtime(self):
        if self.core.get_current_mode() == "minecraft":
            self.minecraft_server.start()
            self._start_minecraft_event_listener()
        else:
            self._stop_minecraft_event_listener()
            self.minecraft_server.stop()

    def _on_reminder(self, reminder_text):
        """
        Called by KimikoCore when a reminder fires.

        The reminder timer runs on a background thread,
        so Tkinter must be updated through root.after().
        """

        self.root.after(
            0,
            self._show_reminder,
            reminder_text
        )


    def _show_reminder(self, reminder_text):
        """
        Display a reminder inside the Kimiko GUI.
        """

        self._register_activity()

        message = (
            f"REMINDER\n\n"
            f"{reminder_text}"
        )

        def show_message():
            self._set_dialog_text(message)
            self._start_talking()

            self.root.after(
                700,
                self._start_talking
            )

        # Open the chat bubble if it is not already open.
        if not self.is_bubble_open:

            if self.is_collapsed:
                self.swoop_in(
                    after=lambda: (
                        self._open_bubble(),
                        show_message()
                    )
                )

            else:
                self._open_bubble()
                show_message()

        else:
            show_message()

    def _register_activity(self):
        self.last_interaction_ts = time.time()
        if self.is_sleeping:
            self.is_sleeping = False
            self.active_expression = self._select_idle_expression()
            self._draw_character()

    def _idle_tick(self):
        idle_for = time.time() - self.last_interaction_ts
        should_sleep = idle_for >= self.sleep_timeout_seconds
        if should_sleep != self.is_sleeping:
            self.is_sleeping = should_sleep
            self.active_expression = self._select_idle_expression()
            self._draw_character()
        self.root.after(1000, self._idle_tick)

    def _set_mode(self, mode):
        self._register_activity()
        self.core.set_mode(mode)
        self._sync_minecraft_mode_runtime()
        self._set_dialog_text(f"Mode changed to {mode}.")

    def _reset_conversation(self):
        self._register_activity()
        self.core.reset_conversation()
        self._set_dialog_text("Conversation reset.")

    def _draw_character(self):
        self.canvas.delete("all")
        if self.is_collapsed:
            return

        expr = self.active_expression if self.active_expression in self.image_pairs else self._select_idle_expression()
        if expr in self.image_pairs:
            closed, opened = self.image_pairs[expr]
            frame = opened if self.talk_open else closed
            if frame is None:
                frame = closed or opened
            if frame is not None:
                self.canvas.create_image(self.width // 2, self.height // 2, image=frame)
                return

        self.canvas.create_oval(95, 40, 225, 210, fill="#f3efff", outline="#9a90dd", width=2)
        self.canvas.create_text(160, 22, text="Kimiko", font=("Segoe UI", 10, "bold"), fill="#5f55a2")
        self.canvas.create_oval(140, 110, 150, 120, fill="#2e2b51", outline="")
        self.canvas.create_oval(170, 110, 180, 120, fill="#2e2b51", outline="")

    def _talk_tick(self):
        if self.is_talking and not self.is_collapsed:
            self.talk_open = not self.talk_open
            self._draw_character()
        elif self.talk_open:
            self.talk_open = False
            self._draw_character()
        self.root.after(140, self._talk_tick)

    def _start_talking(self):
        self._register_activity()
        self.is_talking = True

    def bubble_position(self):
        bubble_w, bubble_h = 360, 240
        x = self.current_x - bubble_w - 12
        y = self.y + 8
        if x < 8:
            x = self.current_x + self.width + 12
        return f"{bubble_w}x{bubble_h}+{x}+{y}"

    def toggle_bubble(self):
        self._register_activity()
        if self.is_bubble_open:
            self.bubble.withdraw()
            self.is_bubble_open = False
            return
        if self.is_collapsed:
            self.swoop_in(after=self._open_bubble)
            return
        self._open_bubble()

    def _open_bubble(self):
        self.bubble.geometry(self.bubble_position())
        self.bubble.deiconify()
        self.bubble.lift()
        self.entry.focus_set()
        self.is_bubble_open = True

    def on_hover_enter(self, _event=None):
        self._register_activity()
        if "nervous" in self.image_pairs:
            self.active_expression = "nervous"
        self._draw_character()

    def on_hover_leave(self, _event=None):
        self._register_activity()
        self.active_expression = self._select_idle_expression()
        self._draw_character()

    def on_left_press(self, event):
        self._register_activity()
        self.is_dragging = False
        self.drag_start_mouse = (event.x_root, event.y_root)
        self.drag_start_pos = (self.current_x, self.y)

    def on_left_drag(self, event):
        if self.is_collapsed or self.is_animating:
            return
        dx = event.x_root - self.drag_start_mouse[0]
        dy = event.y_root - self.drag_start_mouse[1]
        if abs(dx) > 2 or abs(dy) > 2:
            self.is_dragging = True

        new_x = max(self.drag_min_x, min(self.drag_max_x, self.drag_start_pos[0] + dx))
        new_y = max(self.drag_min_y, min(self.drag_max_y, self.drag_start_pos[1] + dy))
        self.current_x, self.y = int(new_x), int(new_y)
        self.root.geometry(f"{self.width}x{self.height}+{self.current_x}+{self.y}")
        if self.is_bubble_open:
            self.bubble.geometry(self.bubble_position())

    def on_left_release(self, event):
        if self.is_dragging:
            return
        if self.is_collapsed:
            self.swoop_in()
            return
        if abs(event.x_root - self.drag_start_mouse[0]) < 3 and abs(event.y_root - self.drag_start_mouse[1]) < 3:
            self.toggle_bubble()

    def on_right_click(self, event):
        self._register_activity()
        self._reload_mode_menu()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def on_dock_click(self, _event=None):
        self._register_activity()
        self.swoop_in()

    def on_dock_right_click(self, event):
        self._register_activity()
        self._reload_mode_menu()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def on_submit(self, _event=None):
        self._register_activity()
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")

        command_result = self.core.handle_command(text)
        if command_result is not None:
            self._sync_minecraft_mode_runtime()
            self._set_dialog_text(command_result)
            self._start_talking()
            self.root.after(700, self._start_talking)
            return

        self._set_dialog_text("Kimiko is thinking...")
        self._start_talking()
        threading.Thread(target=self._get_reply, args=(text,), daemon=True).start()

    def _get_reply(self, text):
        self.response_queue.put(self.core.send(text))

    def _poll_queue(self):
        while not self.response_queue.empty():
            reply = self.response_queue.get()
            self._set_dialog_text(reply)

        if self.is_bubble_open:
            self.bubble.geometry(self.bubble_position())

        self.root.after(90, self._poll_queue)

    def _animate_to(self, target_x, speed= 20, after=None):
        self.is_animating = True

        def step():
            delta = target_x - self.current_x
            if abs(delta) <= speed:
                self.current_x = target_x
                self.root.geometry(f"{self.width}x{self.height}+{self.current_x}+{self.y}")
                self.is_animating = False
                if after:
                    after()
                return

            self.current_x += speed if delta > 0 else -speed
            self.root.geometry(f"{self.width}x{self.height}+{self.current_x}+{self.y}")
            self.root.after(16, step)

        step()

    def toggle_dock(self):
        self._register_activity()
        if self.is_collapsed:
            self.swoop_in()
        else:
            self.swoop_out()

    def swoop_in(self, after=None):
        if self.is_animating:
            return
        self.is_collapsed = False
        self.dock.withdraw()

        def done():
            self._draw_character()
            if after:
                after()

        self._animate_to(self.visible_x, after=done)

    def swoop_out(self):
        if self.is_animating:
            return
        self.is_collapsed = True
        if self.is_bubble_open:
            self.bubble.withdraw()
            self.is_bubble_open = False

        def done():
            self._draw_character()
            self._place_dock_handle()
            self.dock.deiconify()
            self.dock.lift()

        self._animate_to(self.hidden_x, after=done)

    def _shutdown_application(self, _event=None):

        self.core.remove_reminder_callback(
            self._on_reminder
        )

        self._stop_minecraft_event_listener()
        self.minecraft_server.stop()

        self.root.destroy()

    def run(self):
        self.root.bind("<Escape>", self._shutdown_application)
        self.root.bind("<Double-Button-1>", lambda _e: self.toggle_dock())
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown_application)
        self.root.mainloop()


if __name__ == "__main__":
    KimikoDesktopGhost().run()