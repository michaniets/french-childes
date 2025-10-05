# Processing French CHILDES data

This script was created in project H2 of the DFG research unit [SILPAC](https://silpac.uni-mannheim.de) (FOR 5157)

## childes.py

Convert CHILDES chat data to csv where utterances are split into one word per line format.
The script was built to facilitate studies of vocabulary progression.

- Without -p option: Morphological annotation from '%mor' lines will be used, other annotation lines will be ignored.
- Option -p <parameters>: Selects a file with TreeTagger parameters.  Tokenises for TreeTagger and uses tagger annotation instead of the original '%mor' line.) All the annotation lines will be ignored.

(Looking for a better written script? J. Kodner has one, [here](https://github.com/jkodner05/method.git).)

Tested for some of the French CHILDES files (e.g. Paris).

### Changes

- Version 3.0: more object-oriented structure

  - Class-based: processing logic managed within a ChatProcessor class. This eliminated a number of global variables.

  - Non-destructive Data Handling: The script no longer silently discards information from the original CHAT files. The utterance cleaning process now extracts special markers (e.g., [//], (.)) before preparing the string for the tagger. Two new columns have been added to the CSV output:

  - new column 'utterance_raw': Contains the unmodified utterance from the chat file.

  - annotations: A semicolon-separated list of any special markers found in the utterance.

  - safe temporary file management: hardcoded files (like _tagthis.tmp_) have been replaced with Python's tempfile library.

- Version 2.0 published as a release

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
(This is a very shaky implementation and should be improved, but it works).

Rules are based on regular expressions that match the tagged string of the format:
: word_tag=lemma word_tag=lemma word_tag=lemma ...
They are applied during chat-to-csv conversion.

**Tipp**: If you have access to a dependency parser or UDPipe, don't use _--add_annotation_, but _--conllu_, then parse the output and use _dql.py_ for querying and coding the parsed corpus.

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

## Use UDPipe (or any other dependency parser)

UDPipe my fail

1. when CoNLL-U input is malformated. 

> bash check-conllu.sh parseme.conllu 

2. when uploaded files are too large. Split them, e.g. in chunks of 10000 graphs

> conll-util.py -S 10000 parseme.conllu

Process the chunnks and concatenate the output:

```{shell}
bash call-udpipe.sh                     # loop through splitted data
cat udpiped-parseme_* > udpiped.conllu  # concatenate parsed files
rm parseme_* udpiped-parseme_*          # delete temporary files
```

## Merge

There are several options for combining table (csv) with the parser output (conllu).

### Add CoNLL-U to CSV table

Combine (right join) the CoNLL-U columns and the table (CSV):

> python3 merge-csv-conllu.py childes.cha.tagged.csv udpiped.conllu out.conllu

### Add CSV columns to CoNLL-U

Don't combine the files, but copy the values of some CSV columns into the CoNLL-U file. This writes a feature=value list to column 10.  Specify the relevant columns with option --enrich_conllu, like so:

> python3 merge-csv-conllu.py --enrich_conllu speaker,age_days childes.cha.tagged.csv udpiped.conllu out.conllu

### Run coding query on ConLL-U and add codings

see below (dql.py)


# Dependency query language (dql.py)

This script uses the Grew query language and Python library [Link](https://grew.fr).
It applies Grew queries to a corpus, adds coding strings to meta data (and optionally nodes).

## Query CoNLL-U files

- Default is 'search': Prints the complete corpus with added codings
- Option --coding_only: prints only graphs matching the query (with added codings)

Use _--coding_only_ if you if you want to merge the result back into the table.

```{shell}
dql.py <query file> <conllu file> [--coding_only] [> <output file>]
```

More than one Grew query can be concatenated in the query file.  Each query starts with a comment line containing the coding specifications (format: attribute=value).

The *.query files contain examples of Grew queries with coding instructions. If no *.query file is included, look at the example below. It produces two codings. If the patterns match the same graph, codings are appended, e.g. *modal:other(7>9_bouger); modal:savoir(3>7_vouloir)*

Note that if more than one coding matches for a given attribute, codings are **appended**.
For example we get two codings for the attribute 'code_modal' from two matching rules:

```{conll}
# coding = code_modal:xcomp(9>10_faire); code_modal:noRule(9>0); ...
```

When you build your query file, you may want to debug the individual query blocks using the Grew online query tool [here](https://universal.grew.fr/?corpus=UD_French-GSD@2.14).
The discussion of Grew's issues is another useful resource, on [GitHub](https://github.com/grew-nlp/grew/issues/).
Some expression may require a recent version of Grew. Perl-style regular expressions work with Grew 1.16 and grewpy backend 0.5.4.

As of version >0.2 *--print_text* outputs the sentences without their graphs, with optional markup of the matches.

```{shell}
dql.py --coding_only --print_text --mark_coding my.query mycorpus.conllu
```


## Merge CoNLL-U codings with CSV

Example: The following command takes the CoNLL-U file as input and merges it with the CSV referenced by _--merge_. The output will be written to childes-all.cha.tagged.coded.csv

```{shell}
dql.py --merge childes-all.cha.tagged.csv childes-all.coded.conllu [--code_head]
```

The default is merging the coding with the row of the **node** token.

- If your coding produced 'clitic:obj(3>5_lemma)', the script will add value 'obj' to the column 'clitic' in the row matching the ID of node '3'.
- If you want to add that coding to the head '5', use '--code_head'

**Important:** that if more than one coding is present for a given attribute in the CoNLL-U meta data (e.g. 'code_modal' above), _merge_ will copy only the last value to the CSV file (e.g. 'noRule...').  Good practice is to use separate attributes if you expect competing values within the same sentence.  For example, instead of attribute 'clitics' with values 'acc', 'dat' (which can co-occur in the same sentence), code for separate attributes 'acc_clitic', 'dat_clitic' etc.

## Sample query file

```{grew}
% coding attribute=modal value=other node=MOD addlemma=V
pattern {
    MOD [lemma="pouvoir"] | [lemma="vouloir"];
    V [upos="VERB"];
    MOD -[re"xcomp"]-> V;
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
% coding attribute=mod_linear value=inf node=MOD addlemma=V
pattern {
    MOD [lemma=/(pouvoir|vouloir|devoir)/];   % requires Grew 1.16/grewpy 0.5.4
    V [upos="VERB"];
    MOD < V;
}
```

## Workflow for processing Childes files

Adapt the script _childes-pipeline.sh_ to your installation. It lists the commands for most of the steps depicted below.

![Childes processing workflow](https://github.com/user-attachments/assets/ee7950a7-f503-44f0-9211-7ab5af7f1a3f)
