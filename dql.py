#!/usr/local/bin/python3
# -*- coding: utf-8 -*-

__author__ = "Anonymous"
__version__ = "1.4"
__status__ = "27.1.2026"
__license__ = "GPL"

import sys
import re
import argparse
import csv
import os
import tempfile
from typing import Dict, List, Iterable, Tuple, Optional
from grewpy import Corpus, Request, CorpusDraft, Graph

# --------------------------
# Helpers: CoNLL-U streaming
# --------------------------

def iter_conllu_sentences(path: str) -> Iterable[str]:
    """Yield one CoNLL-U sentence (including its #meta) at a time."""
    buf = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                buf.append(line)
            else:
                if buf:
                    yield "".join(buf)
                    buf = []
        # file without trailing newline
        if buf:
            yield "".join(buf)

def write_chunk(sentences: Iterable[str], out_path: str, max_count: int) -> int:
    """Write up to max_count sentences from iterator into out_path. Return how many written."""
    n = 0
    with open(out_path, 'w', encoding='utf-8') as w:
        for s in sentences:
            w.write(s)
            w.write("\n")  # CoNLL-U sentence separator
            n += 1
            if n >= max_count:
                break
    return n

# --------------------------
# Query + coding parsing
# --------------------------

def read_grew_query(query_file):
    with open(query_file, 'r', encoding='utf-8') as f:
        return f.read() + '\n'  # newline avoids Grew error if missing

def parse_grew_query(query_text): 
    """
    Each query (Grew pattern) follows a comment line with coding instruction:
      % coding attribute=modal value=verb node=MOD addlemma=V
    """
    codings = {}
    patterns = {}
    coding_info = ['att', 'val', 'node', 'add']
    coding_nr = 0

    # remove everything from a line starting with "exit" or "quit" including all following text/newlines
    query_text = re.sub(r'\n(?:exit|quit).*', '', query_text, flags=re.S)

    sys.stderr.write("Parsing grew query...\n")

    # split by '% coding' markers
    parts = re.split(r'%\s*(coding|CODING)', query_text)
    for p in parts:
        if not re.search(r'(PATTERN|pattern)\s*{', p):
            continue
        coding = {}
        pattern = ''
        m = re.search(r'^(.*?)\n(.*)\n', p, re.DOTALL)
        if not m:
            continue
        coding_line, pattern = m.group(1), m.group(2)
        match_coding = re.search(
            r'attribute=(?P<att>\w+).*val(ue)?=(?P<val>\w+).*node=(?P<node>\w+)(?:.*?(?:add|addlemma)=(?P<add>\w+))?',
            coding_line
        )
        if match_coding:
            coding_nr += 1
            for v in coding_info:
                coding[v] = match_coding.group(v) if match_coding.group(v) else None
            codings[coding_nr] = coding
            patterns[coding_nr] = pattern
        else:
            sys.stderr.write(f"  Malformed coding line: {coding_line}\n")
    return codings, patterns

# --------------------------
# Matching (optimized)
# --------------------------

