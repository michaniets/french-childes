#!/usr/local/bin/python3

__author__ = "Achim Stein"
__version__ = "0.5"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "18.11.24"
__license__ = "GPL"

import sys
import re
import argparse
import csv
import pandas as pd   # TODO test if Pandas is faster than DictReader with large tables
import os
from grewpy import Corpus, Request, CorpusDraft, Graph

def main(query_file, conllu_file, args):
    # Read and parse the Grew query
    query_content = read_grew_query(query_file)
    sys.stderr.write(f"Query:\n{query_content}\n")
    
    # Match sentences in the CoNLL-U file against the GREW query
    new_graphs = match_sentences_with_query(conllu_file, query_content)
    
    # Output matched sentences
    out_matches = 0
    if args.coding_only:  # print only coded output
        for graph in new_graphs:
            if 'coding' in graph.meta:
                print(graph.to_conll())
                out_matches +=1
        sys.stderr.write(f"{out_matches} matches printed (of total {len(new_graphs)} graphs)\n")
    else:
        for graph in new_graphs:
            print(graph.to_conll())  # print every graph
            if 'coding' in graph.meta:
                out_matches +=1
        sys.stderr.write(f"{len(new_graphs)} graphs printed ({out_matches} matches)\n")
def read_grew_query(query_file):
    # Read Grew query file.
    with open(query_file, 'r', encoding='utf-8') as f:
        query_content = f.read() + '\n'  # append new line to avoid Grew error if missing
    return query_content

def parse_grew_query(query_file): 
    """
    Each query (Grew pattern) follows a comment line that contains coding instruction
    coding line:   % coding attribute=modal value=verb node=MOD add=V
    adds coding:   modal=verb(<lemma of V>)
    """
    codings = {}  # dict of codings
    patterns = {} # list of concatenated Grew queries
    coding_info = ['att', 'val', 'node', 'add']  # keys for the dictionary that stores one coding
    coding_nr = 0
    # split query file in Grew queries, separated by '% coding ...'
    sys.stderr.write("Parsing grew query...\n")
    pattern_list = re.split(r'%\s*(coding|CODING)', query_file)
    for p in pattern_list:
        if not re.search(r'(PATTERN|pattern)\s*{', p):  # each query needs a pattern { }
            continue
        coding = {}  # dictionary stores one coding
        pattern = ''
        m = re.search(r'^(.*?)\n(.*)\n', p, re.DOTALL)
        # grep coding information
        if m:
            coding_line = m.group(1)
            pattern = m.group(2)
            match_coding = re.search(r'attribute=(?P<att>\w+).*val(ue)?=(?P<val>\w+).*node=(?P<node>\w+)(.*(add|addlemma)=(?P<add>\w+))?', coding_line)
            if match_coding:
                coding_nr += 1
                for v in coding_info:
                    coding[v] = match_coding.group(v)
            else: 
                sys.stderr.write(f"  Malformed coding line: {coding_line}\n")
        else:
            continue   # ignore queries without coding line
        # store codings and patterns in dictionaries with the same keys
        codings[coding_nr] = coding
        patterns[coding_nr] = pattern
    return codings, patterns

def find_matches(corpus, patterns):
    """
    Finds all sentences that match any of the queries (patterns).
    Returns a dict with key = pattern number and value = list of matches
    """
    matches_for_patterns = {}
    for nr in patterns.keys():
        sys.stderr.write(f"  Searching corpus query {nr}...")
        request = Request.parse(patterns[nr])
        match_list = corpus.search(request)  # matches for this pattern
        sys.stderr.write(f" {len(match_list)} matches\n")
        matches_for_patterns[nr] = match_list  # store the list of matches in a dict with patter nr as key
    return matches_for_patterns

def match_sentences_with_query(conllu_file, query_content):
    """
    Reads corpus as Grew object. Matches corpus against set of Grew patterns.
    Copies the corpus to a modifiable DraftCorpus.
    For each pattern, for each match for pattern: modifies graph, adds coding if present.
    """
    new_graphs = []  # modified graphs
    corpus = init_corpus(conllu_file)
    codings, patterns = parse_grew_query(query_content)
    matches_for_patterns = find_matches(corpus, patterns)
    # Convert corpus to a CorpusDraft object if it isn't already
    draft_corpus = CorpusDraft(corpus) if not isinstance(corpus, CorpusDraft) else corpus
    for nr in matches_for_patterns.keys():
        sys.stderr.write(f"Modifying matching graphs for query {nr}...\n  Coding: {codings[nr]}\n")
        sent_id2match = {}
        for match in matches_for_patterns[nr]:
            sent_id2match[match['sent_id']] = match  # map sent_id -> match
        # loop through corpus items (sent_id:GraphObject) and apply add_coding
        sys.stderr.write(f"  Loop through corpus graphs...\n")
        for sent_id, graph in draft_corpus.items():
            new_graph = add_coding(graph, sent_id, sent_id2match, codings[nr])
            new_graphs.append(new_graph)
    return new_graphs  # return list of modified graphs

