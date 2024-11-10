#!/usr/local/bin/python3

"""
match_list geht nicht. 

1. jeden Satz matchen


"""

__author__ = "Achim Stein"
__version__ = "0.1"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "10.11.24"
__license__ = "GPL"

import re
import argparse
from grewpy import Corpus, Request, Graph

def read_grew_query(query_file):
    # Read Grew query file.
    with open(query_file, 'r', encoding='utf-8') as f:
        query_content = f.read()
    return query_content

def parse_grew_query_ALT(query_file): 
    nodes = []
    coding = {}
    coding_line = ''
    for line in query_file.split('\n'):
        # collect nodes in list
        reNode = re.compile('(\w+)\s*?\[.*]')
        m = re.search(reNode, line)
        if m:
            nodes.append(m.group(1))  
        # grep coding instruction from comment line (% coding...)
        if not coding_line and re.search(r'coding', line, re.IGNORECASE):
            coding_line = line
    """
    coding line:   % coding attribute=modal value=verb node=MOD addlemma=V
    adds "modal=verb(<lemma of V>)" to (1) meta information and (2) the 'misc' column of MOD node
    """
    if coding_line:
        m = re.search(r'(attr?|attribute)=(?P<value>\w+)', coding_line, re.IGNORECASE)
        if m:
            coding['att'] = m.group('value')
        m = re.search(r'(val|value)=(?P<value>\w+)', coding_line, re.IGNORECASE)
        if m:
            coding['val'] = m.group('value')
        m = re.search(r'(node)=(?P<value>\w+)', coding_line, re.IGNORECASE)
        if m:
            coding['node'] = m.group('value')  # adds coding string to 'misc' of this node
        m = re.search(r'(add)?lemma=(?P<value>\w+)', coding_line, re.IGNORECASE)
        if m:
            coding['addlemma'] = m.group('value')  # adds lemma of this node
        print(f"Coding info: {coding}")
    else:
        print("Coding instructions not found.  Use a comment to define them, e.g. '% coding attribute=modal value=verb node=VERB'")
    return coding

def parse_grew_query(query_file): 
    """
    Each query (Grew pattern) follows a comment line that contains coding instruction
    coding line:   % coding attribute=modal value=verb node=MOD add=V
    adds "modal=verb(<lemma of V>)" to (1) meta information and (2) the 'misc' column of MOD node
    """
    pattern_dict = {} # list of concatenated Grew queries
    coding_info = ['att', 'val', 'node', 'add']  # keys for the dictionary that stores one coding
    coding_nr = 0
    codings = {}  # dict of codings
    # split query file in Grew queries, separated by '% coding ...'
    print("Parsing grew query...")
    patterns = query_file.split('% coding')
    for p in patterns:
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
                print("  Malformed coding line: {coding_line}\n")
        else:
            continue   # ignore queries without coding line
        # store codings and patterns in dictionaries with the same keys
        codings[coding_nr] = coding
        pattern_dict[coding_nr] = pattern
    return codings, pattern_dict

def find_matches(corpus, patterns):
    """Finds all sentences that match any of the queries (patterns)."""
    unique_ids = set()  # Use a set to avoid duplicates
    all_matches = []    # The matching structures
    match_list_pattern = {}
    for nr in patterns.keys():
        print(f"  Searching corpus query no. {nr}...")
        request = Request.parse(patterns[nr])
        match_list = corpus.search(request)
        print(f"    Found {len(match_list)} matches for query:\n{patterns[nr]}")
        match_list_pattern[nr] = match_list  # store the list of matches in a dict with patter nr as key
        for match in match_list:
            sent_id = match['sent_id']
            if sent_id not in unique_ids:  # set() allows fast membership testing
                unique_ids.add(sent_id)  # Add the sent_id to the set
                all_matches.append(match)  # Append the full match object to the list
    print(f"Found {len(unique_ids)} matches for all the patterns")
#    return unique_ids, all_matches
    return match_list_pattern

def match_sentences_with_query(conllu_file, query_content):
    """
    Match each sentence against the pattern(s) of the query file.
    Add codings if present.
    """
    per_min = 450000  # time for loading conllu in Grew Corpus object
    count = count_graphs(conllu_file)
    secs = int(count / per_min * 60)
    minutes, seconds = divmod(secs, 60)


    # init Grew objects (initiating Corpus object is slow)
    print(f"Estimated time to read {count} graphs: {round(minutes,0)}m {seconds}s")
    corpus = Corpus(conllu_file)  # corpus file as Corpus object (slow)
    codings, patterns = parse_grew_query(query_content)
#    unique_ids, all_matches = find_matches(corpus, patterns)
    match_list_pattern = find_matches(corpus, patterns)
  
    # Iterate through each matching graph
    match_nr = 0 
    matched_graphs = []
    """
    ===============   TODO  alle Graphen mit .apply() behandeln.
    add_coding  muss prüfen, ob graph in liste der sent_ids für eine Regel ist.
    """
    for nr in match_list_pattern.keys():
        all_matches = match_list_pattern[nr]
        for match in all_matches:
            match_nr += 1
            sent_id = match['sent_id']
            graph = corpus.get(sent_id)  # get graph for this id
            if match_nr > args.max:
                print(f"Maximum match number {args.max} reached: search stopped.")
                return matched_graphs
    #        nodes = match['matching']['nodes'] # word IDs matching nodes in query
    #        print(f"\n===> Match nr = {match_nr} | nodes = {nodes}\n  {match}")
            matched_graphs.append(graph)
            print(graph.to_sentence())
            j_graph = graph.json_data()  # graph in JSON format
            # add coding data
            for nr in codings.keys():
                add_coding(match, j_graph, codings[nr], patterns[nr])
            # add utterance to meta
            get_misc_string(graph, "1")
            j_graph["meta"]["utterance"] = graph.to_sentence()
            print(graph.to_conll())  # Print matched sentences in CoNLL-U format

#        sent_id = match['sent_id']
#        nodes = match['matching']['nodes']
    return matched_graphs

def add_coding(match, j_graph, coding, pattern):
    """Add coding to this sentence in meta header and in misc column of the specified node"""
    j_graph["meta"]["coding"] = '' # add empty coding line
    # add coding to meta
    addlemma_node_id = match['matching']['nodes'][coding['add']] # id of coding node
    lemma = j_graph['nodes'][addlemma_node_id]['lemma']           # lemma of this node
    coding_string = f"{coding['att']}={coding['val']}({lemma})"
    j_graph["meta"]["coding"] += f"{coding_string}"
    # add coding to node specified in the coding instruction
    coding_node_id = match['matching']['nodes'][coding['node']] # id of coding node
    j_graph['nodes'][coding_node_id]['coding'] = coding_string
    return j_graph

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
    graph_count = 0
    with open(conllu_file, 'r', encoding='utf-8') as file:
        for line in file:
            if line.strip() == '':  # Each empty line indicates the end of a graph
                graph_count += 1
    return graph_count

def main(query_file, conllu_file, args):
    # Read and parse the GREW query
    query_content = read_grew_query(query_file)
    print(f"Query:\n{query_content}")
    
    # Match sentences in the CoNLL-U file against the GREW query
    matched_sentences = match_sentences_with_query(conllu_file, query_content)
    
    # Output matched sentences
    for graph in matched_sentences:
        pass

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