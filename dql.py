#!/usr/local/bin/python3
# -*- coding: utf-8 -*-

__author__ = "Achim Stein"
__version__ = "1.0"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "14.10.2025"
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
      % coding attribute=modal value=verb node=MOD add=V
    """
    codings = {}
    patterns = {}
    coding_info = ['att', 'val', 'node', 'add']
    coding_nr = 0
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

def find_matches_by_sent_id(corpus: Corpus, patterns: Dict[int,str]) -> Dict[int, Dict[str, List[dict]]]:
    """
    For each pattern number, map sent_id -> list of matches.
    To speed things up touch only graphs that matched.
    """
    result = {}
    for nr, pat in patterns.items():
        sys.stderr.write(f"  Searching corpus query {nr}...")
        req = Request(pat)
        mlist = corpus.search(req)
        sys.stderr.write(f" {len(mlist)} matches\n")
        by_sid = {}
        for m in mlist:
            sid = m['sent_id']
            by_sid.setdefault(sid, []).append(m)
        result[nr] = by_sid
    return result

def add_coding_to_graph(graph: Graph, match_list: List[dict], coding: Dict[str,str], args):
    """
    Apply coding to this graph for all matches of one pattern.
    Touch ONLY this graph.
    """
    # honor --first_rule: if any coding already present, skip
    if args.first_rule and 'coding' in graph.meta:
        return

    for match in match_list:
        # which node to code
        code_node_key = coding.get('node')
        if not code_node_key:
            continue
        try:
            node_id = match['matching']['nodes'][code_node_key]
        except KeyError:
            # This match doesn't have the requested node; skip robustly
            continue

        # optional extra node (for lemma)
        add_key = coding.get('add')
        add_node = None
        lemma = 'unknown'
        if add_key:
            add_node = match['matching']['nodes'].get(add_key)
            if add_node and add_node in graph:
                lemma = graph[add_node].get('lemma', 'unknown')

        # build coding string
        att = coding.get('att', 'att')
        val = coding.get('val', 'val')
        if add_node:
            coding_string = f"{att}:{val}({node_id}>{add_node}_{lemma})"
        else:
            coding_string = f"{att}:{val}({node_id}>0)"

        # attach to graph meta
        if 'coding' in graph.meta:
            graph.meta['coding'] += f"; {coding_string}"
        else:
            graph.meta['coding'] = coding_string

        # optionally write into node's MISC
        if args.code_node:
            try:
                graph[node_id]['coding'] = coding_string
            except Exception:
                # If node is missing or not writable, keep going
                pass

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
    matched = find_matches_by_sent_id(corpus, patterns)

    draft = CorpusDraft(corpus) if not isinstance(corpus, CorpusDraft) else corpus

    printed = 0
    # For each pattern, modify only the graphs that matched it
    for nr, sentid2matches in matched.items():
        sys.stderr.write(f"Modifying matching graphs for query {nr}...\n  Coding: {codings.get(nr)}\n")
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
    corpus = Corpus(conllu_file)
    sys.stderr.write(f"Reading table {csv_file}...\n")
    rows = []
    headers = ['utt_id']
    if os.path.exists(csv_file):
        with open(csv_file, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file, delimiter='\t')
            headers = reader.fieldnames if reader.fieldnames else headers
            rows = list(reader)

    draft_corpus = CorpusDraft(corpus) if not isinstance(corpus, CorpusDraft) else corpus
    sys.stderr.write(f"- Reading the corpus to map item_id -> coding...")
    id_meta = {}
    coded = 0
    for sent_id, graph in draft_corpus.items():
        coding = graph.meta.get('coding', '')
        item_id = graph.meta.get('item_id')
        if item_id is None:
            continue
        id_meta[item_id] = coding
        if coding:
            coded += 1
    sys.stderr.write(f"{len(id_meta.keys())} graphs, {coded} codings\n")

    sys.stderr.write(f"- Mapping CSV IDs to rows...\n")
    row_dict = {}
    for row in rows:
        utt_id = row.get('utt_id')
        if utt_id is not None:
            row_dict[utt_id] = row
        else:
            sys.stderr.write(f"WARNING: Row missing 'utt_id': {row}\n")

    for sent_id, coding in id_meta.items():
        if coding == '':
            continue
        coding_entries = [e.strip() for e in coding.split(';') if e.strip()]
        coding_dict = {}
        node_id = 1

        for entry in coding_entries:
            parts = re.split(r':', entry, maxsplit=1)
            attr = parts[0].strip()
            val = parts[1].strip() if len(parts) > 1 else None
            if not val:
                sys.stderr.write(f"   WARNING ({sent_id}): Missing value for attribute '{attr}'. Skipping entry.\n")
                continue

            m = re.search(r'\((\d+)>(\d+)', val)
            if m:
                node_id = m.group(1)
                head_id = m.group(2)
            else:
                sys.stderr.write(f"   No node info found in coding {entry}. Adding coding to node 1 instead.\n")
                node_id = "1"
                head_id = "1"

            if node_id == "0":
                sys.stderr.write(f"   WARNING ({sent_id}): Can't write to node '0'. Adding coding to node 1 instead. VAL = {val}\n")
                node_id = "1"

            target_id = head_id if code_head else node_id
            coding_dict.setdefault(attr, []).append((val, target_id))

        for attr in coding_dict.keys():
            if attr not in headers:
                sys.stderr.write(f"  Adding attribute as new column header: {attr}\n")
                headers.append(attr)

        for attr, values in coding_dict.items():
            for val, nid in values:
                if sent_id is None:
                    sys.stderr.write(f"WARNING: sent_id is None for node_id {nid}. Skipping.\n")
                    this_id = "0000" + f"_w{nid}"
                else:
                    this_id = sent_id + f"_w{nid}"
                if this_id in row_dict:
                    row = row_dict[this_id]
                    if attr in row and row[attr]:
                        row[attr] += f";{val}"
                    else:
                        row[attr] = val
                else:
                    sys.stderr.write(f"! WARNING: ID not found in CSV: {this_id}\n")

    merged_file = re.sub(r'(\.\w+)$', '.coded\\1', csv_file)
    sys.stderr.write(f"Writing output to {merged_file}\n")
    with open(merged_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=headers, delimiter='\t')
        writer.writeheader()
        writer.writerows(row_dict.values())

# --------------------------
# CLI
# --------------------------

def main_cli():
    parser = argparse.ArgumentParser(description=
        '''Query CoNLL-U corpus using Grew query language.
        This script was designed to process CHILDES data created by childes.py.'''
    )
    parser.add_argument("query_file", nargs="?", default=None, help="File with Grew query")
    parser.add_argument("conllu_file", help="CoNLL-U file with parsed data")
    parser.add_argument('-c','--coding_only', action='store_true',
                        help='Print only coded graphs (query matches). Default: print everything')
    parser.add_argument('-f','--first_rule', action='store_true',
                        help='If the first rule for an attribute matches, discard following rules')
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