def add_coding(graph, sent_id, sent_id2match, coding):
    """
    Modify the Graph of the DraftCorpus object
    Apply coding if this sent_id is in the list of matches, else print.
    Matches have an internally created item_id (e.g. file.conllu_00140).
       e.g.: {'sent_id': 'out.conllu_06242', 'matching': {'nodes': {'V': '3', 'MOD': '2'}, 'edges': {}}}
    Graphs contain the meta information (graph.meta) including sent_id (graph.meta['sent_id'])
    """
    # if sent_id has been stored with a match, modify the graph
    if sent_id in sent_id2match:
        match = sent_id2match[sent_id]  # select the match for this graph
        node_id = match['matching']['nodes'][coding['node']]  # the ID of the node specified in coding node=...
        if coding['add']:
            add_node = match['matching']['nodes'][coding['add']]
            coding_string = f"{coding['att']}:{coding['val']}({node_id}>{add_node}_{graph[add_node]['lemma']})"
        else:
            add_node = 0
            coding_string = f"{coding['att']}:{coding['val']}({node_id}>{add_node})"
        # build the coding string
        if 'coding' in graph.meta:
            graph.meta['coding'] += f"; {coding_string}"  # append to existing coding
        else:
            graph.meta['coding'] = coding_string  # add to meta
        if args.code_node:   
            graph[node_id]['coding'] = coding_string   # add coding as a feature to column 'misc'
    # returns changed and unchanged graphs
    return graph

def init_corpus(conllu_file):
    # init Grew corpus object (this is slow: print estimate)
    count = count_graphs(conllu_file)
    per_min = 450000  # processed sentences per min on Mac M2
    secs = int(count / per_min * 60)
    minutes, seconds = divmod(secs, 60)
    sys.stderr.write(f"Estimated time to read {count} graphs (Apple M2): {round(minutes,0)}m {seconds}s\n")
    corpus = Corpus(conllu_file)  # corpus file as Corpus object (slow)
    return corpus

def get_misc_string(graph, node_id):
    "get value of 'misc' column as whole string"
    feats = ''
    conll = graph.to_conll()
    reNode = re.compile(rf'{node_id}\t.*\t(.*?)\n')
    m = re.search(reNode, conll)
    if m:
        feats = m.group(1)
        return feats
    else:
        return ''

def count_graphs(conllu_file):
    # count empty lines as end of graph
    graph_count = 0
    with open(conllu_file, 'r', encoding='utf-8') as file:
        for line in file:
            if line.strip() == '':
                graph_count += 1
    return graph_count

def conllu_to_graphs(conllu_file):
    "read conllu format into a list of Graph objects (not used)"
    graphs = []
    sent = ''
    with open(conllu_file, 'r', encoding='utf-8') as file:
        for line in file:
            if line.strip() == '':  # on empty line
                #print(f"CONLL2GRAPH:\n{sent}")
                graphs.append(Graph(sent))
                show(Graph(sent))
                sent = ''
            else:
                sent += f"{line}" 
    print(f"CONLL2GRAPHS: {len(graphs)}")
    exit()    
    return graphs

def show(graph):
    print(graph.meta)
    exit()

def merge_with_csv(conllu_file, csv_file):
    # read conllu_file as Grew corpus
    corpus = init_corpus(conllu_file)

    # Read current CSV data (or create new header if CSV is empty or does not exist)
    sys.stderr.write(f"Reading table {csv_file}... (this can take a while)\n")
    rows = []
    headers = ['utt_id']  # Ensure utt_id is the first column in headers
    if os.path.exists(csv_file):
        with open(csv_file, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file, delimiter='\t')
            headers = reader.fieldnames if reader.fieldnames else headers
            rows = list(reader)
    """  with Pandas (output and row modification would also need to be modified)
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file, delimiter='\t', encoding='utf-8')  # Read with Pandas
        headers = list(df.columns)  # Match reader.fieldnames
        rows = df.to_dict(orient='records')  # Match list(reader)
    else:
        headers = ['utt_id']
        rows = []
    """    
    # create DraftCorpus and loop through graphs
    draft_corpus = CorpusDraft(corpus) if not isinstance(corpus, CorpusDraft) else corpus
    sys.stderr.write(f"- Reading the corpus to map item_id -> coding")
    id_meta = {}
    coded = 0
    for sent_id, graph in draft_corpus.items():
        coding = graph.meta.get('coding')
        item_id = graph.meta.get('item_id')
        if coding:
            coded +=1
            id_meta[item_id] = coding
        else:
            id_meta[item_id] = ''
    sys.stderr.write(f"{len(id_meta.keys())} graphs, {coded} codings\n")
    coding_to_csv(sent_id, id_meta, headers, rows)