#def find_matches_by_sent_id(corpus: Corpus, patterns: Dict[int,str]) -> Dict[int, Dict[str, List[dict]], codings: Dict[int, dict]) -> Dict[int, Dict[str, List[dict]]}:
def find_matches_by_sent_id(corpus: Corpus, patterns: Dict[int,str], codings: Dict[int, dict]) -> Dict[int, Dict[str, List[dict]]]:
    """
    For each pattern number, map sent_id -> list of matches. (codings is just for stderr output)
    To speed things up touch only graphs that matched.
    version >1.2 with error handling for invalid Grew patterns.
    """
    result = {}
    for nr, pat in patterns.items():
        # --- DEBUGGING ADDED ---
        #sys.stderr.write(f"\n--- Processing pattern #{nr} ---\n")
        #sys.stderr.write(f"--- Pattern content start ---\n{pat}\n--- Pattern content end ---\n")
        # --- END DEBUGGING ---

        c = codings.get(nr, {})    #  info string for stderr
        info_str = f" ({c.get('att', '?')}={c.get('val', '?')})" if c else ""
        sys.stderr.write(f"  Searching corpus query {nr}{info_str}...")
        try:
            # This is where the error occurs if 'pat' has invalid syntax
            req = Request(pat)
            mlist = corpus.search(req)
            sys.stderr.write(f" {len(mlist)} matches\n")
            by_sid = {}
            for m in mlist:
                sid = m['sent_id']
                by_sid.setdefault(sid, []).append(m)
            result[nr] = by_sid
        # --- CATCH THE SPECIFIC ERROR ---
        except TypeError as e:
            if "'NoneType' object is not iterable" in str(e):
                sys.stderr.write(f"\n\nFATAL ERROR: Invalid Grew syntax detected in pattern #{nr} above.\n")
                sys.stderr.write("The `grewpy` library failed to parse this pattern.\n")
                sys.stderr.write("Please check the Grew syntax carefully, especially brackets, feature names, and edge labels.\n")
                sys.stderr.write(f"(Original Error: {e})\n")
            else:
                # Re-raise unexpected TypeErrors
                sys.stderr.write(f"\n\nUNEXPECTED TypeError processing pattern #{nr}:\n{pat}\nError: {e}\n")
            sys.exit(1) # Stop execution after identifying the bad pattern
        except Exception as e: # Catch other potential errors during Request creation or search
             sys.stderr.write(f"\n\nERROR processing pattern #{nr}:\n{pat}\nError: {e}\n")
             sys.exit(1) # Stop execution

    return result

def parse_coding_string(coding_str: str) -> set[tuple[str, str]]:
    """
    helper for add_coding_to_graph (needed to implement --first_rule properly)
    Parses a full '# coding = ...' string into a set of (attribute, head_id_str) tuples.
    Handles 'attr:val(node>head_lemma)' or 'attr:val(node>0)'.
    Returns head_id as a string ("0" or the node number).
    """
    parsed_pairs = set()
    if not coding_str:
        return parsed_pairs
    entries = [e.strip() for e in coding_str.split(';') if e.strip()]
    for entry in entries:
        parts = entry.split(':', 1)
        if len(parts) < 2: continue
        attr = parts[0]
        # Regex to find head_id (digits after '>') or the specific sequence '>0)'
        match = re.search(r'>(\d+)(?:_.*)?\)$', parts[1]) # Match digits after >, optionally followed by _lemma
        if match:
             head_id_str = match.group(1)
             # Distinguish '0' from actual node IDs by keeping as string
             parsed_pairs.add((attr, head_id_str))
        elif parts[1].endswith('(>0)'): # Handle the specific case of no head node
             parsed_pairs.add((attr, "0"))

    return parsed_pairs

