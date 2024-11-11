#!/usr/local/bin/python3

"""
match_list geht nicht. 

1. jeden Satz matchen


"""

__author__ = "Achim Stein"
__version__ = "0.1"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "11.11.24"
__license__ = "GPL"

import re
import argparse
from grewpy import Corpus, Request, CorpusDraft #Graph

def read_grew_query(query_file):
    # Read Grew query file.
    with open(query_file, 'r', encoding='utf-8') as f:
        query_content = f.read()
    return query_content

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
    matches_for_pattern = {}
    for nr in patterns.keys():
        print(f"  Searching corpus query no. {nr}...")
        request = Request.parse(patterns[nr])
        match_list = corpus.search(request)
        print(f"    Found {len(match_list)} matches for query") #:\n{patterns[nr]}
        matches_for_pattern[nr] = match_list  # store the list of matches in a dict with patter nr as key
        for match in match_list:  # TODO not needed
            sent_id = match['sent_id']
            if sent_id not in unique_ids:  # set() allows fast membership testing
                unique_ids.add(sent_id)  # Add the sent_id to the set
                all_matches.append(match)  # Append the full match object to the list
    print(f"Found {len(unique_ids)} matches for all the patterns")
#    return unique_ids, all_matches
    return matches_for_pattern

def match_sentences_with_query_ALT(conllu_file, query_content):
    """
    Match each sentence against queries. Add codings if present.
    """
    corpus = init_grew_corpus(conllu_file)
    codings, patterns = parse_grew_query(query_content)
#    unique_ids, all_matches = find_matches(corpus, patterns)
    matches_for_pattern = find_matches(corpus, patterns)
    corpus.apply(lambda g: print_or_code(g, match_ids))
    # Iterate through each matching graph
    match_nr = 0 
    matched_graphs = []
    for nr in matches_for_pattern.keys():
        all_matches = matches_for_pattern[nr]
        for match in all_matches:
            match_nr += 1
            sent_id = match['sent_id']
            graph = corpus.get(sent_id)  # get graph for this id
            if match_nr > args.max:
                print(f"Maximum match number {args.max} reached: search stopped.")
                return matched_graphs
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

def match_sentences_with_query(conllu_file, query_content):
    grew_corpus = init_grew_corpus(conllu_file)
    codings, patterns = parse_grew_query(query_content)
#    unique_ids, all_matches = find_matches(corpus, patterns)
    matches_for_pattern = find_matches(grew_corpus, patterns)
    print("Make draft corpus")
    # Convert it to a CorpusDraft if it isn't already
    corpus = CorpusDraft(grew_corpus) if not isinstance(grew_corpus, CorpusDraft) else grew_corpus
    print("Done.")
    # corpus is a dict of sent_id:GraphObject
    for sent_id, graph in corpus.items():
        add_coding(graph, sent_id, matches_for_pattern[1])

def add_coding(graph, sent_id, match_ids):
    """
    The Corpus itself seems to serve as a container for Graph objects, without direct access to the metadata of each graph.
    We need to retrieve each Graph individually and then access its meta attribute using .json_data()
    QUESTION: how can I assign modified data back to the graph ???
    """
    # Only apply coding if this sent_id is in the list of matches
    j_graph = graph.json_data()
    for match in match_ids:
        #print(f" sent_id = {sent_id} >>>{m}")
        if sent_id == match['sent_id']:
            print(f" matching nodes: {match['matching']}")
            print(f"JSON: {graph.json_data()['meta']}")
            # Perform modifications
            j_graph['meta']["coding"] = '' # add empty coding line
            print(f" sent_id = {sent_id} >>>{match['matching']}\n   New Graph: {j_graph.to_conll()}")
        
    # Return the modified graph (or unmodified if no match)
    return graph

def get_meta(corpus, sent_id):
    # get meta from Grew corpus object for a sentence
    meta = corpus['meta'][sent_id]
    return meta

def add_coding_ALT(match, j_graph, coding, pattern):
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

def init_grew_corpus(conllu_file):
    # init Grew corpus object (this is slow: print estimate)
    count = count_graphs(conllu_file)
    per_min = 450000  # processed sentences per min on Mac M2
    secs = int(count / per_min * 60)
    minutes, seconds = divmod(secs, 60)
    print(f"Estimated time to read {count} graphs: {round(minutes,0)}m {seconds}s")
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

def main(query_file, conllu_file, args):
    # Read and parse the Grew query
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