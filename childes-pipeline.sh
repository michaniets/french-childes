#!/bin/bash
#
# childes-pipeline.sh - unified pipeline for all languages
# Version 3.0, Sep 2026
#
# Replaces the five per-language copies in chat-*/. The language is selected
# with -l/--lang, or inferred from the name of the current directory.
#
# Runs childes.py (CHAT -> table, tagging, parsing, HTML, CoNLL-U) and
# optionally dql.py (linguistic codings, merge into the table).
#
# USAGE
#   childes-pipeline.sh [options] <chat_file.cha[.gz]>
#
#   -l, --lang LANG   fr | de | it | en-na | en-uk  (aliases accepted, see below)
#                     Default: inferred from the current directory name.
#   -1, --step1       Run only Step 1 (childes.py)
#   -2, --step2       Run only Step 2 (dql.py)
#   -z, --zip         Gzip Step 2 outputs when finished
#   -n, --dry-run     Print the commands that would be run, then exit
#       --log FILE    Log file (default: childes-pipeline.log in the CWD)
#       --no-log      Do not write a log file
#   -h, --help        This message
#
# BATCH USE
#   cd chat-german
#   for f in *.cha.gz; do bash ../childes-pipeline.sh -z "$f"; done
#
# The log is appended to, never truncated, so a whole loop lands in one file.
# Every run writes exactly one [BEGIN] line and exactly one closing line, so
# nothing inside a loop can fail unnoticed. Triage afterwards:
#
#   grep -c '\[BEGIN\]'          childes-pipeline.log   # files attempted
#   grep -c '\[OK\] finished'    childes-pipeline.log   # files completed
#   grep    '\[FAIL\] aborted'   childes-pipeline.log   # files that failed
#   grep    '\[WARN\]'           childes-pipeline.log   # completed, but odd
#
# ---------------------------------------------------------------------------

set -uo pipefail

# ===========================================================================
# 1. SHARED CONFIGURATION  (identical for every language)
# ===========================================================================

PYCMD="uv run"                                    # or python3
PYPATH="$HOME/git/dygram/french-childes"          # the code repository
DATAPATH="."                                      # where the TreeTagger .par files live
SERVER_IP="julienas.philosophie.uni-stuttgart.de" # web server for the HTML export

CHUNK_PARSE=2000        # utterances per UDPipe API call

# Which rows carry the full utterance text, and which rows the "light" table
# keeps. These match the PARSER's universal POS (UPOS), not the tagger's tags -
# see childes.py --use_tagger_pos. VERB and AUX are what the analyses need.
POS_UTTERANCE='^(AUX|VERB)'
POS_OUTPUT='^(AUX|VERB)'

# Step 2, "light coded" table: rows to keep, by parser UPOS.
LIGHT_ROW_UPOS='^(VERB|AUX)$'

# Step 2, "light coded" table: columns to keep, BY NAME (never by number - the
# column layout of the CSV has changed before and positional selection breaks
# silently). All coding columns after conll_10 are appended automatically.
LIGHT_COLS='utt_id,utt_nr,w_nr,URLwww,speaker,child_project,language,child_other,age,age_days,word,lemma,pos,tagger_lemma,tagger_pos,utterance'

# Set to "--code_head" to attach coding attributes to the 'addlemma' row
# instead of the 'node' row.
CODE_HEAD_FLAG=""

# ===========================================================================
# 2. LANGUAGE PROFILES  (the only genuinely language-specific settings)
# ===========================================================================
# Model lists:
#   UDPipe     https://lindat.mff.cuni.cz/repository/items/41f05304-629f-4313-b9cf-9eeb0a2ca7c6
#   TreeTagger https://www.cis.uni-muenchen.de/~schmid/tools/TreeTagger/

