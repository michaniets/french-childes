This repository was previously hosted at [https://github.com/french-childes](https://github.com/french-childes). The pre-transfer release
(version 3.1) is archived at https://doi.org/10.5281/zenodo.22112353.


# Processing French CHILDES data

1. `childes.py` converts CHILDES CHAT files in a pipeline **CHAT -\> Tagger -\> Parser -\> CSV/CoNLL-U**.

2. `dql.py` performs multiple Grew queries on CoNLL-U files and allows the resulting codings (attribute-value pairs) to be merged into the CSV file.

A wrapper script `childes-pipeline.sh` contains an adaptable workflow for processing CHAT files with these scripts.  When the path and filename variables are adapted to your installation, the command

> childes-pipeline.sh test-snippet.cha

will produce `test-snippet.parsed.coded.csv` (and other optional output files), a table with one row per token, and columns for meta annatation (from the CHAT file), pos tagging, dependency parsing and syntactic coding.

The scripts were developed for French input, but `childes.py` is sensitive to the language CODE in CHAT files. French, Italian, German and English CHILDES files were processed successfully. For other languges, please adapt:

- `childes.py`: add tokenisation rules to the function `tokenise()`. If you use the options --pos_utterance and --pos_output, their  arguments need to match the language-specific pos tags.
- `dql.py`: adapt the Grew query (syntactic coding) to language-specific UD annotation

For some languages, the folder _other-languages_  contains a usable wrapper script and coding query file.

## Citation

If you use these scripts in your research, please cite them. Citation metadata is
provided in [`CITATION.cff`](CITATION.cff); GitHub renders it as a *Cite this
repository* button in the sidebar.

> Stein, Achim (2026). *french-childes: a pipeline for tagging, parsing and syntactic
> coding of CHILDES data* (Version 3.0) [Computer software].
> https://github.com/michaniets/french-childes

```bibtex
@software{stein_french_childes,
  author  = {Stein, Achim},
  title   = {french-childes: a pipeline for tagging, parsing and syntactic coding of CHILDES data},
  year    = {2026},
  version = {3.0},
  license = {GPL-3.0},
  url     = {https://github.com/michaniets/french-childes}
}
```

Please also cite the resources this pipeline builds on: the CHILDES/TalkBank corpora
you process, [UDPipe](https://lindat.mff.cuni.cz/services/udpipe/),
[Grew](https://grew.fr/) and, if used, TreeTagger.

## childes.py

This script converts CHILDES chat data to a one-word-per-line CSV format. It integrates tokenisation, optional POS tagging with TreeTagger, and dependency parsing via the UDPipe API into a single process.

### Features

  - **Integrated Pipeline:** Handles the entire conversion and annotation process from a CHAT file (`.cha` or `.cha.gz`) to tabular (CSV) and CoNLL-U formats.
  - **Parsing:** Calls the UDPipe API for dependency parsing. The model can be specified (e.g., `french-gsd`).
  - **Graph rewriting:** Optionally uses Grew for modifying or correcting CoNLL-U annotations.
  - **Tagging:** Optionally uses TreeTagger for POS tagging before parsing. If TreeTagger is not used, tokenisation is normally left to UDPipe: cleaned but untokenised utterance text is sent, and UDPipe performs its own UD-compliant tokenisation (including multiword tokens, e.g. English `gonna` -> `gon`+`na`). The exception is French, where contractions must stay fused - see `--fuse_contractions`.
  - **Session-Aware Streaming:** Processes large files by handling them as a series of sessions (based on `@Begin` markers) and sending data to the parsing API in manageable chunks.
  - **Non-Destructive Conversion:** The original utterance from the CHAT file is preserved. Special markers (e.g., `[//]`, `(.)`, `xxx`) are retained in the raw utterance column, while a cleaned version is used for tagging and parsing.
  - **POS-based filtering:** `--pos_output`/`--pos_utterance` match the parser's universal POS (UPOS) by default when `--api_model` is used, rather than the tagger's own language/model-specific tag - so the same regex (e.g. `VERB`) works across corpora and tagger models. Use `--use_tagger_pos` to restore matching against the tagger's tag. `--pos_utterance` defaults to `--pos_output`'s value when not given explicitly.
  - **Outputs:**
      - A **full CSV** (`.parsed.csv`) containing all original columns plus the complete CoNLL-U annotation for each token.
      - A **light CSV** (`.light.csv`) containing a subset of columns, optionally filtered by the POS of the token (`--pos_output`).
      - An optional **CoNLL-U file** (`.conllu`) for use with other NLP tools.
      - Optional **HTML files** for browsing the parsed dependency trees in a web browser.

### Recent changes (v5.8)

  - **`--fuse_contractions {auto,yes,no}` (default `auto`) - important for French.** Letting UDPipe tokenise French silently destroys the `obj`/`obl:arg` distinction. UDPipe splits `du`/`des`/`au`/`aux` into `de`(ADP)+`le`(DET); the noun then receives `obl:arg` rather than `obj`, because in UD_French-GSD the split representation and `obj` are near-disjoint: a split `du`/`des` has an `obj` head noun in 81 of 6795 cases (1.2%), an unsplit one in 680 of 1675 (41%). Once the tokeniser has split, the parser has effectively no evidence for `obj`. Checked against `french-gsd`, `-sequoia`, `-partut` and `-spoken`: none analyses a partitive direct object (_Max mange du sucre_) as `obj`, and `-gsd` splits even subjects (_des enfants jouent_ → `obl:mod` instead of `nsubj`).
    With `auto`, French utterances are therefore tokenised by `childes.py` (contractions kept fused) and submitted with fixed tokens, which restores `obj`/`nsubj`/`nmod` correctly - including the genuine PP case (_le goût du sucre_ → `nmod`). `yes`/`no` force the behaviour for any language. Other languages are unaffected: the criterion is that the tokeniser's decision be context-dependent _and_ entail a change of deprel, which is not the case for e.g. English `gonna` → `gon`+`na`. German contractions are the easy case (Grünewald & Friedrich, [UDW 2020](https://universaldependencies.org/udw20/papers/2020.udw2020-1.11.pdf)); Italian and Spanish are untested.
    The fused single-token analysis of `du`/`des` deviates from UD only in the contraction/genitive case - and `deprel` identifies that case unambiguously (`nmod`/`obl` ⇒ expand to `de`+`le`; `obj`/`nsubj` ⇒ leave as DET), so any desired surface standard can be derived afterwards with a Grew rewrite rule. The converse does not hold, which is why `deprel` is fixed first.
  - A file mixing languages across `@PID` sessions is handled: whichever input builders have content are used, and the parsed results are combined.

### Recent changes (v5.7)

  - **Tokenisation without a tagger:** when `--api_model` is used without `-p/--parameters`, `childes.py` no longer pre-splits words with its own (TreeTagger-oriented) rules before sending them to UDPipe (but see `--fuse_contractions` under v5.8, which restores fused tokenisation for French). It now sends cleaned, untokenised utterance text and lets UDPipe tokenise it (`tokenizer=presegmented`), so tokens follow the Universal Dependencies guidelines for that language, including multiword tokens. Utterances that clean down to nothing (pure event/pause coding, e.g. `(5.) &=laugh`) are dropped before submission rather than sent as blank lines, which would otherwise desynchronise every following utterance's metadata. This does not affect runs that use TreeTagger (`-p`).
  - **CoNLL-U header metadata:** sentence headers now also carry `# child = <name>` (unabbreviated) and `# project = <name>`, alongside the existing `# item_id`, `# speaker`, `# age`, `# text`, `# chat`.
  - **`# text` vs `# chat`:** `# text` is now guaranteed to reflect the actual tokens (transcription noise such as timed pauses, intonation arrows, and event codes like `&=laugh` is stripped from it, matching what is tagged/parsed); `# chat` keeps the original CHAT-coded line unchanged.
  - **CHAT-cleaning fixes:** `&=word` event/vocalisation codes (e.g. `&=laughs`, `&=noise`) are now fully removed instead of leaving a stray `&` plus a spurious real-looking word in the tagged/parsed output.
  - Bug fix: a metadata-desync in `run_treetagger()`/`tagged2conllu()` (used with `-p` together with `--api_model`) that could attach one session's `# speaker`/`# age`/`# text`/`# chat` to a different session's tokens whenever utterance numbers repeated across `@PID` boundaries.
  - **`--tag_ud_tokens`** (requires both `-p/--parameters` and `--api_model`): reverses the default order of the two. Normally, when both are given, the tagger tokenises first and the parser respects those exact tokens; `pos`/`lemma` are the tagger's tag/lemma. With `--tag_ud_tokens`, the parser tokenises first (UD-compliant, as in the `--api_model`-only case above), and the tagger runs _afterward_ on those tokens purely to add a **second**, independent tag/lemma in new `tagger_pos`/`tagger_lemma` columns. `pos`/`lemma` then hold the parser's UPOS/lemma instead of the tagger's - i.e. what `pos`/`lemma` mean depends on which of the two tokenised first, not on which flags are present as such. Off by default, so existing workflows are unaffected.

### How to use

The recommended method is to adapt the wrapper script `childes-pipeline.sh` to your local paths and run it with the CHAT file as an argument:

```sh
./childes-pipeline.sh [-1|-2] <chatfile.cha[.gz]>
```

Use the options `-1`and `-2` if you want to execute conversion / annotation (`childes.py`) and coding queries (`dql.py`) separately. Or run the Python scripts manually.

### Examples:

Process a sample of French CHILDES projects, generating parsed output and HTML files. The utterance text will only be included in rows where the token is a verb or auxiliary.

```sh
python3 childes.py french-sample.cha \
    --api_model french \
    --html_dir html_output --server_url "http://your.server/html_output" \
    --write_conllu \
    --pos_utterance 'VER|AUX' \
    --pos_output 'VER|AUX|NOUN|ADJ'
```

The command above will generate:

  - `french-sample.cha.parsed.csv`
  - `french-sample.cha.light.csv` (containing only rows with VER, AUX, NOUN, ADJ)
  - `french-sample.cha.conllu`
  - HTML files inside the `html_output/` directory.

## Dependency query language (dql.py)

This script uses the Grew query language to apply syntactic queries to a CoNLL-U corpus. It has two main functions: searching/coding a CoNLL-U file and merging the results back into a CSV table.

### 1\. Query CoNLL-U files

This mode reads a CoNLL-U file, applies one or more Grew queries, and prints the resulting CoNLL-U graphs with new `coding` metadata added to matching sentences.

```sh
python3 dql.py --first_rule my_queries.query my_corpus.conllu > my_corpus.coded.conllu
```
  - `--first_rule`: matches pattern only if THIS attribute has not been coded for THIS verb.  Thus, for a given verb in the structure, only the first subject will be coded. Any further "subjects" will be ignored.  **Important**: The use of this option mimicks the behaviour of _CorpusSearch_ coding. Accordingly, the patterns in the request file need to be ordered by decreasing specificity. The use of `--first_rule` is **recommended** to avoid multiplication of codings.
  - `--coding_only`: Prints only the sentences (graphs) that matched at least one query.
  - `--print_text`: Outputs plain sentences instead of CoNLL-U graphs. Can be combined with `--mark_coding` to wrap matched nodes in `<h>` tags.

### 2\. Merge CoNLL-U codings with CSV

This mode takes a CoNLL-U file that has been annotated with `coding` metadata and merges this information into a corresponding CSV file. The script aligns data using the `utt_id` and word number.

```sh
python3 dql.py --merge childes-all.cha.tagged.csv childes-all.coded.conllu
```

This command reads `childes-all.coded.conllu`, extracts the codings, and writes a new CSV file named `childes-all.cha.tagged.coded.csv`.

  - For a coding string like `clitic:obj(3>5_lemma)`, the script adds the value `obj(3>5_lemma)` to a column named `clitic`.
  - By default, the coding is added to the row corresponding to the **node**, specified by e.g. `node=V` in the coding instruction (token `3` in the example).
  - `--code_head`: Use this flag to add the coding to the row of the **head** token instead (token `5` in the example). For example, when coding verb valencies, this will group the annotations in the row of the verbal head.


**Important:** If multiple rules in a query file match and write to the same attribute (e.g., `clitic`), their codings will be appended in the CoNLL-U metadata (e.g., `coding = clitic:acc(...); clitic:dat(...)`). When merging, only the **last** value will be written to the CSV column. To avoid this, use distinct attributes for potentially co-occurring phenomena (e.g., `acc_clitic` and `dat_clitic`).

## Sample query file

Query files contain one or more Grew patterns. Each pattern must be preceded by a comment line specifying the coding metadata to add upon a match.

```grew
% coding attribute=modal value=other node=V addlemma=MOD
pattern {
    MOD [lemma="pouvoir"] | [lemma="vouloir"];
    V [upos="VERB"];
    MOD -[xcomp]-> V;
}
without {
    MOD [lemma="savoir"]
}

% coding attribute=modal value=savoir node=V addlemma=MOD
pattern {
    MOD [lemma="savoir"];
    V [upos="VERB"];
    MOD -[re".*"]-> V;
}

% coding attribute=mod_linear value=inf node=V addlemma=MOD
pattern {
    MOD [lemma=/(pouvoir|vouloir|devoir)/];
    V [upos="VERB"];
    MOD < V;
}
```

## Sample rewrite file

A function for correcting systematic errors in the Dependency annotation can be called by adding to the flag --write_conllu the flag --rewrite <GRS file>. `childes.py` will process the rules internally before writing the CoNLL-U output.

For French, a sample Grew rewrite file (*.grs) and a minimal lexicon (*.tsv) are part of this distribution. They are standard Grew files and can also be used with a stand-alone installatino of `grew`.

A GRS file is a request (query) pattern block, an optional `without` block, and a command block. The command block contains the rules for rewriting the graph if the pattern is matched. For more information, see [https://grew.fr/doc/rule/](https://grew.fr/doc/rule/).

## Workflow for processing Childes files

Adapt the script `childes-pipeline.sh` to your needs.
It contains the commands for the steps depicted below.

![Childes processing workflow](https://github.com/user-attachments/assets/ee7950a7-f503-44f0-9211-7ab5af7f1a3f)

## Alternative parsing

_childes.py_ calls the UDPipe API.  This is recommended, because the API uses UDPipe2, with considerably accuracy compared to UDPipe1.

If you want to use UDPipe1 or any other parser locally, feel free to add the necessary function to _chides.py_.

### Local use of UDPipe

(This refers to UDPipe version 1.  The Lindat API provides version 2, with higher accuracy.)

1. Install Python bindings
> pip3 install ufal.udpipe

2. Go to the [UDPipe Models Repository](https://lindat.mff.cuni.cz/repository/items/41f05304-629f-4313-b9cf-9eeb0a2ca7c6). Download any model, e.g. the generic French model: french-gsd-ud-2.5-191206.udpipe (25MB)

3. Save the following code, e.g. as eval_udpipe1.py 

```{Python}
import sys
from ufal.udpipe import Model, Pipeline, ProcessingError

def parse_local(input_conllu, output_conllu, model_path):
    # 1. Load the model
    print(f"Loading model: {model_path}...")
    model = Model.load(model_path)
    if not model:
        sys.stderr.write(f"Cannot load model from file '{model_path}'\n")
        sys.exit(1)
    print("Model loaded successfully.")

    # 2. Setup pipeline
    # input="conllu" (assumes already tokenized), output="conllu"
    # We specifically want tagging and parsing.
    pipeline = Pipeline(model, "conllu", Pipeline.DEFAULT, Pipeline.DEFAULT, "conllu")

    # 3. Read input
    with open(input_conllu, 'r', encoding='utf-8') as f:
        text = f.read()

    # 4. Process
    print(f"Processing {input_conllu}...")
    error = ProcessingError()
    processed = pipeline.process(text, error)

    if error.occurred():
        sys.stderr.write("An error occurred when running UDPipe: ")
        sys.stderr.write(error.message)
        sys.stderr.write("\n")
        sys.exit(1)

    # 5. Write output
    with open(output_conllu, 'w', encoding='utf-8') as f:
        f.write(processed)
    print(f"Output saved to {output_conllu}")

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python3 eval_udpipe1.py <input.conllu> <output.conllu> <model_file>")
        sys.exit(1)
    
    parse_local(sys.argv[1], sys.argv[2], sys.argv[3])
```

4. Run the script on your non-annotated CoNLL-U file

(It should also work with pre-annotated CoNLL-U; previous annotation will probably be overwritten)

> python3 eval_udpipe1.py sample_input.conllu sample_output_local.conllu french-gsd-ud-2.5-191206.udpipe