def add_coding_to_graph(graph: Graph, match_list: List[dict], coding: Dict[str,str], args):
    """
    Apply coding to this graph for all matches of one pattern.
    Touch ONLY this graph.
    --first_rule stops further processing for same attribute AND same head node.
    This prevents adding codings less specific coding rules follow more specific ones.
    """
    current_rule_attribute = coding.get('att')
    if not current_rule_attribute:
        sys.stderr.write(f"  WARNING: Rule definition missing 'attribute'. Skipping rule.\n Coding: {coding}\n")
        return # Cannot apply rule without an attribute

    # --- Get existing codings ONCE for efficient lookup ---
    existing_attr_head_pairs = set()
    if 'coding' in graph.meta:
        existing_attr_head_pairs = parse_coding_string(graph.meta['coding'])

    # --- Track codings added *during this specific function call* ---
    # This prevents adding duplicates if the *same rule* matches multiple times
    # in a way that targets the same attribute/head pair.
    added_attr_head_pairs_this_call = set()
    coding_strings_to_add_to_meta = set()
    # Track nodes updated in MISC during this call to potentially avoid duplicate appends
    updated_nodes_misc = {} # node_id -> set of strings added

    for match in match_list:
        code_node_key = coding.get('node')
        if not code_node_key:
            sys.stderr.write(f"  WARNING: Rule definition missing 'node'. Skipping match.\n Coding: {coding}\n")
            continue
        try:
            # This is the node *being coded* (e.g., the subject pronoun)
            node_id = match['matching']['nodes'][code_node_key]
        except KeyError:
             # This match doesn't have the requested node key; skip robustly
            continue # Node key not in this specific match

        # Determine the head node ID (as a string) for this match
        add_key = coding.get('add')
        add_node_id_str = "0" # Default head_id if no 'add' key or 'add' node not found/valid
        lemma = 'unknown'
        if add_key:
            # This is the head node (e.g., the verb)
            found_add_node_id = match['matching']['nodes'].get(add_key)
            # Ensure the found node ID actually exists in the graph
            if found_add_node_id and found_add_node_id in graph:
                add_node_id_str = str(found_add_node_id) # Use string representation for consistency
                lemma = graph[found_add_node_id].get('lemma', 'unknown')
            # else: add_node_id_str remains "0"

        # Define the attribute-head pair for this potential coding
        current_attr_head_pair = (current_rule_attribute, add_node_id_str)

        # --- REFINED CHECK for --first_rule ---
        skip_this_match = False
        if args.first_rule:
             # Check if this attribute/head pair exists from a *previous* rule OR
             # has already been added by an *earlier match within this current rule processing*
             if current_attr_head_pair in existing_attr_head_pairs or \
                current_attr_head_pair in added_attr_head_pairs_this_call:
                  skip_this_match = True
                  # Optional: Add a stderr message for debugging
                  # graph_id = graph.meta.get('sent_id', graph.meta.get('item_id', 'UNKNOWN'))
                  # sys.stderr.write(f"DEBUG: Skipping match for {current_attr_head_pair} on graph {graph_id} due to --first_rule.\n")

        if not skip_this_match:
            # --- Build and collect coding string ---
            att = current_rule_attribute
            val = coding.get('val', 'val')
            if not val:
                 sys.stderr.write(f"  WARNING: Rule definition missing 'value'. Skipping match.\n Coding: {coding}\n")
                 continue # Cannot apply coding without a value

            # Construct the coding string using the determined node_id and head node ID string
            if add_node_id_str != "0":
                coding_string = f"{att}:{val}({node_id}>{add_node_id_str}_{lemma})"
            else:
                coding_string = f"{att}:{val}({node_id}>0)"

            # Add to sets for tracking and final output (sets handle internal duplicates)
            coding_strings_to_add_to_meta.add(coding_string)
            added_attr_head_pairs_this_call.add(current_attr_head_pair)

            # --- Optionally write into node's MISC ---
            if args.code_node:
                try:
                    # Initialize set for this node if not seen before in this call
                    if node_id not in updated_nodes_misc:
                        updated_nodes_misc[node_id] = set()

                    # Check if this specific string was already added to this node's MISC *in this call*
                    if coding_string not in updated_nodes_misc[node_id]:
                        existing_misc_coding = graph[node_id].get('coding', '')
                        # Check if string exists from previous script runs before appending
                        if coding_string not in existing_misc_coding.split('; '):
                            if existing_misc_coding:
                                graph[node_id]['coding'] += f"; {coding_string}"
                            else:
                                graph[node_id]['coding'] = coding_string
                        # Mark this string as added to this node in this call
                        updated_nodes_misc[node_id].add(coding_string)
                except Exception as e:
                    graph_id = graph.meta.get('sent_id', graph.meta.get('item_id', 'UNKNOWN'))
                    sys.stderr.write(f"  WARNING: Could not write coding to MISC for node {node_id} in graph {graph_id}. Error: {e}\n")
                    # Pass and continue with other matches/nodes
                    pass

    # --- Update graph meta ---
    # Add all unique strings collected from non-skipped matches for this rule
    if coding_strings_to_add_to_meta:
        # Sort for consistent output order
        full_coding_string_addition = "; ".join(sorted(list(coding_strings_to_add_to_meta)))

        if 'coding' in graph.meta:
            # Check if the *entire block* of new codings is already present somehow
            # (unlikely but prevents adding redundant blocks)
            # A more robust check might split existing and check subset, but this is simpler
            if full_coding_string_addition not in graph.meta['coding']:
                 # Check if graph.meta['coding'] is empty or just whitespace before appending ;
                 if graph.meta['coding'] and not graph.meta['coding'].isspace():
                      graph.meta['coding'] += f"; {full_coding_string_addition}"
                 else: # If existing meta is empty/whitespace, just set it
                      graph.meta['coding'] = full_coding_string_addition
        else:
             # If no coding meta exists yet, just set it
             graph.meta['coding'] = full_coding_string_addition

