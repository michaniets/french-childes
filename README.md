# Processing French CHILDES data

This script was created in project H2 of the DFG research unit [SILPAC](https://silpac.uni-mannheim.de) (FOR 5157)

## childes.py

Convert CHILDES chat data to csv where utterances are split into one word per line format.
The script was built to facilitate studies of vocabulary progression.

- Without -p option: Morphological annotation from '%mor' lines will be used, other annotation lines will be ignored.
- Option -p <parameters>: Selects a file with TreeTagger parameters.  Tokenises for TreeTagger and uses tagger annotation instead of the original '%mor' line.) All the annotation lines will be ignored.

(Looking for a better written script? J. Kodner has one, [here](https://github.com/jkodner05/method.git).)

Tested for some of the French CHILDES files (e.g. Paris).

### How to use

1. Concatenate *.cha files of one project
2. Run script on concatenated file.
3. Use -p <parameters> for TreeTagger analysis

Example: concatenated French CHILDES projects, tagged with parameters for spoken French

> childes.py -m VER --pos_utterance VER -p perceo-spoken-french-utf.par childes-all.cha

With option to preserve the string with the tagged utterance:

> childes.py -m VER --pos_utterance VER --tagger_output -p perceo-spoken-french-utf.par childes-all.cha

With option --add_annotation to apply the annotation rules specified in _tag_analyser.py_ 

> childes.py -m VER --add_annotation --tagger_output --pos_utterance VER -p perceo-spoken-french-utf.par childes-all.cha

### Bugs

- Some utterances are not processed correctly because not all the specifics of the CHAT annotation were implemented.  Watch out for 'INDEX ERROR' messages while processing.

### Dependency parsing

Work in progress, version >= 1.8

Options:

- **--ud_pipe <model>** calls the UDPipe API for each single utterance during processing and appends CoNLL-U columns directly to the csv table.  This is very slow and should only be done for small texts.  For example **--udpipe french** selects UDPipe's default French model.  Any UDPipe model name can be given (see UDPipe documentation).

- **--conllu** creates parallel output in the file _parseme.conllu_.  Run the parser on this file, then optionally merge the output with the csv table.  To run UDPipe on this file, specify 'conllu' as input format, like so:

> curl -F data=@parseme.conllu  -F model=french -F tagger= -F parser= -F input=conllu https://lindat.mff.cuni.cz/services/udpipe/api/process | python -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['result'])" > udpipe.conllu

Example:
> childes.py -m VER --add_annotation --tagger_output --pos_utterance VER -p perceo-spoken-french-utf.par --conllu childes-all.cha