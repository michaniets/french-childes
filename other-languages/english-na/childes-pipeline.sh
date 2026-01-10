#!/bin/bash
#
# childes-pipeline.sh
# Version 2.2
# Nov 2025
#
# pipeline to process a CHAT file. It uses childes.py verion>=4.0 to handle
# conversion, tagging, parsing, and HTML generation in a single step.
# The resulting .conllu file can then be used for further analysis.
#
# Added options -1 / -2 to run steps independently.
#
# MEMO: for batch processing the 11 selected French CHILDES files use:
#   for file in Champaud Geneva Leveille Lyon MTLN Palasis Paris Pauline VionColas Yamaguchi York; do echo "----------> $file"; childes-pipeline.sh ${file}.cha.gz; done
# OR:
#   for file in *.cha.gz; do echo "----------> $file"; childes-pipeline.sh ${file}; done

# --- Configuration ---
# Path to your scripts and models
# UDPipe model list: https://lindat.mff.cuni.cz/repository/items/41f05304-629f-4313-b9cf-9eeb0a2ca7c6
PYCMD="python3.11"  # or python3, adjust to your Python command
DATAPATH="."
SERVER_IP="julienas.philosophie.uni-stuttgart.de"  # replace with your server IP address or domain name
PYPATH="$HOME/git/french-childes"  # adjust to your path
TAGGER_PAR="${DATAPATH}/english.par"   # TreeTagger parameter file
API_MODEL="english-ewt-ud-2.5"  # UDPipe model. / French: french-gsd-ud-2.5-191206 / German: german-gsd-ud / Italian: italian-isdt-ud-2.5 / US English: english-ewt-ud-2.5
HTML_DIR="ch_en"  # subfolder for parsed HTML files (don't precede with './')
SERVER_URL="https://${SERVER_IP}/${HTML_DIR}"  # julienas - keep string short to avoid large output files
# For Step 2: Grew query file for adding codings
DQL_REQUESTS="childes-english.query"
CODE_HEAD_FLAG=""   # ONLY set to "--code_head" if you want coding attributes to be inserted in the table row of the node 'addlemma' (instead of 'node')


set -e       # stop on error

# --- Option Parsing ---
RUN_STEP_1=false
RUN_STEP_2=false
RUN_GZIP=false
# Store non-flag arguments
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -1 | --step1)
            RUN_STEP_1=true
            shift # past argument
            ;;
        -2 | --step2)
            RUN_STEP_2=true
            shift # past argument
            ;;
        -z | --zip)
            RUN_GZIP=true
            shift # past argument
            ;;
        -h | --help)
            echo "Usage: $0 [options] <chat_file.cha[.gz]>"
            echo "Options:"
            echo "  -1, --step1   Run only Step 1 (childes.py conversion/parsing)"
            echo "  -2, --step2   Run only Step 2 (dql.py coding/merging)"
            echo "  -h, --help    Show this help message"
            echo "If no step options are given, both Step 1 and Step 2 are run."
            exit 0
            ;;
        -*)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage."
            exit 1
            ;;
        *)
            # Save positional arg
            POSITIONAL_ARGS+=("$1")
            shift # past argument
            ;;
    esac
done

# Restore positional args (should only be the filename)
set -- "${POSITIONAL_ARGS[@]}"

# Default behavior: if no step flags were set, run both
if [ "$RUN_STEP_1" = false ] && [ "$RUN_STEP_2" = false ]; then
    RUN_STEP_1=true
    RUN_STEP_2=true
fi

# Check for input file (which should be $1 now)
if [ -z "$1" ]; then
    echo "Error: No input chat_file specified."
    echo "Usage: $0 [options] <chat_file.cha[.gz]>"
    exit 1
fi
INPUT_FILE="$1"


# --- File Basename ---
# This is needed by both steps
FILE_BASENAME=$(basename "$(basename "${INPUT_FILE}" .gz)" .cha)  # remove the .cha and optionally .gz suffix

# --- Step 1 Processing ---
if [ "$RUN_STEP_1" = true ]; then
    echo "--- Step 1: Running childes.py for conversion, tagging, and parsing ---"
    # Version>=4.0 of childes.py replaces the old multi-step process.
    # converts CHAT to table and calls the UDPipe API
    # optionally: runs TreeTagger, generates HTML, generates CoNLL-U
    $PYCMD "${PYPATH}/childes.py" "${INPUT_FILE}" \
        --pos_utterance '^(AUX|VER|VV|VH|VB|MD)' --pos_output '(AUX|VER|VV|VH|VB|MD)' \
        --write_conllu --html_dir "${HTML_DIR}" --server_url "${SERVER_URL}" \
        --api_model "${API_MODEL}" --parameters "${TAGGER_PAR}"   # (un)comment --parameters to (not) use TreeTagger

    echo ""
    echo "--- Step 1 finished successfully ---"
    if [ -f "${FILE_BASENAME}.cha.conllu" ]; then # Corrected filename check
        echo "CoNLL-U output: ${FILE_BASENAME}.cha.conllu"
    fi

    # MEMO for useful follow-up commands
    echo "Next steps:"
    echo "- Concatenate CSV files if needed, e.g."
    echo '    head -n 1 "$(ls *.light.csv | head -n 1)" > all.csv; tail -n +2 -q *.light.csv >> all.csv'

    if [ -d "${HTML_DIR}" ]; then
      echo "---"
      echo "- HTML files in: ${HTML_DIR}/    Delete or upload them to your server:"
      echo "   rsync -zav --no-perms ${HTML_DIR}/ ${SERVER_IP}:/Library/WebServer/Documents/${HTML_DIR}"
      echo "   ssh -x ${SERVER_IP} \"chmod 644 /Library/WebServer/Documents/${HTML_DIR}/*.html\""
    fi