# --------------------------
# Output helpers
# --------------------------

def conllu_to_sentence(conllu_string):
    lines = [line for line in conllu_string.splitlines() if line and not line.startswith("#")]
    words = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) == 10 and '-' not in fields[0]:  # skip MWTs
            words.append(fields[1])
    return " ".join(words)

def conllu_to_sentence_with_coding(conllu_string):
    # support multiple codings of the form: "# coding = rule:...(<id>..."
    coding_map = {}
    for line in conllu_string.splitlines():
        if line.startswith("# coding"):
            # collect all targets in this line (robust to multiple codings)
            for m in re.finditer(r"# coding\s*=\s*(\w+):\w+\((\d+)", line):
                rule, target = m.group(1), int(m.group(2))
                coding_map[target] = rule
    lines = [line for line in conllu_string.splitlines() if line and not line.startswith("#")]
    words = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) == 10 and '-' not in fields[0]:
            try:
                wid = int(fields[0])
            except ValueError:
                continue
            form = fields[1]
            if wid in coding_map:
                rule = coding_map[wid]
                form = f"<h rule=\"{rule}\">{form}</h>"
            words.append(form)
    return " ".join(words)

# --------------------------
# Core pipelines
# --------------------------

def process_one_corpus_file(conllu_path: str, query_text: str, args) -> int:
    """
    Process a (possibly small) CoNLL-U file fully and print output.
    Returns number of graphs printed. TODO: Doesn't seem to work, yet.
    """
    if getattr(args, "estimate", False):
        try:
            est = sum(1 for _ in iter_conllu_sentences(conllu_path))
            per_min = 450000
            secs = int(est / per_min * 60)
            minutes, seconds = divmod(secs, 60)
            sys.stderr.write(f"Estimated time to read {est} graphs (Apple M2): {round(minutes,0)}m {seconds}s\n")
        except Exception:
            pass

    corpus = Corpus(conllu_path)
    codings, patterns = parse_grew_query(query_text)
    matched = find_matches_by_sent_id(corpus, patterns, codings)   # codings added only for stderr output

    draft = CorpusDraft(corpus) if not isinstance(corpus, CorpusDraft) else corpus

    printed = 0
    # For each pattern, modify only the graphs that matched it
    sys.stderr.write(f"Modifying matching graphs...\n")
    for nr, sentid2matches in matched.items():
        #sys.stderr.write(f"Modifying matching graphs for query {nr}...\n  Coding: {codings.get(nr)}\n")
        for sent_id, mlist in sentid2matches.items():
            try:
                graph = draft[sent_id]  # direct access by sent_id, avoids full scan
            except KeyError:
                # Some corpora use item_id rather than sent_id; try item_id too
                # If not present, skip silently but warn once.
                continue
            add_coding_to_graph(graph, mlist, codings[nr], args)

    # Output
    out_matches = 0
    for _, graph in draft.items():
        if args.coding_only and 'coding' not in graph.meta:
            continue
        conll_str = graph.to_conll()
        out_matches += 1
        if args.print_text:
            if args.mark_coding:
                print(conllu_to_sentence_with_coding(conll_str))
            else:
                print(conllu_to_sentence(conll_str))
        else:
            print(conll_str)

    # stats
    total = len(draft)
    if args.coding_only:
        sys.stderr.write(f"{out_matches} matches printed (of total {total} graphs)\n")
    else:
        sys.stderr.write(f"{total} graphs printed ({out_matches} matches)\n")
    return out_matches

