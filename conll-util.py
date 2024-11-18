#!/usr/bin/python3

__author__ = "Achim Stein"
__version__ = "0.9"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "6.11.24"
__license__ = "GPL"

"""
This script is a Python implementation of some functions of my Perl script conll.pl
"""

import argparse
import re
import os
import sys

def read_conllu(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    return content.split('\n\n')  # Split sentences by blank lines

def split_sentences(sentences, first, last=None, infile="input.conllu", suffix="conllu"):
    counter = 0
    out_file = None
    if last == "cut":
        output_file = f"cut_{first}.{suffix}"
        with open(output_file, 'w', encoding='utf-8') as out:
            if first - 1 < len(sentences):
                out.write(sentences[first - 1] + '\n\n')
        print(f"Cut sentence {first} written to {output_file}")
    elif last:  # Extract sentences from 'first' to 'last'
        output_file = f"extract_{first}_to_{last}.{suffix}"
        with open(output_file, 'w', encoding='utf-8') as out:
            for i in range(first - 1, min(last, len(sentences))):
                out.write(sentences[i] + '\n\n')
        print(f"Extracted sentences {first} to {last} written to {output_file}")
    else:  # Split every 'first' sentences
        for i, sentence in enumerate(sentences, 1):
            if (i - 1) % first == 0:
                if out_file:
                    out_file.close()
                counter += 1
                output_file = f"{infile.rsplit('.', 1)[0]}_{counter}.{suffix}"
                out_file = open(output_file, 'w', encoding='utf-8')
                print(f"Writing to {output_file}")
            out_file.write(sentence + '\n\n')
        if out_file:
            out_file.close()

def main():
    parser = argparse.ArgumentParser(description="Utility for splitting or extracting CoNLL-U files")
    parser.add_argument("file", help="Input CoNLL-U file")
    parser.add_argument("-S", "--split", help="Split options in the format 'n(,m)' or 'n,cut'", required=True)
    args = parser.parse_args()

    split_match = re.match(r"(\d+),?(\d+|cut)?", args.split)
    if not split_match:
        print("Invalid format for --split option. Use 'n', 'n,m' or 'n,cut'")
        sys.exit(1)
    
    first = int(split_match.group(1))
    last = split_match.group(2) if split_match.group(2) else None
    last = int(last) if last and last != "cut" else last

    sentences = read_conllu(args.file)
    split_sentences(sentences, first, last, infile=args.file)

if __name__ == "__main__":
    main()