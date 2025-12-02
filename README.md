# Processing French CHILDES data

1. `childes.py` converts CHILDES CHAT files in a pipeline **CHAT -\> Tagger -\> Parser -\> CSV/CoNLL-U**.

2. `dql.py` performs multiple Grew queries on CoNLL-U files and allows the resulting codings (attribute-value pairs) to be merged into the CSV file.

A wrapper script `childes-pipeline.sh` contains an adaptable workflow for processing CHAT files with these scripts.

The scripts were developed for French input, but `childes.py` is sensitive to the language CODE in CHAT files. French, Italian and English CHILDES files were processed successfully. For other languges, please adapt:

- `childes.py`: add tokenisation rules to the function `tokenise()`. If you use the options --pos_utterance and --pos_output, their  arguments need to match the language-specific pos tags.
- `dql.py`: adapt the Grew query (syntactic coding) to language-specific UD annotation

For some languages, the folder _other-languages_  contains a usable wrapper script and coding query file.

## childes.py

This script converts CHILDES chat data to a one-word-per-line CSV format. It integrates tokenisation, optional POS tagging with TreeTagger, and dependency parsing via the UDPipe API into a single process.

### Features

  - **Integrated Pipeline:** Handles the entire conversion and annotation process from a CHAT file (`.cha` or `.cha.gz`) to tabular (CSV) and CoNLL-U formats.
  - **Parsing:** Calls the UDPipe API for dependency parsing. The model can be specified (e.g., `french-gsd`).
  - **Tagging:** Optionally uses TreeTagger for POS tagging before parsing. If not used, tokenised text is sent directly to the parser.
  - **Session-Aware Streaming:** Processes large files by handling them as a series of sessions (based on `@Begin` markers) and sending data to the parsing API in manageable chunks.
  - **Non-Destructive Conversion:** The original utterance from the CHAT file is preserved. Special markers (e.g., `[//]`, `(.)`, `xxx`) are retained in the raw utterance column, while a cleaned version is used for tagging and parsing.
  - **Outputs:**
      - A **full CSV** (`.parsed.csv`) containing all original columns plus the complete CoNLL-U annotation for each token.
      - A **light CSV** (`.light.csv`) containing a subset of columns, optionally filtered by the POS of the token (`--pos_output`).
      - An optional **CoNLL-U file** (`.conllu`) for use with other NLP tools.
      - Optional **HTML files** for browsing the parsed dependency trees in a web browser.

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
  - By default, the coding is added to the row corresponding to the **node** token (token `3` in the example).
  - `--code_head`: Use this flag to add the coding to the row of the **head** token instead (token `5` in the example). For example, when coding verb valencies, this will group the annotations in the row of the verbal head.


**Important:** If multiple rules in a query file match and write to the same attribute (e.g., `clitic`), their codings will be appended in the CoNLL-U metadata (e.g., `coding = clitic:acc(...); clitic:dat(...)`). When merging, only the **last** value will be written to the CSV column. To avoid this, use distinct attributes for potentially co-occurring phenomena (e.g., `acc_clitic` and `dat_clitic`).

## Sample query file

Query files contain one or more Grew patterns. Each pattern must be preceded by a comment line specifying the coding metadata to add upon a match.

```grew
% coding attribute=modal value=other node=MOD addlemma=V
pattern {
    MOD [lemma="pouvoir"] | [lemma="vouloir"];
    V [upos="VERB"];
    MOD -[xcomp]-> V;
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
    MOD [lemma=/(pouvoir|vouloir|devoir)/];
    V [upos="VERB"];
    MOD < V;
}
```

## Workflow for processing Childes files

Adapt the script `childes-pipeline.sh` to your needs.
It contains the commands for the steps depicted below.

![Childes processing workflow](https://github.com/user-attachments/assets/ee7950a7-f503-44f0-9211-7ab5af7f1a3f)

## Alternative parsing

_childes.py_ calls the UDPipe API.  This is recommended, because the API uses UDPipe2, with considerably accuracy compared to UDPipe1.

If you want to use UDPipe1 or any other parser locally, feel free to add the necessary function to _chides.py_.

### Local use of UDPipe

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