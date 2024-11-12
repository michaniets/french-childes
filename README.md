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

Example: concatenated French CHILDES projects, tagged with parameters for spoken French (from the PERCEO project, see [Helmut Schmid's TreeTagger website](https://www.cis.uni-muenchen.de/~schmid/tools/TreeTagger/))

> childes.py -m VER --pos_utterance VER -p perceo-spoken-french-utf.par childes-all.cha

With option to preserve the string with the tagged utterance:

> childes.py -m VER --pos_utterance VER --tagger_output -p perceo-spoken-french-utf.par childes-all.cha

With option --add_annotation to apply the annotation rules specified in _tag_analyser.py_ 

> childes.py -m VER --add_annotation --tagger_output --pos_utterance VER -p perceo-spoken-french-utf.par childes-all.cha


### Annotation (-a --add_annotation)

Rules for automatic annotation based on the tagged utterance can be added to _tag_analyser.py_.
(This is a very shakey implementation and should be improved, but it works).

Rules are based on regular expressions that match the tagged string of the format:
: word_tag=lemma word_tag=lemma word_tag=lemma ...
They are applied during chat-to-csv conversion.

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

## Use UDPipe (or other parser)

UDPipe fails when uploaded files are too large. Split them:

> conll-util.py -S 10000 parseme.conllu

Process the splitted files in a loop and concatenate the output:

```{shell}
bash call-udpipe.sh                     # loop through splitted data
cat udpiped-parseme_* > udpiped.conllu  # concatenate parsed files
rm parseme_* udpiped-parseme_*          # delete temporary files
```

## Merge

### Add CoNLL-U to CSV table

Combine (right join) the CoNLL-U columns and the table (CSV):

> python3 merge-csv-conllu.py childes.cha.tagged.csv udpiped.conllu out.conllu

### Add CSV columns to CoNLL-U

Don't combine the files, but copy the values of some CSV columns into the CoNLL-U file. This writes a feature=value list to column 10.  Specify the relevant columns with option --enrich_conllu, like so:

> python3 merge-csv-conllu.py --enrich_conllu speaker,age_days childes.cha.tagged.csv udpiped.conllu out.conllu

# Work in progress

## dql.py

Applies Grew queries to a corpus, adds coding strings to meta data (and optionally nodes).

- Default: Prints the complete corpus with added codings
- Option --coding_only: prints only graphs matching the query (with coding)

```{shell}
dql.py dql.query <query file> <input file> [--code_node] [--coding_only] [> <output file>]
```

More than one Grew query can be concatenated in the query file.  Each query starts with a comment line containing the coding specifications (format: attribute=value).

The example below combines two query patterns and produces two codings. If the patterns match the same graph, codings are appended, e.g. *modal:other(7>9_bouger); modal:savoir(3>7_vouloir)*

```{grew}
% coding attribute=modal value=other node=MOD addlemma=V
pattern {
    MOD [lemma="pouvoir"] | [lemma="vouloir"];
    V [upos="VERB"];
    MOD -[re"xcomp"]-> V;  % test comment
}
without {
    MOD [lemma="savoir"]
}
% coding attribute=modal value=savoir node=MOD addlemma=V
pattern {
    MOD [lemma="savoir"];
    V [upos="VERB"];
    MOD -[re".*"]-> V;
}
```