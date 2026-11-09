"""The Creature Lab browser app: a FastAPI server around the robot check-up, plus its React UI.

The UI source lives in ``web-ui/`` at the repository root and is built into ``static/`` here,
so installing the package needs no Node. The server only reads and writes this machine's own
files, so it listens on 127.0.0.1 by default and rejects requests from other sites.
"""
