for i in parseme_*.conllu
do 
    echo "--------- $i"
    curl -F data=@$i  -F model=french -F tagger= -F parser= -F input=conllu\
        https://lindat.mff.cuni.cz/services/udpipe/api/process |\
    python3 -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['result'])" > udpiped-$i
done

echo "After parsing, concatenate the files in numerical order:"
echo "  > ls udpiped-parseme_*.conllu | sort -t_ -k2,2n | xargs cat > udpiped-parseme.conllu "
echo "Optionally, remove the splitted files:"
echo "  > rm udpiped-parseme_*.conllu

echo "========= Verifying line counts ========="

# Verify that each udpiped file has the same number of lines as the original
for i in parseme_*.conllu
do
    original_lines=$(wc -l < "$i")
    processed_lines=$(wc -l < "udpiped-$i")
    
    if [ "$original_lines" -eq "$processed_lines" ]; then
        echo "[OK] $i: $original_lines lines"
    else
        echo "[ERROR] $i: original=$original_lines, udpiped=$processed_lines"
    fi
done

