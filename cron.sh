#!/bin/bash
# =============================================================
# cron.sh - Exécution quotidienne du pipeline job_pipeline
#
# Installation sur Linux/Mac :
#   crontab -e
#   0 8 * * 1-5 /chemin/vers/job_pipeline/scheduler/cron.sh
#   → Exécute du lundi au vendredi à 8h00
#
# Sur Windows, utilise le Planificateur de tâches Windows
# (voir README.md pour les instructions)
# =============================================================

# Répertoire racine du projet (chemin absolu)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Python à utiliser (adapte si tu utilises un venv)
PYTHON="${PROJECT_DIR}/.venv/bin/python"
if [ ! -f "$PYTHON" ]; then
    PYTHON="python3"
fi

LOG_FILE="${PROJECT_DIR}/storage/cron.log"
mkdir -p "${PROJECT_DIR}/storage"

echo "=============================" >> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Démarrage" >> "$LOG_FILE"

cd "$PROJECT_DIR" && "$PYTHON" run.py >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
echo "$(date '+%Y-%m-%d %H:%M:%S') - Fin (code=$EXIT_CODE)" >> "$LOG_FILE"
exit $EXIT_CODE