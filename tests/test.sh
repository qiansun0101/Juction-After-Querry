#!/bin/bash
# Chess Gauntlet verifier entry point. Writes /logs/verifier/reward.txt.
mkdir -p /logs/verifier
python3 /tests/verify.py || echo 0 > /logs/verifier/reward.txt