def process_in_chunks(conllu_file: str, query_text: str, chunk_size: int, args):
    """
    Stream the big CoNLL-U file in chunks (bounded memory).
    Each chunk is processed independently and printed immediately.
    """
    it = iter_conllu_sentences(conllu_file)
    total_printed = 0
    chunk_idx = 0

    while True:
        with tempfile.NamedTemporaryFile(mode='w', suffix=".conllu", delete=False, encoding='utf-8') as tmp:
            tmp_path = tmp.name
        # Fill the temp file with up to chunk_size sentences
        written = 0
        with open(tmp_path, 'w', encoding='utf-8') as w:
            for s in it:
                w.write(s); w.write("\n")
                written += 1
                if written >= chunk_size:
                    break

        if written == 0:
            # no more sentences
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            break

        chunk_idx += 1
        sys.stderr.write(f"\n=== Processing chunk {chunk_idx} ({written} graphs) ===\n")
        try:
            total_printed += process_one_corpus_file(tmp_path, query_text, args)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    sys.stderr.write(f"\nDone. Total printed: {total_printed}\n")

# --------------------------
# CSV merge (unchanged logic)
# --------------------------

def merge_with_csv(conllu_file, csv_file, code_head=False):
    # 1. Read the CoNLL-U data
    corpus = Corpus(conllu_file)
    draft_corpus = CorpusDraft(corpus)
    sys.stderr.write(f"Merge codings from {conllu_file} to {csv_file}\n")
    
    id_meta = {}
    coded = 0
    newly_encountered_attributes = set()

    for sent_id, graph in draft_corpus.items():
        coding = graph.meta.get('coding', '')
        item_id = graph.meta.get('item_id')
        if item_id is None: continue
        
        id_meta[item_id] = coding
        if coding:
            coded += 1
            for entry in [e.strip() for e in coding.split(';') if e.strip()]:
                # Extract attribute name (e.g. "subj" from "subj:clit(...)")
                attr = entry.split(':', 1)[0].strip()
                if attr: newly_encountered_attributes.add(attr)

    sys.stderr.write(f"- Reading the corpus to map item_id -> coding...{len(draft_corpus)} graphs, {coded} codings\n")

    # 2. Read the existing CSV
    sys.stderr.write(f"Reading table {csv_file}...\n")
    rows = []
    original_headers = []

    if os.path.exists(csv_file):
        with open(csv_file, mode='r', newline='', encoding='utf-8') as file:
            try:
                # Read headers first to filter empty ones
                header_reader = csv.reader(file, delimiter='\t')
                original_headers = next(header_reader)
                original_headers = [h for h in original_headers if h] # Remove empty header strings
                
                file.seek(0)
                # Use DictReader with refined headers
                reader = csv.DictReader(file, fieldnames=original_headers, delimiter='\t')
                next(reader) # skip header row
                rows = list(reader)
            except Exception as e:
                 sys.stderr.write(f"ERROR: Could not read CSV {csv_file}. Error: {e}\n")
                 return

    if 'utt_id' not in original_headers:
         sys.stderr.write(f"ERROR: 'utt_id' column not found in CSV. Cannot merge.\n")
         return

    # 3. Clean rows to avoid matching errors
    # Remove 'None' key if present (caused by trailing tabs/extra columns in input)
    for row in rows:
        if None in row:
            del row[None]

    # Map rows by ID
    row_dict = {}
    sys.stderr.write("- Mapping CSV IDs to rows...\n")
    for row in rows:
        utt_id = row.get('utt_id')
        if utt_id is not None:
            row_dict[utt_id] = row

    # 4. Determine Final Headers
    final_headers = list(original_headers)
    for attr in sorted(list(newly_encountered_attributes)):
        if attr not in final_headers:
            sys.stderr.write(f"  Adding attribute as new column header: {attr}\n")
            final_headers.append(attr)

    # 5. Merge Data
    for sent_id, coding in id_meta.items():
        if not coding: continue
        coding_entries = [e.strip() for e in coding.split(';') if e.strip()]

        for entry in coding_entries:
            parts = re.split(r':', entry, maxsplit=1)
            attr = parts[0].strip()
            if not attr or len(parts) < 2: continue
            val = parts[1].strip()

            # Logic to find target word index
            m = re.search(r'\((\d+)>(\d+)(?:_.*)?\)$', val)
            node_id_str = m.group(1) if m else "1"
            head_id_str = m.group(2) if m else "0"
            
            # Fallback for root
            if not m and re.search(r'\((\d+)>0\)$', val):
                 node_id_str = re.search(r'\((\d+)>0\)$', val).group(1)

            target_node = head_id_str if code_head else node_id_str
            this_id = f"{sent_id}_w{target_node}"

            if this_id in row_dict:
                row = row_dict[this_id]
                current_val = row.get(attr, '')
                row[attr] = f"{current_val};{val}" if current_val else val

    # 6. Write Output
    merged_file = re.sub(r'(\.\w+)$', r'.coded\1', csv_file)
    tmp_file = merged_file + ".tmp"
    sys.stderr.write(f"Writing first output to {tmp_file}\n")

    with open(tmp_file, mode='w', newline='', encoding='utf-8') as file:
        # Added extrasaction='ignore' to prevent crashes on unknown keys
        writer = csv.DictWriter(file, fieldnames=final_headers, delimiter='\t', 
                                quoting=csv.QUOTE_NONE, escapechar='\x1e', 
                                extrasaction='ignore')
        writer.writeheader()
        writer.writerows(row_dict.values())

    # Final cleanup of quotes
    sys.stderr.write(f"  Cleaning quotes around =HYPERLINK() formulas\n")
    with open(tmp_file, mode='r', encoding='utf-8') as infile, open(merged_file, mode='w', encoding='utf-8') as outfile:
        for line in infile:
            cleaned_line = re.sub(r"\x1e", "", line)
            outfile.write(cleaned_line)
            
    sys.stderr.write(f"Writing final output to {merged_file}\n")
    os.unlink(tmp_file)

