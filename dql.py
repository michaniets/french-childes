#!/usr/local/bin/python3

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

def parse_grew_query(query_file): 
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

def match_sentences_with_query(conllu_file, query_content):
    per_min = 450000  # time for loading conllu in Grew Corpus object
    count = count_graphs(conllu_file)
    secs = int(count / 450000 * 60)
    minutes, seconds = divmod(secs, 60)
    print(f"Reading corpus: {count} graphs ~ {round(minutes,0)}'{seconds}\"")
    # init Grew objects
    corpus = Corpus(conllu_file)  # corpus file as Corpus object (slow)
    request = Request.parse(query_content)  # query as Request object
    # count
    match_count = corpus.count(request)
    print(f"{match_count} graphs match this request")
    # search   
    print("Matching query against corpus...")
    match_list = corpus.search(request)
  
    # Iterate through each matching graph
    match_nr = 0 
    matched_graphs = []
    for match in match_list:
        match_nr += 1
        sent_id = match['sent_id']
        graph = corpus.get(sent_id)  # get graph for this id
        if match_nr > args.max:
            print(f"Maximum match number {args.max} reached: search stopped.")
            return matched_graphs
        nodes = match['matching']['nodes'] # word IDs matching nodes in query
        print(f"\n===> Match nr = {match_nr} | nodes = {nodes}\n  {match}")
        matched_graphs.append(graph)
        print(graph.to_sentence())
        j_graph = graph.json_data()  # graph in JSON format
        # add coding data
        add_coding(match, j_graph, query_content)
        # add utterance to meta
        get_misc_string(graph, "1")
        j_graph["meta"]["utterance"] = graph.to_sentence()
        print(graph.to_conll())  # Print matched sentences in CoNLL-U format

#        sent_id = match['sent_id']
#        nodes = match['matching']['nodes']
    return matched_graphs

def add_coding(match, j_graph, query_content):
    coding = parse_grew_query(query_content)
    j_graph["meta"]["coding"] = '' # add empty coding line
    if coding:
        # add coding to meta
        addlemma_node_id = match['matching']['nodes'][coding['addlemma']] # id of coding node
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