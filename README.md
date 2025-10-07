# Processing French CHILDES data

These scripts were created in project H2 of the DFG research unit [SILPAC](https://silpac.uni-mannheim.de) (FOR 5157).

`childes.py` converts CHILDES CHAT files in a pipeline **CHAT -> Tagger -> Parser -> CSV/CoNLL-U**

`dql.py` performs multiple GREW queries on CoNLL-U files and allow to merge the resulting codings (attribute-value pairs) into the CSV file.

## childes.py

Convert CHILDES chat data to csv where utterances are split into one word per line format.
The script was built to facilitate the quantitative exploration of the data, such as studies of vocabulary progression.

(Looking for an alternative script? J. Kodner has written one, [here](https://github.com/jkodner05/method.git).)

- Option -p <parameters>: Selects a file with TreeTagger parameters.  Tokenises for TreeTagger and uses tagger annotation instead of the original '%mor' line.) All the annotation lines will be ignored.
  - TreeTagger parameters are freely available for many languages.
- Without -p option: Morphological annotation from '%mor' lines will be used, other annotation lines will be ignored.

Tested for some of the French CHILDES files (e.g. Paris) as well as Italian and German.
Special tokenisation and tagger correction rules are applied for French.  Further language-specific rules can be added if needed: the scripts reacts to the language specified in the @ID line of the chat file (see functions tokenise() and correct_tagger_output()).

### History
- Version 4.0: complete revision of the structure, building on intermediate version 3.0

  - UDPipe API call integrated in childes.py with debug function for parser errors
  - --html_dir: html export of parsed corpus, with URL columns in CSV file
  - more efficient CHAT file streaming (line-by-line parser)
  - session-based parsing allows for processing concatenated projects
  - input file can be gzipped (*.gz)
  - output two CSV versions:
    - full: including CoNLL-U annotation
    - work: without CoNLL-U annotation, rows optionally filtered by --pos_output
  - updated wrapper script childes-pipeline.sh
  - abandoned:
    - processing of %mor annotation if tagger is not used
    - annotation based on the analysis of the tagged utterance

- Version 3.0: (unpublished intermediate version)

  - Class-based: processing logic managed within a ChatProcessor class. This eliminated a number of global variables.

  - Non-destructive Data Handling: The script no longer silently discards information from the original CHAT files. The utterance cleaning process now extracts special markers (e.g., [//], (.)) before preparing the string for the tagger. Two new columns have been added to the CSV output:
  - column 'utterance' now contains the unmodified utterance from the chat file
  - new options can add cleaned and tagged versions of utterance
  - safe temporary file management: hardcoded files (like _tagthis.tmp_) have been replaced with Python's tempfile library.
  - option --write_conllu must be used to export the parsed CoNLL-U file


- Version 2.0 published as a release

### How to use

Adapt the wrapper shell script to your needs and run with 

> childes-pipeline.sh <chatfile[.gz]>

or run manually based on the examples below.

### Examples:

Minimal: using a sample of concatenated French CHILDES projects

> python3 childes.py french-sample.cha --html_dir chifr --server_url "https://141.58.164.21/chifr" --pos_utterance 'VER|AUX'

Tagged with parameters for spoken French (from the PERCEO project, see [Helmut Schmid's TreeTagger website](https://www.cis.uni-muenchen.de/~schmid/tools/TreeTagger/)).
`--pos_utterance <regex>` prints the utterance _only_ in matching rows with verbs.

> python3 childes.py french-sample.cha --pos_utterance 'VER|AUX' -p perceo-spoken-french-utf.par

Same, with option to preserve the string with the tagged utterance:

> python3 childes.py french-sample.cha --pos_utterance 'VER|AUX' -p perceo-spoken-french-utf.par --utt_tagged

Tagging and dependency parsing with UDPipe. `--api_model french` will use UDPipe's default French model. Any specific model name can be given (see UDPipe documentation).

> python3 childes.py french-sample.cha --pos_utterance 'VER|AUX' -p perceo-spoken-french-utf.par --api_model french

As of version 3.0, the script handles temporary file internally.  Option `--write_conllu` will output a CoNLL-U version of the file.

## Dependency query language (dql.py)

This script uses the Grew query language and Python library [Link](https://grew.fr).
It applies Grew queries to a corpus, adds coding strings to meta data (and optionally nodes).

### Query CoNLL-U files

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


### Merge CoNLL-U codings with CSV

Example: The following command takes the CoNLL-U file as input and merges the codings with the CSV referenced by _--merge_. The output will be written to _*.coded.csv_. The attribute-value pair of the coding will become column header and column value.

```{shell}
dql.py --merge childes-all.cha.tagged.csv childes-all.coded.conllu [--code_head]
```

The default is merging the coding with the row of the **node** token.

- If your coding produced 'clitic:obj(3>5_lemma)', the script will add value 'obj' to the column 'clitic' in the row matching the ID of node '3'.
- If you want to add that coding to the head '5', use '--code_head'

**Important:** If more than one coding is present for a given attribute in the CoNLL-U meta data (e.g. 'code_modal' above), _merge_ will copy only the last value to the CSV file (e.g. 'noRule...').  Good practice is to use separate attributes if you expect competing values within the same sentence.  For example, instead of attribute 'clitics' with values 'acc', 'dat' (which can co-occur in the same sentence), code for separate attributes 'acc_clitic', 'dat_clitic' etc.

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
