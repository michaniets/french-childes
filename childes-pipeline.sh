#!/bin/bash
#
# childes-pipeline.sh
# Version 2.0
# Oct 2025
#
# pipeline to process a CHAT file. It uses childes.py verion>=4.0 to handle
# conversion, tagging, parsing, and HTML generation in a single step.
# The resulting .conllu file can then be used for further analysis.
#

set -e      # stop on error

# --- Configuration ---
# Path to your scripts and models
# UDPipe model list: https://lindat.mff.cuni.cz/repository/items/41f05304-629f-4313-b9cf-9eeb0a2ca7c6
DATAPATH="."
SERVER_IP="999.99.999.99"  # replace with your server IP address or domain name
PYPATH="."  # adjust to your path
TAGGER_PAR="${DATAPATH}/perceo-spoken-french-utf.par"   # TreeTagger parameter file
API_MODEL="french"  # UDPipe model. For German: german-gsd-ud / Italian: italian-isdt-ud-2.5
HTML_DIR="html"  # subfolder for parsed HTML files (don't precede with './')
SERVER_URL="https://${SERVER_IP}/${HTML_DIR}"  # julienas - keep string short to avoid large output files

# Check for input file
if [ -z "$1" ]; then
    echo "Usage: $0 <chat_file.cha[.gz]>"
    exit 1
fi

INPUT_FILE="$1"
FILE_BASENAME=$(basename "$(basename "${INPUT_FILE}" .gz)" .cha)  # remove the .cha and optionally .gz suffix

# --- Main Processing ---

echo "--- Step 1: Running childes.py for conversion, tagging, and parsing ---"
# Version>=4.0 of childes.py replaces the old multi-step process.
# It converts the CHAT file and calls the UDPipe API
# It optionally runs TreeTagger and generates HTML and CoNLL-U
python3 "${PYPATH}/childes.py" "${INPUT_FILE}" \
    --pos_utterance '(AUX|VER|VV)' --pos_output '(AUX|VER|VV)' \
    --write_conllu --html_dir "${HTML_DIR}" --server_url "${SERVER_URL}" \
    --api_model "${API_MODEL}" #--parameters "${TAGGER_PAR}"   # (un)comment --parameters to (not) use TreeTagger

echo ""
echo "--- Pipeline finished successfully ---"
echo "Full output file: ${FILE_BASENAME}.cha.parsed.csv"
echo "Work output file: ${FILE_BASENAME}.cha.work.csv"
echo "Next steps:"
echo "- Concatenate CSV files if needed, e.g."
echo '    head -n 1 "$(ls *.light.csv | head -n 1)" > all.csv; tail -n +2 -q *.light.csv >> all.csv'
if [ -f "${FILE_BASENAME}.coded.conllu" ]; then
    echo "CoNLL-U output: ${FILE_BASENAME}.cha.conllu"
fi

if [ -d "${HTML_DIR}" ]; then
  echo "---"
  echo "- HTML files in: ${HTML_DIR}/    Delete or upload them to your server:"
  echo "   rsync -zav --no-perms ${HTML_DIR}/ ${SERVER_IP}:/Library/WebServer/Documents/${HTML_DIR}"
  echo "   ssh -x ${SERVER_IP} \"chmod 644 /Library/WebServer/Documents/${HTML_DIR}/*.html\""
  echo ""
fi

# exit     ## exit here if you don't want to run dql.py

echo ""
echo "--- Step 2: (Optional) Add linguistic codings with dql.py ---"
# dql.py takes a CoNLL-U file and a request file and outputs a new CoNLL-U file with metadata codings.
# You may need to adjust the arguments. 
# dql.py requires grewpy to be installed, see https://grew.fr/usage/python/
#
DQL_REQUESTS="${DATAPATH}/object-clitics.dql.query"
if [ -f "$DQL_REQUESTS" ]; then
    echo "Running dql.py to add codings..."
    python3 "${PYPATH}/dql.py" "${DQL_REQUESTS}" "${FILE_BASENAME}.conllu" > "${FILE_BASENAME}.coded.conllu"
    echo "Running dql.py to merge codings into table..."
    python3 "${PYPATH}/dql.py" --code_head --merge "${FILE_BASENAME}.parsed.csv" "${FILE_BASENAME}.coded.conllu"
else
    echo "Skipping dql.py (request file not found: ${DQL_REQUESTS})"
fi
