"""Tkinter GUI for comparing four DeepSeek prompt routes."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from cases import ROUTE_LABELS, run_four_routes


class PromptComparisonApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Multilingual Token Cost Optimizer")
        self.root.geometry("1100x760")
        self.root.minsize(760, 560)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.completed_routes = 0

        self._build_ui()
        self.root.after(100, self._drain_events)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        ttk.Label(container, text="Enter a prompt (Chinese supported):").grid(
            row=0, column=0, sticky="w"
        )
        self.prompt_entry = scrolledtext.ScrolledText(
            container, height=7, wrap=tk.WORD, font=("TkDefaultFont", 12)
        )
        self.prompt_entry.grid(row=1, column=0, sticky="ew", pady=(5, 8))
        self.prompt_entry.focus_set()

        controls = ttk.Frame(container)
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        controls.columnconfigure(1, weight=1)
        self.submit_button = ttk.Button(
            controls, text="Submit", command=self.submit
        )
        self.submit_button.grid(row=0, column=0, padx=(0, 12))
        self.status = ttk.Label(controls, text="Ready")
        self.status.grid(row=0, column=1, sticky="w")

        outputs = ttk.Frame(container)
        outputs.grid(row=3, column=0, sticky="nsew")
        for index in range(2):
            outputs.rowconfigure(index, weight=1)
            outputs.columnconfigure(index, weight=1)

        self.output_boxes: dict[str, scrolledtext.ScrolledText] = {}
        for index, (route, label) in enumerate(ROUTE_LABELS.items()):
            frame = ttk.LabelFrame(outputs, text=label, padding=6)
            frame.grid(
                row=index // 2,
                column=index % 2,
                sticky="nsew",
                padx=(0 if index % 2 == 0 else 5, 5 if index % 2 == 0 else 0),
                pady=(0 if index < 2 else 5, 5 if index < 2 else 0),
            )
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            box = scrolledtext.ScrolledText(
                frame, wrap=tk.WORD, state=tk.DISABLED, font=("TkDefaultFont", 11)
            )
            box.grid(row=0, column=0, sticky="nsew")
            self.output_boxes[route] = box

    def _set_output(self, route: str, text: str) -> None:
        box = self.output_boxes[route]
        box.configure(state=tk.NORMAL)
        box.delete("1.0", tk.END)
        box.insert("1.0", text)
        box.configure(state=tk.DISABLED)

    def submit(self) -> None:
        prompt = self.prompt_entry.get("1.0", "end-1c")
        if not prompt.strip():
            messagebox.showwarning("Prompt required", "Enter a prompt before submitting.")
            return

        self.submit_button.configure(state=tk.DISABLED)
        self.completed_routes = 0
        self.status.configure(text="Transforming prompts...")
        for route in self.output_boxes:
            self._set_output(route, "Waiting...")

        worker = threading.Thread(
            target=self._run_submission, args=(prompt,), daemon=True
        )
        worker.start()

    def _run_submission(self, prompt: str) -> None:
        def report(route: str, answer: str | None, error: str | None) -> None:
            self.events.put(("result", (route, answer, error)))

        try:
            run_four_routes(prompt, on_result=report)
        except Exception as exc:
            self.events.put(("fatal", str(exc)))
        finally:
            self.events.put(("done", None))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "result":
                    route, answer, error = payload  # type: ignore[misc]
                    self.completed_routes += 1
                    self._set_output(route, answer if answer is not None else f"ERROR\n\n{error}")
                    self.status.configure(
                        text=f"Receiving answers... {self.completed_routes}/4"
                    )
                elif event == "fatal":
                    messagebox.showerror("Request failed", str(payload))
                elif event == "done":
                    self.submit_button.configure(state=tk.NORMAL)
                    self.status.configure(text="Complete")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)


def main() -> None:
    root = tk.Tk()
    PromptComparisonApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
