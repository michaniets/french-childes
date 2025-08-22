#!/bin/bash

# CHILDES pipeline: conversion, annotation, coding

FILE=${1%.*} # remove path and suffix, e.g. .cha
echo "Processing file: ${FILE}"

#MYPATH="$HOME/git/french-childes"
MYPATH="."

if [ ! -f ${1} ]
then
    echo "Error: file not found: $1"
    exit 1
fi

check_success() {
  if [ $? -ne 0 ]; then
    echo "Error: Command failed at: $1" >&2
    exit 1
  fi
}

if command -v tree-tagger >/dev/null 2>&1; then
    echo :
else
    echo "tree-tagger is not available or not executable"
    exit 1
fi


# convert Childes CHAT format
${MYPATH}/childes.py -m VER --add_annotation --tagger_output --pos_utterance VER -p perceo-spoken-french-utf.par --conllu ${FILE}.cha
check_success "Convert Childes CHAT format"

if [ ! -f parseme.conllu ]
then
    echo "Error: parseme.conllu not found.  This may be because your input file was in a different folder. Move it here and re-run the script."
    exit 1
fi

# split conllu in chunks
echo "Splitting CoNLL-U file into chunks..."
${MYPATH}/conll-util.py -S 10000 parseme.conllu
check_success "Split CoNLL-U in chunks"

# parse (loop through chunks)
#${MYPATH}/call-udpipe.sh
for i in parseme_*.conllu
do 
    echo "--------- $i"
    curl -F data=@$i  -F model=french -F tagger= -F parser= -F input=conllu\
        https://lindat.mff.cuni.cz/services/udpipe/api/process |\
    python3 -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['result'])" > udpiped-$i
done

## simple concat
# cat udpiped-parseme_* > ${FILE}.conllu
## concat respecting numerical order
ls udpiped-parseme_*.conllu | sort -t_ -k2,2n | xargs cat > ${FILE}.conllu
check_success "Join parsed files"

rm parseme_* udpiped-parseme_*
check_success "Remove temporary files"

# run Grew queries for coding (requires grewpy backend, see https://grew.fr)
python3.11 ${MYPATH}/dql.py ${MYPATH}/dql.query ${FILE}.conllu --coding_only > ${FILE}.coded.conllu
check_success "Run Grew queries for coding"

# merge codings with csv - add option --code_head to add coding to the head (default is 'node')
python3.11 ${MYPATH}/dql.py --merge ${FILE}.cha.tagged.csv ${FILE}.coded.conllu 
check_success "Merge codings with CSV"

echo "Pipeline completed successfully!"

# optional: extract relevant columns for easy verification
# grep -E '\(\d'  ${FILE}.cha.tagged.coded.csv|cut -f 1,15,23- > tmp.csv


### Optional: extract column header and verb rows
# run-grew.sh sources/Geneva.cha
# -- extract verbs from result
# head -1 sources/Geneva.cha.tagged.coded.csv > Geneva-coded.csv
# gawk  -F'\t' '$12 ~ /VER/' sources/Geneva.cha.tagged.coded.csv >> Geneva-coded.csv
