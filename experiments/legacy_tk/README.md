# Legacy Tkinter Prompt Comparison

This directory contains the original research GUI and its model-call experiment.
It is intentionally isolated from the production `slashtoken` package.

- Run it directly with `python experiments/legacy_tk/gui.py`.
- It may read a local `.env` file for backwards compatibility.
- Production modules must never import this directory.
- Its route definitions and tests represent historical experiments, not the current
  SlashToken routing contract.

