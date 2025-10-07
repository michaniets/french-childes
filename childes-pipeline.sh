#!/bin/bash
#
# childes-pipeline.sh
# Version 2.0
# AS Oct 2025
#
# pipeline to process a CHAT file. It uses childes.py verion>=4.0 to handle
# conversion, tagging, parsing, and HTML generation in a single step.
# The resulting .conllu file can then be used for further analysis.
#

# Stop script on any error
set -e

# --- Configuration ---
# Path to your scripts and models
# UDPipe model list: https://lindat.mff.cuni.cz/repository/items/41f05304-629f-4313-b9cf-9eeb0a2ca7c6
DATAPATH="."
SERVER_IP="999.99.999.99"  # replace with your server IP address or domain name
PYPATH="$HOME/git/french-childes"  # adjust to your path
TAGGER_PAR="${DATAPATH}/perceo-spoken-french-utf.par"   # TreeTagger parameter file
API_MODEL="french"  # UDPipe model. For German: german-gsd-ud
HTML_DIR="html"  # subfolder for parsed HTML files (don't precede with './')
SERVER_URL="https://${SERVER_IP}/${HTML_DIR}"  # julienas - keep string short to avoid large output files

# Check for input file
if [ -z "$1" ]; then
    echo "Usage: $0 <chat_file.cha>"
    exit 1
fi

INPUT_FILE="$1"
FILE_BASENAME=$(basename "${INPUT_FILE}" .cha)

# --- Main Processing ---

echo "--- Step 1: Running childes.py for conversion, tagging, and parsing ---"
# Version>=4.0 of childes.py replaces the old multi-step process.
# It converts the CHAT file, runs TreeTagger, calls the UDPipe API,
# generates HTML, and merges all data into the final CSV and CoNLL-U files.
python3 "${PYPATH}/childes.py" "${INPUT_FILE}" \
    --parameters "${TAGGER_PAR}" --api_model "${API_MODEL}" \
    --write_conllu --html_dir "${HTML_DIR}" --server_url "${SERVER_URL}" \
    --pos_utterance '(AUX|VER)' --pos_output '(AUX|VER)'

echo ""
echo "--- Step 2: (Optional) Add linguistic codings with dql.py ---"
# This step is a placeholder for your existing dql.py workflow.
# It assumes dql.py takes a CoNLL-U file and a request file,
# and outputs a new CoNLL-U file with metadata codings.
# You may need to adjust the arguments. 
# dql.py requires grewpy to be installed.
#
# DQL_REQUESTS="${DATAPATH}/requests.tsv"
# if [ -f "$DQL_REQUESTS" ]; then
#     echo "Running dql.py to add codings..."
#     python3 "${PYPATH}/dql.py" "${FILE_BASENAME}.cha.conllu" \
#         -r "${DQL_REQUESTS}" \
#         -o "${FILE_BASENAME}.coded.conllu"
# else
#     echo "Skipping dql.py (request file not found: ${DQL_REQUESTS})"
# fi


echo ""
echo "--- Pipeline finished successfully ---"
echo "Full output file: ${FILE_BASENAME}.cha.parsed.csv"
echo "Work output file: ${FILE_BASENAME}.cha.work.csv"
echo "Concatenate CSV files if needed:"
echo '  head -n 1 "$(ls *.light.csv | head -n 1)" > all.csv; tail -n +2 -q *.light.csv >> all.csv'
if [ -f "${FILE_BASENAME}.coded.conllu" ]; then
    echo "CoNLL-U output: ${FILE_BASENAME}.cha.conllu"
fi
if [ -d "${HTML_DIR}" ]; then
  echo "---"
  echo "HTML files in: ${HTML_DIR}/    Delete or upload them with (adapt to your server):"
  echo "   rsync -zav --no-perms ${HTML_DIR}/ ${SERVER_IP}:/Library/WebServer/Documents/${HTML_DIR}"
  echo "   ssh -x ${SERVER_IP} \"chmod 644 /Library/WebServer/Documents/${HTML_DIR}/*.html\""
  echo ""
fi