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
# for file in Champaud Geneva Leveille Lyon MTLN Palasis Paris Pauline VionColas Yamaguchi York; do echo "----------> $file"; childes-pipeline.sh ${file}.cha.gz; done

set -e       # stop on error

# --- Configuration ---
# Path to your scripts and models
# UDPipe model list: https://lindat.mff.cuni.cz/repository/items/41f05304-629f-4313-b9cf-9eeb0a2ca7c6
DATAPATH="."
SERVER_IP="141.58.164.21"  # replace with your server IP address or domain name
PYPATH="$HOME/git/french-childes"  # adjust to your path
TAGGER_PAR="${DATAPATH}/italian.par"   # TreeTagger parameter file
API_MODEL="italian-isdt-ud-2.5"  # UDPipe model. For German: german-gsd-ud
HTML_DIR="ch_it"  # subfolder for parsed HTML files (don't precede with './')
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
    --pos_utterance '^(AUX|VER|VV)' --pos_output '(AUX|VER|VV)' \
    --write_conllu --html_dir "${HTML_DIR}" --server_url "${SERVER_URL}" \
    --api_model "${API_MODEL}" --parameters "${TAGGER_PAR}"   # (un)comment --parameters to (not) use TreeTagger

echo ""
echo "--- Pipeline finished successfully ---"
if [ -f "${FILE_BASENAME}.coded.conllu" ]; then
    echo "CoNLL-U output: ${FILE_BASENAME}.cha.conllu"
fi
echo "Next steps:"
echo "- Concatenate CSV files if needed, e.g."
echo '    head -n 1 "$(ls *.light.csv | head -n 1)" > all.csv; tail -n +2 -q *.light.csv >> all.csv'

if [ -d "${HTML_DIR}" ]; then
  echo "---"
  echo "- HTML files in: ${HTML_DIR}/    Delete or upload them to your server:"
  echo "   rsync -zav --no-perms ${HTML_DIR}/ ${SERVER_IP}:/Library/WebServer/Documents/${HTML_DIR}"
  echo "   ssh -x ${SERVER_IP} \"chmod 644 /Library/WebServer/Documents/${HTML_DIR}/*.html\""
fi

# exit     ## exit here if you don't want to run dql.py

echo ""
echo "--- Step 2: (Optional) Add linguistic codings with dql.py ---"
# dql.py takes a CoNLL-U file and a request file and outputs a new CoNLL-U file with metadata codings.
# You may need to adjust the arguments. 
# dql.py requires grewpy to be installed, see https://grew.fr/usage/python/
#
DQL_REQUESTS="childes-italian.query"
if [ -f "$DQL_REQUESTS" ]; then
    echo "Running dql.py to add codings..."
    python3 "${PYPATH}/dql.py" --first_rule "${DQL_REQUESTS}" "${FILE_BASENAME}.conllu" > "${FILE_BASENAME}.coded.conllu"
    echo "  Codings added. New CoNLL-U file: ${FILE_BASENAME}.coded.conllu"
    echo "Running dql.py to merge codings into table..."
    python3 "${PYPATH}/dql.py" --code_head --merge "${FILE_BASENAME}.parsed.csv" "${FILE_BASENAME}.coded.conllu"
    # light version: only verb rows and selected columns, strip coding node details
    gawk '($14~/VER/ || $21!~/VERB/)' "${FILE_BASENAME}.parsed.coded.csv" |\
        cut -d $'\t' -f1-4,6-10,12-15,28- |\
        perl -npe 's/\(\d+>\d+_.*?\)//g'> "${FILE_BASENAME}.light.coded.csv"
    echo "Light version of the table: ${FILE_BASENAME}.light.coded.csv"
    echo "Zipping unused files to save space..."
    gzip -f ${FILE_BASENAME}*.csv ${FILE_BASENAME}*.conllu
    gunzip -f "${FILE_BASENAME}.light.coded.csv.gz"   # keep light coded csv unzipped
else
    echo "Skipping dql.py (request file not found: ${DQL_REQUESTS})"
fi