def coding_to_csv(sent_id, id_meta, headers, rows):
    """
    Extract coding from a CoNLL-U graph and append it to a CSV file.
    
    Parameters:
        graph (grewpy.graph.Graph): The graph from which to extract codings.
        csv_file (str): The path to the CSV file where codings will be saved.
    """
    # Create a mapping of utt_id to row for quick access
    sys.stderr.write(f"- Mapping CSV IDs to rows...\n")
    row_dict = {row['utt_id']: row for row in rows}# Find the row with matching 'utt_id' or create a new one if not found

    # Loop through the stored meta information
    for sent_id in id_meta.keys():
        node_id = 1  # coding value is added to the row of this node  (assuming IDs with '_w1' etc)
        coding = id_meta[sent_id] #graph.meta.get('coding') #graph.meta['coding']

        # if coding exists, parse, make dict of attribute:value, modify row
        #    else: don't modify anything
        if coding != '':
            coding_entries = coding.split(';')
            coding_dict = {}
            # for each coding in the meta information
            for entry in coding_entries:
                parts = re.split(r':', entry, maxsplit=1)
                attr = parts[0]
                val = parts[1] if len(parts) > 1 else None  # Default value if no ':'
                if val is None:
                    sys.stderr.write(f"   WARNING ({sent_id}): Missing value for attribute '{attr}'. Skipping entry.\n")
                    continue
                # get node value from coding string, e.g. attribute = value(2>3_verb)
                reNode = re.compile(r'.*?\((\d+)')
                m = re.search(reNode, val)
                if m:
                    node_id = m.group(1)
                else:
                    sys.stderr.write(f"   No node info found in coding {entry}. Adding coding to node 1 instead.\n")
                if node_id == "0":
                    sys.stderr.write(f"   WARNING ({sent_id}): Can't write to node '0'. Adding coding to node 1 instead. VAL = {val}\n")
                    node_id = 1
                coding_dict[attr.strip()] = (val.strip(), node_id)
                sys.stderr.write(f"       -----> coding_dict: adding {attr} -> {val} \n")

            # Add any new columns for attributes found in coding_dict
            for attr in coding_dict.keys():
                if attr not in headers:
                    sys.stderr.write(f"  Adding attribute as new column header: {attr}\n")
                    headers.append(attr)

            # Process each attribute and update the CSV row
            for attr, (val, node_id) in coding_dict.items():
                # Combine sentence ID and node ID to form the row ID
                this_id = sent_id + f"_w{node_id}"
                if this_id in row_dict:
                    row = row_dict[this_id]
                    row[attr] = val   # Update column 'attr' with this value
                    sys.stderr.write(f"       -----> updating row {this_id}: {attr} -> {val} \n")
                else:
                    sys.stderr.write(f"! WARNING: ID not found in CSV: {this_id}\n")

    # Write updated data to new CSV file *.coded.csv
    merged_file = re.sub(r'(\.\w+)$', '.coded\\1', args.merge) # , flags=re.I
    sys.stderr.write(f"Writing output to {merged_file}\n")
    with open(merged_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=headers, delimiter='\t')
        writer.writeheader()
        writer.writerows(row_dict.values())  # updated rows from row_dict


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=
        '''Query CoNLL-U corpus using Grew query language.
        This script was designed to process CHILDES data created by childes.py.
        '''
    )
#    parser.add_argument("query_file", help="File with Grew query")
    parser.add_argument("query_file", nargs="?", default=None, help="File with Grew query")
    parser.add_argument("conllu_file", help="CoNLL-U file with parsed data")
    parser.add_argument(
       '-c', '--coding_only', action='store_true',
       help='Print only coded graphs (query matches). Default: print everything')
    parser.add_argument(
       '-n', '--code_node', action='store_true',
       help='Add coding also to column misc of the specified node (this option implies --coding)')
    parser.add_argument(
       '--merge', default = '', type = str,
       help='Argument is a CSV file. Adds codings from CoNLL-U file to CSV file, with attributes as columns, based on sentence and word IDs.')
    args = parser.parse_args()

    if args.merge:
        if not args.merge:
            parser.error("--merge requires a file path as an argument.")
        # merge codings with csv file
        sys.stderr.write(f"Merge codings from {args.conllu_file} to {args.merge}\n")
        merge_with_csv(args.conllu_file, args.merge)
    elif args.query_file:
        # default: run query/coding functions
        main(args.query_file, args.conllu_file,args)
    else:
        parser.error("Either 'query_file' must be specified or '--merge' must be used.")