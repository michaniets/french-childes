#!/bin/bash

# CHILDES pipeline: conversion, annotation, coding

FILE=$1

MYPATH="$HOME/git/french-childes"
SHELLCMD="bash"

check_success() {
  if [ $? -ne 0 ]; then
    echo "Error: Command failed at $1" >&2
    exit 1
  fi
}

# convert Childes CHAT format
${MYPATH}/childes.py -m VER --add_annotation --tagger_output --pos_utterance VER -p perceo-spoken-french-utf.par --conllu ${FILE}.cha
check_success "Convert Childes CHAT format"

# split conllu in chunks
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

cat udpiped-parseme_* > ${FILE}.conllu
check_success "Join parsed files"

rm parseme_* udpiped-parseme_*
check_success "Remove temporary files"

# run Grew queries for coding (requires grewpy backend, see https://grew.fr)
python3.11 ${MYPATH}/dql.py ${MYPATH}/dql.query ${FILE}.conllu --coding_only > ${FILE}.coded.conllu
check_success "Run Grew queries for coding"

# merge codings with csv
python3.11 ${MYPATH}/dql.py --merge ${FILE}.cha.tagged.csv ${FILE}.coded.conllu 
check_success "Merge codings with CSV"

echo "Pipeline completed successfully!"

# optional: extract relevant columns for easy verification
# grep -E '\(\d'  ${FILE}.cha.tagged.coded.csv|cut -f 1,15,23- > tmp.csv
