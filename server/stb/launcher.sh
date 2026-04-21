#!/usr/bin/env bash

BASE="$HOME/anggira"

ANGGIRA="$BASE/anggira.py"
SERVICES="$BASE/services.py"
DASH="$BASE/dashboard.py"
MUSIC="$BASE/stream_server.py"
BOT="$BASE/bot.py"

LOG=$HOME/system.log

echo "$(date) SYSTEM START" >> $LOG

# ✅ cek services.py wajib ada
if [ ! -f "$SERVICES" ]; then
    echo "$(date) ERROR: services.py tidak ditemukan! Sistem tidak bisa jalan." >> $LOG
    exit 1
fi

start() {
    NAME=$1
    FILE=$2
    LOGFILE=$3

    while true; do
        echo "$(date) START $NAME" >> $LOG

        if [ -f "$FILE" ]; then
            python3 "$FILE" >> "$LOGFILE" 2>&1
        else
            echo "$(date) ERROR: $FILE tidak ditemukan" >> $LOG
        fi

        EXIT_CODE=$?
        echo "$(date) $NAME EXIT code=$EXIT_CODE, restart 3 detik" >> $LOG

        sleep 3
    done
}

start anggira "$ANGGIRA" "$HOME/anggira.log" &
start dashboard "$DASH" "$HOME/dashboard.log" &
start music "$MUSIC" "$HOME/stream_server.log" &   
start bot "$BOT" "$HOME/bot.log" &

wait