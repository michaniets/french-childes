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
MYPATH="."
TAGGER_PAR="${MYPATH}/perceo-spoken-french-utf.par"   # TreeTagger parameter file
API_MODEL="french"  # UDPipe model name
LANGUAGE="french"   # language-specific rules (tokenise, correct tagger output) -- add to childes.py if needed
HTML_DIR="chifr"  # subfolder for parsed HTML files (don't precede with './')
SERVER_URL="https://141.58.164.21/${HTML_DIR}"  # julienas - keep string short to avoid large output files

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
python3 "${MYPATH}/childes.py" "${INPUT_FILE}" \
    --parameters "${TAGGER_PAR}" \
    --api_model "${API_MODEL}" \
    --html_dir "${HTML_DIR}" \
    --server_url "${SERVER_URL}" \
    --pos_utterance '(AUX|VER)' \
    --pos_output '(AUX|VER)' \
#    --utt_clean \
#    --utt_tagged \
    --write_conllu

echo ""
echo "--- Step 2: (Optional) Add linguistic codings with dql.py ---"
# This step is a placeholder for your existing dql.py workflow.
# It assumes dql.py takes a CoNLL-U file and a request file,
# and outputs a new CoNLL-U file with metadata codings.
# You may need to adjust the arguments. 
# dql.py requires grewpy to be installed.
#
# DQL_REQUESTS="${MYPATH}/requests.tsv"
# if [ -f "$DQL_REQUESTS" ]; then
#     echo "Running dql.py to add codings..."
#     python3 "${MYPATH}/dql.py" "${FILE_BASENAME}.cha.conllu" \
#         -r "${DQL_REQUESTS}" \
#         -o "${FILE_BASENAME}.coded.conllu"
# else
#     echo "Skipping dql.py (request file not found: ${DQL_REQUESTS})"
# fi


echo ""
echo "--- Pipeline finished successfully ---"
echo "Main output file: ${FILE_BASENAME}.cha.tagged.csv"
echo "CoNLL-U output: ${FILE_BASENAME}.cha.conllu"
echo "HTML output in: ${HTML_DIR}/"
echo "------------------------------------"