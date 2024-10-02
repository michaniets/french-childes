# Processing French CHILDES data

This script was created in project H2 of the DFG research unit [SILPAC](https://silpac.uni-mannheim.de) (FOR 5157)

## childes.py

Convert CHILDES chat data to csv where utterances are split into one word per line format.
The script was built to facilitate studies of vocabulary progression.

- Without -p option: Morphological annotation from '%mor' lines will be used, other annotation lines will be ignored.
- Option -p <parameters>: Selects a file with TreeTagger parameters.  Tokenises for TreeTagger and uses tagger annotation instead of the original '%mor' line.) All the annotation lines will be ignored.

(Looking for a better written script? J. Kodner has one, [here](https://github.com/jkodner05/method.git).)

Tested for some of the French CHILDES files (e.g. Paris).

Hints:

1. Concatenate *.cha files of one project
2. Run script on concatenated file.
3. Use -p <parameters> for TreeTagger analysis

Example: concatenated French CHILDES projects, tagged with parameters for spoken French

> childes.py -m VER --pos_utterance VER -p perceo-spoken-french-utf.par CHILDES-French-SILPAC.cha

With option to preserve the string with the tagged utterance:

> childes.py -m VER --pos_utterance VER --tagger_output -p perceo-spoken-french-utf.par CHILDES-French-SILPAC.cha


Bugs:

- Some utterances are not processed correctly because not all the specifics of the CHAT annotation were implemented.  Watch out for 'INDEX ERROR' messages while processing.


