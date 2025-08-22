#!/bin/bash

# run GREW   (partial code from childes-pipeline.sh)

FILE=${2%.*} # remove path and suffix, e.g. .cha
echo "Processing file: ${FILE}"

MYPATH="$HOME/git/french-childes"

if [ ! -f ${2} ]
then
    echo "Error: file not found: $2"
    exit 1
fi

check_success() {
  if [ $? -ne 0 ]; then
    echo "Error: Command failed at: $2" >&2
    exit 1
  fi
}

# run Grew queries for coding (requires grewpy backend, see https://grew.fr)
python3.11 ${MYPATH}/dql.py $1 ${FILE}.conllu --first_rule --coding_only > ${FILE}.coded.conllu
check_success "Run Grew queries for coding"

read -p "Do you want to run the merge step? (y/n): " answer
if [[ "$answer" == "y" ]]; then
  # merge codings with csv - add option --code_head to add coding to the head (default is 'node')
  python3.11 ${MYPATH}/dql.py --merge ${FILE}.cha.tagged.csv ${FILE}.coded.conllu 
  check_success "Merge codings with CSV"
else
  echo "Merge step skipped."
fi

echo "Pipeline completed successfully!"

 