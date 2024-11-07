for i in parseme_*.conllu
do 
    echo "--------- $i"
    curl -F data=@$i  -F model=french -F tagger= -F parser= -F input=conllu\
        https://lindat.mff.cuni.cz/services/udpipe/api/process |\
    python3 -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['result'])" > udpiped-$i
done