apply_language_profile() {
    IT_DIR="${PYPATH}/other-languages/italian"
    case "$LANG_KEY" in
      fr)
        LANG_NAME="French"
        TAGGER_PAR="${DATAPATH}/perceo-spoken-french-utf.par"
        API_MODEL="french"
        GRS_FILE="${PYPATH}/french-post-parse.grs"
        HTML_DIR="ch_fr"
        DQL_REQUESTS="childes-french.query"
        EXTRA_FLAGS=""
        ;;
      de)
        LANG_NAME="German"
        TAGGER_PAR="${DATAPATH}/stts-german.par"
        API_MODEL="german-gsd-ud"
        GRS_FILE=""                       # no post-parse rules for German yet
        HTML_DIR="ch_de"
        DQL_REQUESTS="childes-german.query"
        EXTRA_FLAGS=""
        ;;
      it)
        LANG_NAME="Italian"
        TAGGER_PAR="${DATAPATH}/italian.par"
        API_MODEL="italian-isdt-ud-2.5"
        GRS_FILE="${IT_DIR}/italian-post-parse.grs"
        HTML_DIR="ch_it"
        DQL_REQUESTS="childes-italian.query"
        EXTRA_FLAGS="--verb_lexicon ${IT_DIR}/italian-verbs.grewlex.tsv --enclitic_stoplist ${IT_DIR}/italian-noclitic.txt"
        ;;
      en-na)
        LANG_NAME="English (North America)"
        TAGGER_PAR="${DATAPATH}/english.par"
        API_MODEL="english-childes-ud"
        GRS_FILE=""                       # no post-parse rules for English yet
        HTML_DIR="ch_en"
        DQL_REQUESTS="childes-english.query"
        EXTRA_FLAGS=""
        ;;
      en-uk)
        LANG_NAME="English (UK)"
        TAGGER_PAR="${DATAPATH}/english-bnc.par"
        API_MODEL="english-childes-ud"
        GRS_FILE=""                       # no post-parse rules for English yet
        HTML_DIR="ch_uk"
        DQL_REQUESTS="childes-english.query"
        EXTRA_FLAGS=""
        ;;
      *)
        return 1
        ;;
    esac
    SERVER_URL="https://${SERVER_IP}/${HTML_DIR}"
    return 0
}

# Accepted spellings for -l. Case-insensitive; '_' is read as '-'.
resolve_lang_key() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr '_' '-')" in
        fr|fra|fre|fr-fr|french|francais|français)         LANG_KEY="fr"    ;;
        de|deu|ger|de-de|german|deutsch)                   LANG_KEY="de"    ;;
        it|ita|it-it|italian|italiano)                     LANG_KEY="it"    ;;
        en-na|na|us|usa|eng-na|english-na|american)        LANG_KEY="en-na" ;;
        en-uk|uk|gb|eng-uk|english-uk|british)             LANG_KEY="en-uk" ;;
        en|eng|english)                                    LANG_KEY="en-?"  ;;
        *)                                                 LANG_KEY=""      ;;
    esac
    [ -n "$LANG_KEY" ]
}

# ===========================================================================
# 3. LOGGING
# ===========================================================================

LOG_FILE="childes-pipeline.log"
LOG_ENABLED=true
WARN_COUNT=0
RUN_ID="$$"

_stamp() { date '+%Y-%m-%d %H:%M:%S'; }

_emit() {   # _emit LEVEL message...
    local level="$1"; shift
    local line
    line="[$level] $*"
    printf '%s\n' "$line"
    if [ "$LOG_ENABLED" = true ]; then
        printf '%s %s %s\n' "$(_stamp)" "$RUN_ID" "$line" >> "$LOG_FILE"
    fi
}

info() { _emit INFO "$@"; }
ok()   { _emit OK   "$@"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); _emit WARN "$@"; }
fail() { _emit FAIL "$@"; finish 1; }

# Send a subprocess's own output to both terminal and log.
tee_log() {
    if [ "$LOG_ENABLED" = true ]; then tee -a "$LOG_FILE"; else cat; fi
}

# Capture a command's stderr in a temp file, then show it and log it. Used
# where stdout is redirected to a data file and cannot be piped through tee.
ERR_TMP="$(mktemp -t childes-pipeline)" || ERR_TMP="/tmp/childes-pipeline.$$.err"
trap 'rm -f "$ERR_TMP"' EXIT
flush_err() {
    [ -s "$ERR_TMP" ] || return 0
    cat "$ERR_TMP" >&2
    [ "$LOG_ENABLED" = true ] && cat "$ERR_TMP" >> "$LOG_FILE"
    : > "$ERR_TMP"
}

