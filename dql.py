#!/usr/local/bin/python3
"""
TODO:
- options where to add coding
- re-import in Childes csv
"""
__author__ = "Achim Stein"
__version__ = "0.1"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "12.11.24"
__license__ = "GPL"

import sys
import re
import argparse
from grewpy import Corpus, Request, CorpusDraft #Graph

def main(query_file, conllu_file, args):
    # Read and parse the Grew query
    query_content = read_grew_query(query_file)
    sys.stderr.write(f"Query:\n{query_content}\n")
    
    # Match sentences in the CoNLL-U file against the GREW query
    new_graphs = match_sentences_with_query(conllu_file, query_content)
    
    # Output matched sentences
    for graph in new_graphs:
        print(graph.to_conll())

def read_grew_query(query_file):
    # Read Grew query file.
    with open(query_file, 'r', encoding='utf-8') as f:
        query_content = f.read()
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
    pattern_list = query_file.split('% coding')
    for p in pattern_list:
        coding = {}  # dictionary stores one coding
        pattern = ''
        m = re.search(r'^(.*?)\n(.*)\n', p, re.DOTALL)
        # grep coding information
        if m:
            coding_line = m.group(1)
            pattern = m.group(2)
            match_coding = re.search(r'attribute=(?P<att>\w+).*val(ue)?=(?P<val>\w+).*node=(?P<node>\w+).*(add|addlemma)=(?P<add>\w+)', coding_line)
            if match_coding:
                coding_nr += 1
                for v in coding_info:
                    coding[v] = match_coding.group(v)
            else: 
                sys.stderr.write("  Malformed coding line: {coding_line}\n")
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
    # Convert it to a CorpusDraft if it isn't already
    draft_corpus = CorpusDraft(corpus) if not isinstance(corpus, CorpusDraft) else corpus
    for nr in matches_for_patterns.keys():
        sys.stderr.write(f"Modifying matching graphs for query {nr}...\n   Coding: {codings[nr]}\n")
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
    if sent_id in sent_id2match:
        match = sent_id2match[sent_id]  # select the match for this graph
        node_id = match['matching']['nodes'][coding['node']]  # the ID of the node specified in coding node=...
        add_node = match['matching']['nodes'][coding['add']]
        # build the coding string
        coding_string = f"{coding['att']}:{coding['val']}({node_id}>{add_node}_{graph[add_node]['lemma']})"
        if 'coding' in graph.meta:
            graph.meta['coding'] += f"; {coding_string}"  # append to existing coding
            sys.stderr.write(f"Appending to existing coding: {graph.meta['coding']}\n")
        else:
            graph.meta['coding'] = coding_string  # add to meta
        # this (miraculously) adds coding as a feature to column 'misc' (get_misc_string() not needed)
        graph[node_id]['coding'] = coding_string  
   
    # Return the modified graph (or unmodified if no match)
    return graph

def init_corpus(conllu_file):
    # init Grew corpus object (this is slow: print estimate)
    count = count_graphs(conllu_file)
    per_min = 450000  # processed sentences per min on Mac M2
    secs = int(count / per_min * 60)
    minutes, seconds = divmod(secs, 60)
    sys.stderr.write(f"Estimated time to read {count} graphs: {round(minutes,0)}m {seconds}s\n")
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=
        '''Query CoNLL-U corpus using Grew query language.
        This script was designed to process CHILDES data created by childes.py.
        '''
    )
    parser.add_argument("query_file", help="File with Grew query")
    parser.add_argument("conllu_file", help="CoNLL-U file with parsed data")
    parser.add_argument(
       '-m', '--max', default = float('inf'), type = int,
       help='Max output: stop after <int> matches')
    parser.add_argument(
       '-f', '--format', default = float('inf'), type = int,
       help='Output format (or list of formats), e.g. conll,text,json')
    args = parser.parse_args()

    main(args.query_file, args.conllu_file,args)