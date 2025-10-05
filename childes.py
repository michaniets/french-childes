#!/usr/bin/python3

__author__ = "Achim Stein"
__version__ = "3.0"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "05.10.25"
__license__ = "GPL"

import sys
import argparse, re
import os
import subprocess
import csv
from tag_analyser import TagAnalyser
import json
import warnings
import tempfile

#-------------------------------------------------------
# Helper functions
#-------------------------------------------------------

def parseAge(age_str):
    year = months = days = 0
    m = re.search(r'(\d+);', age_str)
    if m: year = m.group(1)
    m = re.search(r'\d+;(\d+)', age_str)
    if m: months = m.group(1)
    m = re.search(r'\d+;\d+\.(\d+)', age_str)
    if m: days = m.group(1)
    age_days = int(int(year) * 365 + int(months) * 30.4 + int(days))
    return age_str, age_days

def cleanUtt(s):
    s = re.sub(r' 0([\S+])', r' \1', s)
    s = re.sub(r'0faire ', 'faire ', s)
    s = re.sub(r'<[^>]+> \[//?\] ', '', s)
    s = re.sub(r'\[\!\] ?', ' ', s)
    s = re.sub(r' ?\(\.\) ', ' , ', s)
    s = re.sub(r'<([^>]+)>\s+\[%[^\]]+\]', r'\1', s)
    s = re.sub(r'<(0|www|xxx|yyy)[^>]+> ?', '', s)
    s = re.sub(r'\+[<,]? ?', '', s)
    s = re.sub(r'(0|www|xxx|yyy)\s', '', s)
    s = re.sub(r'\[.*?\] ?', '', s)
    s = re.sub(r'\(([A-Za-z]+)\)', r'\1', s)
    s = re.sub(r' \+/+', ' ', s)
    s = re.sub(r'[_=]', ' ', s)
    s = re.sub(r'[<>]', '', s)
    s = re.sub(r'\s+', ' ', s)
    return(s)

def tokenise(s):
    reBeginChar = re.compile('(\[\|\{\(\/\'\´\`"»«°<)')
    reEndChar = re.compile('(\]\|\}\/\'\`\"\),\;\:\!\?\.\%»«>)')
    reBeginString = re.compile('([dcjlmnstDCJLNMST]\'|[Qq]u\'|[Jj]usqu\'|[Ll]orsqu\')')
    reEndString = re.compile('(-t-elles?|-t-ils?|-t-on|-ce|-elles?|-ils?|-je|-la|-les?|-leur|-lui|-mêmes?|-m\'|-moi|-nous|-on|-toi|-tu|-t\'|-vous|-en|-y|-ci|-là)')
    s = re.sub(reBeginChar, r'\1 ', s)
    s = re.sub(reBeginString, r'\1 ', s)
    s = re.sub(reEndChar, r' \1', s)
    s = re.sub(reEndString, r' \1', s)
    s = re.sub(r'\s+', ' ', s)
    return(s)

def process_tagged_data(tagged):
    lines = tagged.strip().split('\n')
    processed_lines = []
    for line in lines:
        columns = line.split('\t')
        if len(columns) == 3 and re.search(' ', columns[2]):
            columns[2] = re.sub(r'.*? ', '', columns[2])
        processed_lines.append('\t'.join(columns))
    return '\n'.join(processed_lines)