START_TS=$(date '+%s')
finish() {
    local status="${1:-0}"
    local secs=$(( $(date '+%s') - START_TS ))
    if [ "$status" -eq 0 ]; then
        if [ "$WARN_COUNT" -gt 0 ]; then
            _emit OK "finished ${FILE_BASENAME:-?} (${LANG_KEY:-?}) in ${secs}s with ${WARN_COUNT} warning(s)"
        else
            _emit OK "finished ${FILE_BASENAME:-?} (${LANG_KEY:-?}) in ${secs}s"
        fi
    else
        _emit FAIL "aborted ${FILE_BASENAME:-?} (${LANG_KEY:-?}) after ${secs}s"
    fi
    exit "$status"
}

# ===========================================================================
# 4. CHECKS  (these are what turn a silent error into a log line)
# ===========================================================================

# require_file <path> <description>
require_file() {
    [ -f "$1" ] || fail "$2 not found: $1"
}

# expect_file <path> <min_lines> <description>   - non-fatal, counts as WARN
expect_file() {
    local f="$1" min="$2" desc="$3" n
    if [ ! -f "$f" ]; then
        if [ -f "$f.gz" ]; then f="$f.gz"; else warn "$desc missing: $1"; return 1; fi
    fi
    case "$f" in
        *.gz) n=$(gzip -cd "$f" | wc -l | tr -d ' ') ;;
        *)    n=$(wc -l < "$f" | tr -d ' ') ;;
    esac
    if [ "$n" -lt "$min" ]; then
        warn "$desc has only $n line(s), expected at least $min: $f"
        return 1
    fi
    info "$desc: $n lines"
    return 0
}

# count_sents <conllu[.gz]>
count_sents() {
    local f="$1"
    [ -f "$f" ] || f="$f.gz"
    [ -f "$f" ] || { echo 0; return; }
    case "$f" in
        *.gz) gzip -cd "$f" | grep -c '^# sent_id' ;;
        *)    grep -c '^# sent_id' "$f" ;;
    esac
}

# ===========================================================================
# 5. OPTION PARSING
# ===========================================================================

RUN_STEP_1=false
RUN_STEP_2=false
RUN_GZIP=false
DRY_RUN=false
LANG_ARG=""
POSITIONAL_ARGS=()

usage() { sed -n '3,40p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        -l|--lang)   LANG_ARG="${2:-}"; shift 2 ;;
        -l=*|--lang=*) LANG_ARG="${1#*=}"; shift ;;
        -1|--step1)  RUN_STEP_1=true; shift ;;
        -2|--step2)  RUN_STEP_2=true; shift ;;
        -z|--zip)    RUN_GZIP=true; shift ;;
        -n|--dry-run) DRY_RUN=true; shift ;;
        --log)       LOG_FILE="${2:-}"; shift 2 ;;
        --log=*)     LOG_FILE="${1#*=}"; shift ;;
        --no-log)    LOG_ENABLED=false; shift ;;
        -h|--help)   usage; exit 0 ;;
        -*)          echo "Unknown option: $1 (use -h for usage)" >&2; exit 1 ;;
        *)           POSITIONAL_ARGS+=("$1"); shift ;;
    esac
done
set -- ${POSITIONAL_ARGS[@]+"${POSITIONAL_ARGS[@]}"}

if [ "$RUN_STEP_1" = false ] && [ "$RUN_STEP_2" = false ]; then
    RUN_STEP_1=true; RUN_STEP_2=true
fi