# --------------------------
# CLI
# --------------------------

def main_cli():
    parser = argparse.ArgumentParser(description=
        '''Query CoNLL-U corpus using Grew query language.
        This script was designed to process general CHILDES data (coding function)
        and to merge the output with tables created by childes.py (merge function).'''
    )
    parser.add_argument("query_file", nargs="?", default=None, help="File with Grew query")
    parser.add_argument("conllu_file", help="CoNLL-U file with parsed data")
    parser.add_argument('-c','--coding_only', action='store_true',
                        help='Print only coded graphs (query matches). Default: print everything')
    parser.add_argument('-f','--first_rule', action='store_true',
                        help='For a given attribute AND head node combination (e.g., subj targeting verb V1), '
                             'only apply the first matching rule. Subsequent rule matches for the '
                             'same attribute targeting the same head node on the same graph will be ignored.')
    parser.add_argument('-m','--mark_coding', action='store_true',
                        help='Print codes around matched words in the sentence (requires --print_text)')
    parser.add_argument('-n','--code_node', action='store_true',
                        help='Add coding also to column misc of the specified node (implies --coding)')
    parser.add_argument('--code_head', action='store_true',
                        help='Add coding only to the head node of the coding (value node>head)')
    parser.add_argument('--merge', default='', type=str,
                        help='CSV path: add codings from CoNLL-U file to CSV based on sentence+word IDs.')
    parser.add_argument('-t','--print_text', action='store_true',
                        help='Print only sentence text (not CoNLL-U graphs)')
    parser.add_argument('--chunk-size', type=int, default=0,
                        help='Process the CoNLL-U in chunks of N sentences (streaming, avoids large memory).')
    parser.add_argument('--estimate', action='store_true',
                        help='Print a rough ETA by counting sentences first.')

    args = parser.parse_args()

    # merge mode unchanged
    if args.merge:
        sys.stderr.write(f"Merge codings from {args.conllu_file} to {args.merge}\n")
        merge_with_csv(args.conllu_file, args.merge, code_head=args.code_head)
        return

    if not args.query_file:
        parser.error("Either 'query_file' must be specified or '--merge' must be used.")

    query_text = read_grew_query(args.query_file)

    if args.mark_coding and not args.print_text:
        sys.stderr.write("NOTE: --mark_coding implies --print_text.\n")
        args.print_text = True

    if args.chunk_size and args.chunk_size > 0:
        # STREAMING PATH: bounded memory
        process_in_chunks(args.conllu_file, query_text, args.chunk_size, args)
    else:
        # SINGLE SHOT PATH (legacy, but faster for medium corpora)
        process_one_corpus_file(args.conllu_file, query_text, args)

if __name__ == "__main__":
    main_cli()