fi


# --- Step 2 Processing ---
if [ "$RUN_STEP_2" = true ]; then
    echo ""
    echo "--- Step 2: (Optional) Add linguistic codings with dql.py ---"
    # dql.py takes a CoNLL-U file and a request file and outputs a new CoNLL-U file with metadata codings.
    # You may need to adjust the arguments.
    # dql.py requires grewpy, see https://grew.fr/usage/python/
    #
    
    # Define expected input files for step 2
    CONLLU_INPUT="${FILE_BASENAME}.conllu"
    PARSED_CSV_INPUT="${FILE_BASENAME}.parsed.csv" # Adjusted based on childes.py output
    
    # Check if Step 1's outputs exist, otherwise Step 2 can't run
    # Attempt to gunzip if .gz versions exist
    if [ ! -f "$CONLLU_INPUT" ]; then
        if [ -f "$CONLLU_INPUT.gz" ]; then
            echo "Found gzipped CoNLL-U file, uncompressing..."
            gunzip -f "$CONLLU_INPUT.gz"
        fi
    fi
    
    if [ ! -f "$PARSED_CSV_INPUT" ]; then
        if [ -f "$PARSED_CSV_INPUT.gz" ]; then
            echo "Found gzipped parsed CSV file, uncompressing..."
            gunzip -f "$PARSED_CSV_INPUT.gz"
        fi
    fi

    # Final check: if files are still missing after gunzip attempt, then exit
    if [ ! -f "$CONLLU_INPUT" ] || [ ! -f "$PARSED_CSV_INPUT" ]; then
         echo "Error: Step 2 requires output from Step 1."
         echo "Missing ${CONLLU_INPUT} or ${PARSED_CSV_INPUT} (and .gz versions were not found)"
         echo "Please run Step 1 first (or run without options)."
         exit 1
    fi
    if [ -f "$DQL_REQUESTS" ]; then
        echo "Running dql.py to add codings..."
        $PYCMD "${PYPATH}/dql.py" --first_rule "${DQL_REQUESTS}" "${CONLLU_INPUT}" > "${FILE_BASENAME}.coded.conllu"
        echo "  Codings added. New CoNLL-U file: ${FILE_BASENAME}.coded.conllu"
        
        echo ""
        echo "Running dql.py to merge codings into table..."
        # Use the correct .cha.parsed.csv name
        $PYCMD "${PYPATH}/dql.py" ${CODE_HEAD_FLAG} --merge "${PARSED_CSV_INPUT}" "${FILE_BASENAME}.coded.conllu"
        
        # Define the merged file name as output by dql.py
        MERGED_CSV="${FILE_BASENAME}.parsed.coded.csv" # Adjusted
        
        if [ -f "$MERGED_CSV" ]; then
            # light version: keep only header, verb rows and selected columns, strip coding node details (!! adapt this to your pos tags)
            echo "Creating light coded version..."
            cat "${FILE_BASENAME}.parsed.coded.csv" |\
                gawk -F'\t' '($1~/utt_id/ || $12~/^(VER|V|MD)/ || $21~/VERB/)' |\
                cut -d $'\t' -f1-4,6-10,12-15,20,28- |\
                perl -npe 's/\(\d+>\d+_.*?\)//g'> "${FILE_BASENAME}.light.coded.csv"            
            echo "Light version of the table: ${FILE_BASENAME}.light.coded.csv"
            echo "Zipping unused files to save space..."
            # Zip the *original* (non-coded) inputs from Step 1, plus the intermediate coded files
            if [ "$RUN_GZIP" = true ]; then
                echo "  Note: zipping only Step 2 outputs - original input files are kept unzipped."
                gzip -f "${PARSED_CSV_INPUT}" "${CONLLU_INPUT}" "${FILE_BASENAME}.coded.conllu" "${MERGED_CSV}"
            fi
        else
            echo "Error: Merged file ${MERGED_CSV} was not created. Skipping light version and zipping."
            # Zip only the inputs
            gzip -f "${PARSED_CSV_INPUT}" "${CONLLU_INPUT}" "${FILE_BASENAME}.coded.conllu"
        fi

    else
        echo "Skipping dql.py (request file not found: ${DQL_REQUESTS})"
    fi
    
    echo "--- Step 2 finished successfully ---"
fi

### Concatenate coded csv files
# for i in *.light.coded.csv; do gawk -F'\t' '$12~/^(VER|AUX)/' $i > verbs-only/$i;done
# cat *.light.coded.csv | head -1 > verbs-only/00header.csv
# cat verbs-only/*.csv > french-childes.coded.csv
# rm verbs_only/*