if [ $# -lt 1 ]; then
    echo "Error: no input chat_file specified." >&2
    echo "Usage: $0 [options] <chat_file.cha[.gz]>" >&2
    exit 1
fi
INPUT_FILE="$1"
FILE_BASENAME=$(basename "$(basename "$INPUT_FILE" .gz)" .cha)

# ===========================================================================
# 6. LANGUAGE RESOLUTION
# ===========================================================================

CWD_NAME=$(basename "$PWD")
LANG_SOURCE=""

if [ -n "$LANG_ARG" ]; then
    resolve_lang_key "$LANG_ARG" || { echo "Error: unknown language '$LANG_ARG'." >&2
        echo "Use one of: fr | de | it | en-na | en-uk (aliases accepted)." >&2; exit 1; }
    LANG_SOURCE="--lang $LANG_ARG"
    if [ "$LANG_KEY" = "en-?" ]; then
        # plain "english": let the directory decide, otherwise ask
        case "$CWD_NAME" in
            *english-na|*en-na) LANG_KEY="en-na" ;;
            *english-uk|*en-uk) LANG_KEY="en-uk" ;;
            *) echo "Error: 'english' is ambiguous - the two profiles differ in" >&2
               echo "       TreeTagger parameters and HTML directory." >&2
               echo "       Use -l en-na or -l en-uk." >&2; exit 1 ;;
        esac
    fi
else
    resolve_lang_key "${CWD_NAME#chat-}" || { echo "Error: cannot infer the language from the" >&2
        echo "       current directory ('$CWD_NAME'). Pass -l/--lang explicitly." >&2; exit 1; }
    LANG_SOURCE="inferred from directory '$CWD_NAME'"
    if [ "$LANG_KEY" = "en-?" ]; then
        echo "Error: directory '$CWD_NAME' does not say which English profile to use." >&2
        echo "       Pass -l en-na or -l en-uk." >&2; exit 1
    fi
fi

apply_language_profile || { echo "Error: no profile for '$LANG_KEY'." >&2; exit 1; }

# ===========================================================================
# 7. PREFLIGHT
# ===========================================================================

_emit BEGIN "$FILE_BASENAME  lang=$LANG_KEY ($LANG_NAME, $LANG_SOURCE)  host=$(hostname -s)  cwd=$PWD"

require_file "${PYPATH}/childes.py" "childes.py"
require_file "$INPUT_FILE" "input CHAT file"

CHILDES_VERSION=$(grep -m1 '^__version__' "${PYPATH}/childes.py" | cut -d'"' -f2)
CHILDES_STATUS=$(grep -m1 '^__status__'  "${PYPATH}/childes.py" | cut -d'"' -f2)
GIT_REV=$(cd "$PYPATH" && git rev-parse --short HEAD 2>/dev/null || echo "not-a-git-checkout")
GIT_DIRTY=""
(cd "$PYPATH" && git diff --quiet 2>/dev/null) || GIT_DIRTY=" (uncommitted changes)"
info "childes.py $CHILDES_VERSION ($CHILDES_STATUS), repo $GIT_REV$GIT_DIRTY"
info "model=$API_MODEL  tagger=$(basename "$TAGGER_PAR")  html=$HTML_DIR"

TAGGER_FLAGS=""
REWRITE_FLAG=""
if [ "$RUN_STEP_1" = true ]; then
    # TreeTagger is optional: warn loudly rather than fail, since the run is
    # still valid without it - but tagger_pos/tagger_lemma will be empty.
    if [ -f "$TAGGER_PAR" ]; then
        TAGGER_FLAGS="--parameters ${TAGGER_PAR} --tag_ud_tokens"
    else
        warn "TreeTagger parameter file not found: $TAGGER_PAR - running WITHOUT the tagger"
    fi

    # Grew rewriting is optional per language, but if a profile names a .grs
    # file and it is missing, that IS an error: it means the rewrite silently
    # did not happen for a language that expects it.
    if [ -n "$GRS_FILE" ]; then
        require_file "$GRS_FILE" "Grew rule file named by the $LANG_KEY profile"
        REWRITE_FLAG="--rewrite ${GRS_FILE}"
        info "Grew rewriting enabled: $(basename "$GRS_FILE")"
    else
        info "no Grew rule file for $LANG_KEY - skipping the rewrite step"
    fi
fi

# ===========================================================================
# 8. STEP 1 - childes.py
# ===========================================================================

CONLLU_FILE="${FILE_BASENAME}.conllu"
PARSED_CSV="${FILE_BASENAME}.parsed.csv"
LIGHT_CSV="${FILE_BASENAME}.light.csv"

