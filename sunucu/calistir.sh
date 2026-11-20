#!/bin/bash
# İlan Radarı — sunucuda saatlik toplayıcı.
# cron tarafından saatte bir çalıştırılır (bkz. sunucu/cron). İlanları toplar,
# değiştiyse akis/ilanlar.json'u GitHub'a gönderir. Çıktı: ~/toplayici.log
set -euo pipefail

DEPO="$HOME/ilan-radari-akis"
PYTHON="$(command -v python3.11 || command -v python3)"
export GIT_TERMINAL_PROMPT=0

# Aynı anda iki kopya çalışmasın.
exec 9>"$HOME/.toplayici.kilit"
flock -n 9 || { echo "Önceki çalışma sürüyor, atlandı."; exit 0; }

cd "$DEPO"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="

git pull --rebase --quiet

GECICI="$(mktemp)"
trap 'rm -f "$GECICI"' EXIT

"$PYTHON" -I toplayici/topla.py "$GECICI"

degisti=$("$PYTHON" -I - "$GECICI" <<'EOF'
import json, os, sys
yeni = json.load(open(sys.argv[1]))["ilanlar"]
yol = "akis/ilanlar.json"
eski = json.load(open(yol))["ilanlar"] if os.path.exists(yol) else None
print("evet" if yeni != eski else "hayir")
EOF
)

if [ "$degisti" = "evet" ]; then
    mkdir -p akis
    cp "$GECICI" akis/ilanlar.json
    git add akis/ilanlar.json
    git commit --quiet -m "İlanlar güncellendi"
    git push --quiet
    echo "Yeni akış gönderildi."
else
    echo "İlanlarda değişiklik yok."
fi