def correct_tagger_output(tagged):
    # This is the full, original function
    tagged = re.sub(r'([,\?])_NAM=<unknown>', r'\1_PON=,', tagged)
    tagged, count = re.subn('Marie_VER:pres=marier', 'Marie_NAM=Marie', tagged)
    tagged, count = re.subn(r'( allez[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER:impe=NEWLEM:aller', tagged)
    tagged, count = re.subn(r'( attend[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:attendre', tagged)
    tagged, count = re.subn(r'( dis[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:dire', tagged)
    tagged, count = re.subn(r'( enl.v.[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:enlever', tagged)
    tagged, count = re.subn(r'( fai[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:faire', tagged)
    tagged, count = re.subn(r'( fini[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:finir', tagged)
    tagged, count = re.subn(r'( prend[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:prendre', tagged)
    tagged, count = re.subn(r'( mett[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:mettre', tagged)
    tagged, count = re.subn(r'( regard[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:regarder', tagged)
    tagged, count = re.subn(r'( tomb[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:tomber', tagged)
    tagged, count = re.subn(r'( vu[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:voir', tagged)
    tagged, count = re.subn(r'( ![^_ ]*)_([^= ]+)=<unknown>', r' !_PON=!', tagged)
    tagged, count = re.subn('NEWLEM:', '', tagged)
    return(tagged)