if [ "$RUN_STEP_1" = true ]; then
    info "--- Step 1: childes.py (conversion, tagging, parsing, HTML, CoNLL-U)"

    set -- "${PYPATH}/childes.py" "$INPUT_FILE" \
        --chunk_parse "$CHUNK_PARSE" \
        --pos_utterance "$POS_UTTERANCE" --pos_output "$POS_OUTPUT" \
        --write_conllu --html_dir "$HTML_DIR" --server_url "$SERVER_URL" \
        --api_model "$API_MODEL"
    [ -n "$REWRITE_FLAG" ] && set -- "$@" $REWRITE_FLAG
    [ -n "$EXTRA_FLAGS"  ] && set -- "$@" $EXTRA_FLAGS
    [ -n "$TAGGER_FLAGS" ] && set -- "$@" $TAGGER_FLAGS

    if [ "$DRY_RUN" = true ]; then
        echo "DRY RUN: $PYCMD $*"
    else
        $PYCMD "$@" 2>&1 | tee_log
        rc=${PIPESTATUS[0]}
        [ "$rc" -eq 0 ] || fail "childes.py exited with status $rc"

        # --- post-conditions: these catch the failures that produce no error ---
        expect_file "$PARSED_CSV"  2 "parsed CSV"
        expect_file "$CONLLU_FILE" 2 "CoNLL-U"
        expect_file "$LIGHT_CSV"   2 "light CSV (check --pos_output if empty)"

        n_sent=$(count_sents "$CONLLU_FILE")
        [ "$n_sent" -gt 0 ] || warn "CoNLL-U contains no '# sent_id' lines"
        info "CoNLL-U sentences: $n_sent"

        if [ -f "$CONLLU_FILE" ]; then
            grep -q '^# udpipe_model' "$CONLLU_FILE" \
                || warn "CoNLL-U is missing the UDPipe provenance header"
            grep -q '^# text = ' "$CONLLU_FILE" \
                || warn "CoNLL-U is missing '# text' comments"
        fi

        if [ -d "$HTML_DIR" ]; then
            n_html=$(ls -1 "$HTML_DIR"/*.html 2>/dev/null | wc -l | tr -d ' ')
            info "HTML files: $n_html in $HTML_DIR/"
            [ -f "$HTML_DIR/index.html" ] || warn "no index.html in $HTML_DIR/"
        else
            warn "HTML directory not created: $HTML_DIR"
        fi

        info "Step 1 done. To publish the HTML:"
        info "  rsync -zav --no-perms ${HTML_DIR}/ ${SERVER_IP}:/Library/WebServer/Documents/${HTML_DIR}"
        info "  ssh -x ${SERVER_IP} \"chmod 644 /Library/WebServer/Documents/${HTML_DIR}/*.html\""
    fi
fi

# ===========================================================================
# 9. STEP 2 - dql.py codings
# ===========================================================================

if [ "$RUN_STEP_2" = true ]; then
    info "--- Step 2: dql.py (linguistic codings, merge into the table)"

    if [ ! -f "$DQL_REQUESTS" ]; then
        warn "no query file '$DQL_REQUESTS' in $PWD - skipping Step 2"
        finish 0
    fi

    # Step 1's outputs may have been gzipped by an earlier run.
    for f in "$CONLLU_FILE" "$PARSED_CSV"; do
        if [ ! -f "$f" ] && [ -f "$f.gz" ]; then
            info "uncompressing $f.gz"
            gunzip -f "$f.gz" || fail "could not uncompress $f.gz"
        fi
    done
    [ -f "$CONLLU_FILE" ] || fail "Step 2 needs $CONLLU_FILE from Step 1"
    [ -f "$PARSED_CSV"  ] || fail "Step 2 needs $PARSED_CSV from Step 1"

    CODED_CONLLU="${FILE_BASENAME}.coded.conllu"
    MERGED_CSV="${FILE_BASENAME}.parsed.coded.csv"
    LIGHT_CODED="${FILE_BASENAME}.light.coded.csv"

    if [ "$DRY_RUN" = true ]; then
        echo "DRY RUN: $PYCMD ${PYPATH}/dql.py --first_rule $DQL_REQUESTS $CONLLU_FILE > $CODED_CONLLU"
        echo "DRY RUN: $PYCMD ${PYPATH}/dql.py $CODE_HEAD_FLAG --merge $PARSED_CSV $CODED_CONLLU"
        finish 0
    fi

    $PYCMD "${PYPATH}/dql.py" --first_rule "$DQL_REQUESTS" "$CONLLU_FILE" > "$CODED_CONLLU" 2> "$ERR_TMP"
    rc=$?
    flush_err
    [ "$rc" -eq 0 ] || fail "dql.py (coding) exited with status $rc"

    n_in=$(count_sents "$CONLLU_FILE")
    n_out=$(count_sents "$CODED_CONLLU")
    if [ "$n_in" -ne "$n_out" ]; then
        warn "coded CoNLL-U has $n_out sentences, input had $n_in"
    else
        info "coded CoNLL-U: $n_out sentences"
    fi

    $PYCMD "${PYPATH}/dql.py" $CODE_HEAD_FLAG --merge "$PARSED_CSV" "$CODED_CONLLU" 2>&1 | tee_log
    rc=${PIPESTATUS[0]}
    [ "$rc" -eq 0 ] || fail "dql.py (merge) exited with status $rc"
    [ -f "$MERGED_CSV" ] || fail "merged table was not created: $MERGED_CSV"

    r_in=$(wc -l < "$PARSED_CSV" | tr -d ' ')
    r_out=$(wc -l < "$MERGED_CSV" | tr -d ' ')
    if [ "$r_in" -ne "$r_out" ]; then
        warn "merged table has $r_out rows, parsed table had $r_in"
    else
        info "merged table: $r_out rows"
    fi

    # --- light coded table -------------------------------------------------
    # Columns are selected BY NAME from the header, so the file cannot silently
    # come out empty when the CSV layout changes (which is what happened with
    # the previous positional 'cut -f1-4,6-10,12-15,20,28-').
    info "creating the light coded table"
    gawk -F'\t' -v OFS='\t' \
         -v want="$LIGHT_COLS" -v posre="$LIGHT_ROW_UPOS" -v tail_after="conll_10" '
    NR == 1 {
        for (i = 1; i <= NF; i++) { idx[$i] = i }
        if (!("pos" in idx)) { print "no column named pos" > "/dev/stderr"; exit 3 }
        posc = idx["pos"]
        n = split(want, w, ",")
        m = 0
        for (j = 1; j <= n; j++) {
            if (w[j] in idx) { sel[++m] = idx[w[j]] }
            else { printf("light table: no column named %s\n", w[j]) > "/dev/stderr"; missing++ }
        }
        if (tail_after in idx) { for (i = idx[tail_after] + 1; i <= NF; i++) sel[++m] = i }
        else { printf("light table: no column named %s, codings not appended\n", tail_after) > "/dev/stderr"; missing++ }
        ncols = m
    }
    NR == 1 || $posc ~ posre {
        out = ""
        for (k = 1; k <= ncols; k++) out = (k == 1 ? $(sel[k]) : out OFS $(sel[k]))
        gsub(/\([0-9]+>[0-9]+_[^)]*\)/, "", out)
        print out
        if (NR > 1) kept++
    }
    END {
        printf("light table: %d data rows kept, %d columns", kept + 0, ncols) > "/dev/stderr"
        if (missing) printf(", %d column name(s) not found", missing) > "/dev/stderr"
        printf("\n") > "/dev/stderr"
        if (kept + 0 == 0) exit 4
    }' "$MERGED_CSV" > "$LIGHT_CODED" 2> "$ERR_TMP"
    rc=$?
    flush_err
    case "$rc" in
        0) expect_file "$LIGHT_CODED" 2 "light coded table" ;;
        3) fail "light table: the merged CSV has no 'pos' column - check the layout" ;;
        4) warn "light coded table is EMPTY: no row matched $LIGHT_ROW_UPOS in column 'pos'" ;;
        *) fail "gawk failed with status $rc while building $LIGHT_CODED" ;;
    esac

    if [ "$RUN_GZIP" = true ]; then
        info "gzipping Step 2 inputs and intermediates"
        gzip -f "$PARSED_CSV" "$CONLLU_FILE" "$CODED_CONLLU" "$MERGED_CSV" \
            || warn "gzip reported an error"
    fi
fi

finish 0
