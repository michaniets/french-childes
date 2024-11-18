# CHILDES pipeline: conversion, annotation, coding

FILE=$1

PATH="$HOME/git/french-childes"

# convert Childes CHAT format
${PATH}/childes.py -m VER --add_annotation --tagger_output --pos_utterance VER -p perceo-spoken-french-utf.par --conllu ${FILE}.cha

# split conllu in chunks
${PATH}/conll-util.py -S 10000 parseme.conllu
# parse (loop through chunks)
${PATH}/call-udpipe.sh
# join and clean
cat udpiped-parseme_* > ${FILE}.conllu  # concatenate parsed files
rm parseme_* udpiped-parseme_*          # delete temporary files


# run Grew queries for coding (requires grewpy backend, see https://grew.fr)
python3.11 ${PATH}/dql.py ${PATH}/dql.query ${FILE}.conllu --coding_only > ${FILE}.coded.conllu

# merge codings with csv
python3.11 ${PATH}/dql.py --merge ${FILE}.cha.tagged.csv ${FILE}.coded.conllu 

# optional: extract relevant columns for easy verification
# grep -E '\(\d'  ${FILE}.cha.tagged.coded.csv|cut -f 1,15,23- > tmp.csv