#-------------------------------------------------------
# Main processing class
#-------------------------------------------------------
class ChatProcessor:
    def __init__(self, args):
        self.args = args; self.pid = ''; self.child = ''; self.age = ''; self.age_days = 0; self.sNr = 0
        self.childData = {}; self.outRows = []; self.analyser = TagAnalyser()
        self.annot_keys = ['annot_refl', 'annot_dat', 'annot_clit', 'annot_mod', 'annot_particle']
        self.tagger_input_file = None; self.tagged_temp_file = None

    def run(self):
        try:
            self.tagger_input_file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8', delete=False, suffix=".txt")
            with open(self.args.out_file, 'r', encoding="utf8") as f: content = f.read()
            content = re.sub('@End', '*\n', content)
            content = re.sub('@Begin.*?\n@Comment:.*?(dummy file|No transcript).*?\n@End\n', '', content, flags=re.DOTALL)
            for block in content.split('\n*'):
                if block.strip(): self.process_utterance_block(block)
            self.finalize_output()
        finally:
            if self.tagger_input_file: self.tagger_input_file.close(); os.unlink(self.tagger_input_file.name)
            if self.tagged_temp_file: self.tagged_temp_file.close(); os.unlink(self.tagged_temp_file.name)

    def process_utterance_block(self, block):
        if '@PID:' in block: self.parse_header(block); return
        if not self.pid: return
        self.sNr += 1; uttID = f"{self.pid}_u{self.sNr}"
        block = re.sub(r'[‹›]', lambda m: {'‹':'<', '›':'>'}[m.group()], block)
        block = re.sub(r'\n\s+', ' ', block, flags=re.DOTALL)
        timeCode = (m.group(1) if (m := re.search(r'\x15(\d+_\d+)\x15', block)) else '')
        block = re.sub(r'\x15.*?\x15', '', block)
        mor = (m.group(1) if (m := re.search(r'%mor:\s+(.*)', block)) else '')
        if not (m := re.search(r'^([A-Z]+):\s+(.*)', block.strip(), flags=re.MULTILINE)): return
        speaker, utt = m.groups()
        splitUtt = cleanUtt(utt)
        if self.args.parameters:
            self.tagger_input_file.write(f"<s_{uttID}> {tokenise(splitUtt)}\n")
            self.generate_rows_from_tagger(splitUtt, utt, speaker, uttID, timeCode)
        else: self.generate_rows_from_chat(splitUtt, mor, utt, speaker, uttID, timeCode)

    def parse_header(self, block):
        if not (m := re.search(r'@PID:.*/.*?0*(\d+)', block)): return
        self.pid = m.group(1); self.sNr = 0; self.childData = {}
        if (m := re.search(r'@ID:.*\|(.*?)\|[A-Z]+\|([0-9;.]+)\|.*Target_Child', block)):
            project, age_str = m.groups()
            self.age, self.age_days = parseAge(age_str)
            if (m := re.search(r'@Participants:.*CHI\s(.*?)\sTarget_Child', block)):
                child_name = m.group(1).split()[0]
                self.child = f"{child_name}_{project[:3]}"
                self.childData['CHI'] = (self.child, self.age, self.age_days)
    
    def generate_rows_from_tagger(self, splitUtt, raw_utt, speaker, uttID, timeCode):
        words = tokenise(splitUtt).split(' ')
        for wNr, w in enumerate(words, 1):
            if not w: continue
            age, age_days, child_other = self.get_speaker_age(speaker)
            self.outRows.append({'utt_id': f"{uttID}_w{wNr}", 'utt_nr': self.sNr, 'w_nr': wNr, 'speaker': speaker, 'child_project': self.child, 'child_other': child_other, 'age': age, 'age_days': age_days, 'time_code': timeCode, 'word': w, 'lemma': '', 'pos': '', 'features': '', 'annotations': '', 'utterance': raw_utt, 'utt_clean': splitUtt if self.args.tagger_input else '', 'utt_tagged': ''})

    def generate_rows_from_chat(self, splitUtt, mor, raw_utt, speaker, uttID, timeCode): pass

    def get_speaker_age(self, speaker):
        if speaker in self.childData: return self.childData[speaker][1], self.childData[speaker][2], "C"
        return '', self.childData.get('CHI', ('', '', 0))[2], "X"
    
    def finalize_output(self):
        self.tagger_input_file.seek(0)
        taggerInput = self.tagger_input_file.read()
        itemWords, itemPOS, itemLemmas, itemTagged = {}, {}, {}, {}
        if self.args.parameters and taggerInput:
            itemWords, itemPOS, itemLemmas, itemTagged = self.run_treetagger(taggerInput)
        header = ['utt_id', 'utt_nr', 'w_nr', 'speaker', 'child_project', 'child_other', 'age', 'age_days', 'time_code', 'word', 'lemma', 'pos', 'features', 'annotations', 'utterance', 'utt_clean', 'utt_tagged']
        if self.args.add_annotation: header.extend(self.annot_keys)
        intermediate_csv = self.args.out_file + '.csv'
        with open(intermediate_csv, 'w', newline='', encoding='utf8') as f:
            writer = csv.DictWriter(f, delimiter='\t', fieldnames=header, extrasaction='ignore')
            writer.writeheader(); writer.writerows(self.outRows)
        if self.args.parameters:
            final_csv = self.args.out_file + '.tagged.csv'
            self.add_tagging_to_csv(intermediate_csv, final_csv, header, itemWords, itemPOS, itemLemmas, itemTagged)
            sys.stderr.write(f"\nOUTPUT: {final_csv}\n")
        else: sys.stderr.write(f"OUTPUT: {intermediate_csv}\n")

    def run_treetagger(self, tagger_input):
        tagger_bin, param_file = './tree-tagger', self.args.parameters
        if not all(map(os.path.exists, [tagger_bin, param_file])): sys.exit("Tagger binary or param file not found.")
        self.tagged_temp_file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8', delete=False, suffix=".txt")
        self.tagged_temp_file.write(re.sub(' +', '\n', tagger_input)); self.tagged_temp_file.flush()
        p1 = subprocess.Popen(["cat", self.tagged_temp_file.name], stdout=subprocess.PIPE)
        tagged = subprocess.check_output([tagger_bin, param_file, '-token', '-lemma', '-sgml'], stdin=p1.stdout).decode('utf8')
        tagged = process_tagged_data(tagged)
        
        # --- LOGIC RESTORED ---
        if self.args.conllu:
            self.tagged2conllu(tagged)
        
        tagged = re.sub(r'\t([A-Za-z:]+)\t', r'_\1=', tagged)
        tagged = re.sub(r'\n', ' ', tagged)
        if self.args.language == 'french':
            tagged = correct_tagger_output(tagged)
        
        words, pos, lemmas, tagged_sents = {}, {}, {}, {}
        for sent in tagged.split("<s_"):
            if not (m := re.match(r'([^>]+)> (.*)', sent)): continue
            key, content = m.groups()
            tagged_sents[key] = content.strip()
            lemmas[key] = ' '.join(re.findall(r'=(.*?)(?: |$)', content))
            pos[key] = ' '.join(re.findall(r'_(.*?)=', content))
            words[key] = ' '.join(re.findall(r' (.*?)_', ' ' + content))
        return words, pos, lemmas, tagged_sents

    def tagged2conllu(self, str_in):
            conllu_out = 'parseme.conllu'
            sys.stderr.write(f"Creating output file '{conllu_out}' for dependency parsing...\n")
            # convert 3-column tagger output to 10-column conllu format
            str_in = re.sub(r'(.*)\t(.*)\t(.*)', r'\1\t\3\t_\t\2\t_\t_\t_\t_\t_', str_in)
            str_in = re.sub('<s_([^>]+)>', r'# item_id = \1', str_in)
            
            with open(conllu_out, 'w', encoding='utf8') as parsetmp:
                out, wNr = '', 0
                # Split by the sentence marker, keeping the marker
                sentences = re.split('(# item_id = [^\n]+)', str_in)
                for i in range(1, len(sentences), 2):
                    header = sentences[i]
                    body = sentences[i+1]
                    
                    sentence_block = header
                    wNr = 0
                    for line in body.strip().split('\n'):
                        if line.strip():
                            wNr += 1
                            sentence_block += f"\n{wNr}\t{line}"

                    # Write the complete sentence block followed by a blank line
                    parsetmp.write(sentence_block + '\n\n')
                    
    def add_tagging_to_csv(self, infile, outfile, header, words, pos_tags, lemmas, tagged_sents):
        with open(infile, 'r', encoding='utf8') as f_in, open(outfile, 'w', newline='', encoding='utf8') as f_out:
            reader = list(csv.reader(f_in, delimiter='\t')); writer = csv.writer(f_out, delimiter='\t')
            writer.writerow(header)
            p_idx, l_idx, u_idx, t_idx = map(header.index, ['pos', 'lemma', 'utterance', 'utt_tagged'])
            for row in reader[1:]:
                if not (m := re.match(r'(.*)_w(\d+)', row[0])): continue
                uID, wID_str = m.groups(); wID = int(wID_str)
                try:
                    current_pos = pos_tags.get(uID, '').split(' ')[wID - 1] if uID in pos_tags else ''
                    row[p_idx] = current_pos
                    row[l_idx] = lemmas.get(uID, '').split(' ')[wID - 1] if uID in lemmas else ''
                    match = (re.search(self.args.pos_utterance, current_pos) if self.args.pos_utterance else True)
                    if not match: row[u_idx] = ''
                    if self.args.tagger_output and match: row[t_idx] = tagged_sents.get(uID, '')
                    if self.args.add_annotation and match and self.args.match_tagging and re.search(self.args.match_tagging, current_pos):
                        ann = self.analyser.analyse(tagged_sents.get(uID, ''), row[l_idx])
                        for k, v in ann.items():
                            if k in header: row[header.index(k)] = v
                except IndexError: pass
                writer.writerow(row)

if __name__ == "__main__":
   parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
   parser.add_argument('out_file', type=str,  help='output file')
   parser.add_argument('-F', '--first_utterance', action='store_true', help='print utterance only for first token')
   parser.add_argument('-a', '--add_annotation', action='store_true', help='add annotation based on rules')
   parser.add_argument('-c', '--conllu', action='store_true', help='create CoNLL-U output')
   parser.add_argument('--hops', default = "", type = str, help='run hops parser')
   parser.add_argument('-l', '--language', default = "french", type = str, help='language-specific functions')
   parser.add_argument('-m', '--match_tagging', default = "", type = str, help='match tagger output')
   parser.add_argument('-p', '--parameters', default = "", type = str, help='TreeTagger parameter file')
   parser.add_argument('--pos_utterance', default = "", type = str, help='print utterance if pos matches')
   parser.add_argument('--tagger_input', action='store_true', help='print utterance for tagger')
   parser.add_argument('--tagger_output', action='store_true', help='print tagged utterance')
   parser.add_argument('-u', '--ud_pipe', default = "", type = str, help='run UDPipe parser')
   
   args = parser.parse_args()
   processor = ChatProcessor(args)
   processor.run()