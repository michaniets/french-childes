#!/usr/bin/python3

# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "requests",
#     "conllu",
#     "grewpy"
# ]
# ///

__author__ = "Achim Stein"
__version__ = "5.7"
__status__ = "5.9.26"
__license__ = "GPL"

import sys
import argparse, re
import os
import subprocess
import csv
import tempfile
import gzip
import io
import time
import requests
from conllu import parse
#from grewpy import Corpus, GRS

# Robust Grew import 
try:
    import grewpy
    from grewpy import Corpus, GRS
    # Explicit init inside the try block
    grewpy.init() 
except Exception as e:
    sys.stderr.write(f"  [INFO] Initial Grew connection failed. Retrying in 1s...\n")
    time.sleep(1)
    try:
        # Retry the import and initialization
        import grewpy
        from grewpy import Corpus, GRS
        grewpy.init()
    except Exception as final_e:
        sys.stderr.write(f"  [WARNING] Grew backend failed to initialize: {final_e}\n")
        sys.stderr.write("            Rewrite rules will not work.\n")
        sys.stderr.write("   TRY THIS:\n")
        sys.stderr.write("     - Check if you have a VPN running: disconnecting from the VPN might help.\n")
        sys.stderr.write("     - Check if grew_backend is installed correctly (for your Python version), maybe re-install\n\n")

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
    """
    cleans standard CHAT markup from utterances to prepare them for NLP tools
    revised v4.4
    """
    s = re.sub(r' 0([\S+])', r' \1', s)           # 0word -> word
    s = re.sub(r'0(faire|ne) ', '\1 ', s)           # Specific fix for 0faire, 0ne
    s = re.sub(r'&=li ', ' ', s)                   # Remove non-canonical liaison markers (mostly in Lyon project)
    s = re.sub(r'<[^>]+> \[//?\] ', '', s)        # Remove retracings <...> [//]
    s = re.sub(r'\[\!\] ?', ' ', s)               # Remove stressing [!]
    s = re.sub(r' ?\(\.+\) ', ' ', s)            # Pauses (.) (..) -> remove
    s = re.sub(r'<([^>]+)>\s+\[%[^\]]+\]', r'\1', s) # Keep text before comment <text> [% comment]
    s = re.sub(r'<(0|www|xxx|yyy)[^>]+> ?', '', s)   # Remove unintelligible marked with <>
    s = re.sub(r'\+[<,]? ?', '', s)               # Remove +< and +,
    s = re.sub(r'(0|www|xxx|yyy)\s', '', s)          # Remove unintelligible words
    s = re.sub(r'\[.*?\] ?', '', s)               # Remove all other bracketed content [...]
    s = re.sub(r'\(([A-Za-z]+)\)', r'\1', s)      # Keep text inside parentheses (word) -> word
    s = re.sub(r' \+/+', ' ', s)                  # Remove +/
    # added v4.4
    s = re.sub(r'@[a-z:0-9]+', '', s)             # Remove special CHAT suffixes like @c, @s:eng
    s = re.sub(r'&[\S]+', '', s)                  # Remove phonological fragments like &mm, event codes like &=laugh
    # must run AFTER the &-removal above: &=word's '=' would otherwise be turned into a
    # space first, splitting it into a bare '&' plus a stray real-looking word ('& laugh')
    s = re.sub(r'[_=]', ' ', s)                   # Replace _ and = with space
    # final cleanups
    s = re.sub(r'[<>]', '', s)                    # Remove remaining angle brackets
    s = re.sub(r'\s+', ' ', s)                    # Normalize spaces
    return(s.strip())

def process_tagged_data(tagged):
    lines = tagged.strip().split('\n')
    processed_lines = []
    for line in lines:
        columns = line.split('\t')
        if len(columns) == 3 and re.search(' ', columns[2]):
            columns[2] = re.sub(r'.*? ', '', columns[2])
        processed_lines.append('\t'.join(columns))
    return '\n'.join(processed_lines)
    
#-------------------------------------------------------
# HTML export class for UD parsed data
#-------------------------------------------------------
class HtmlExporter:
    """Generates a chunked, styled HTML corpus with dependency trees."""
    def __init__(self, output_dir, file_basename, chunk_size=1000):
        self.output_dir = output_dir
        self.file_basename = file_basename
        self.project = ''  # rather than file_basename, for html filenames
        self.chunk_size = chunk_size
        os.makedirs(self.output_dir, exist_ok=True)
        self.html_head = '''<!DOCTYPE html>
<html>
  <meta http-equiv="Content-type" content="text/html; charset=utf-8" />
  <head>
    <title>CHILDES Parse: %s</title>
    <style>
      body { font-family: sans-serif; }
      .parse p {
        font-family: monospace;
        white-space: pre;
        margin: 0;
        letter-spacing: 0;
      }
      .coding {
        background: #f0f0f0; color: black; font-family: "Courier New", Courier, monospace;
        font-size: 12px; padding: 5px; border-left: 3px solid blue; margin-bottom: 1em;
      }
      .nav-header { margin-bottom: 2em; text-align: center; }
      .nav-footer { margin-top: 2em; text-align: center; }
      .a { color:black; font-weight: bold; }
      .v { background-color:yellow; }
      .l { color:magenta; }
      .r { color:red; }
      .u { color:DarkGreen; }
      .x { color:Olive; }
      .d { color:blue; }
    </style>
  </head>
  <body>
'''
        self.html_foot = '</body></html>'

    def _format_tree_as_html(self, tree_str, tokenlist):
        deps = {token["id"]: token["head"] for token in tokenlist}
        lines = sorted(tree_str.strip().split("\n"), key=lambda line: int(re.search(r'\[(\d+)\]', line).group(1)))
        
        rebuilt_lines = []
        for line in lines:
            match = re.search(r'\[(\d+)\]$', line)
            if match:
                wID = int(match.group(1))
                headID = deps.get(wID, 0)
                line = line.replace(f"[{wID}]", f"[{wID}:{headID}]")
            
            leading_spaces = len(line) - len(line.lstrip(' '))
            indented_line = '.' * leading_spaces + line.lstrip()
            rebuilt_lines.append(indented_line)

        html_tree = "\n".join(rebuilt_lines)
        
        html_tree = re.sub(
            r'(\.*)\(deprel:(.*?)\)(.*?)\[(\d+):(\d+)\]',
            lambda m: f"{int(m.group(4)):02d}{m.group(1)}{m.group(3)} <span class=d>{m.group(2)}</span>&#8594;{m.group(5)}",
            html_tree,
            flags=re.MULTILINE
        )
        html_tree = re.sub(r'lemma:(.*?) ', r'<span class=l>\1</span> ', html_tree)
        html_tree = re.sub(r'upos:(VER[A-Z]+) ', r'<span class=v>\1</span> ', html_tree)
        html_tree = re.sub(r'upos:(.*?) ', r'<span class=u>\1</span> ', html_tree)
        html_tree = re.sub(r'xpos:(.*?) ', r'<span class=x>\1</span> ', html_tree)
        html_tree = re.sub(r'form:(.*?) ', r'<b>\1</b> ', html_tree)
        return html_tree

    def export(self, parsed_conllu_str, original_rows):
        sentences = parse(parsed_conllu_str)
        
        header_info_map = {}
        for row in original_rows:
            utt_id_base = re.match(r'(.*)_w\d+', row['utt_id']).group(1)
            if utt_id_base not in header_info_map:
                header_info_map[utt_id_base] = {
                    'child_project': row['child_project'],
                    'speaker': row['speaker'],
                    'age': row['age'] if row['age'] else '_',
                    'utterance': row['utterance']
                }

        html_links = {}
        total_chunks = (len(sentences) + self.chunk_size - 1) // self.chunk_size
        for chunk_id in range(total_chunks):
            sys.stderr.write(f"\rWriting HTML files to {self.output_dir} for chunk {chunk_id+1}/{total_chunks}")
            sys.stderr.flush()
            start_index = chunk_id * self.chunk_size
            end_index = start_index + self.chunk_size
            chunk_sentences = sentences[start_index:end_index]
            
            html_filename = f"{self.project[:3]}{chunk_id}.html" # keep as short as possible
            html_filepath = os.path.join(self.output_dir, html_filename)

            with open(html_filepath, 'w', encoding='utf8') as f:
                # HTML header
                f.write(self.html_head % self.file_basename)
                # Navigation header
                nav_header = ''
                if chunk_id > 0:
                    prev_file = f"{self.project[:3]}{chunk_id - 1}.html"
                    nav_header += f'<a href="{prev_file}">&laquo; Previous Page</a>'
                if chunk_id > 0 and chunk_id < total_chunks - 1:
                    nav_header += ' | '
                nav_header += f" <b> CHILDES project {self.project}</b> | "
                if chunk_id < total_chunks - 1:
                    next_file = f"{self.project[:3]}{chunk_id + 1}.html"
                    nav_header += f'<a href="{next_file}">Next Page &raquo;</a>'
                nav_header = '<div class="nav-header">' + nav_header + '</div>'
                f.write(nav_header)


                for sentence in chunk_sentences:
                    if 'item_id' not in sentence.metadata: continue
                    utt_id = sentence.metadata['item_id']
                    
                    info = header_info_map.get(utt_id, {})
                    child_project = info.get('child_project', 'N/A')
                    html_filename = f"{self.project[:3]}{chunk_id}.html"
                    speaker = info.get('speaker', 'N/A')
                    age = info.get('age', '_')
                    raw_utterance = info.get('utterance', '[Utterance not found]')
                    
                    html_links[utt_id] = {'local': html_filepath, 'file': html_filename}
                    
                    for token in sentence:
                        if token['lemma'] is None:
                            token['lemma'] = '_'
                        if token['xpos'] is None:
                            token['xpos'] = '_'

                    old_stdout = sys.stdout; sys.stdout = captured_output = io.StringIO()
                    try:
                        sentence.to_tree().print_tree()
                    except Exception as e:
                        sys.stderr.write(f"Could not generate tree for {utt_id}: {e}\n")
                    sys.stdout = old_stdout; tree_str = captured_output.getvalue()
                    
                    if not tree_str: continue
                    formatted_tree = self._format_tree_as_html(tree_str, sentence)

                    f.write(f'\n<a name="{utt_id}"></a><hr>\n')  # anchor
                    if speaker == "CHI":
                        f.write(f"<h3>ID: {utt_id} | {child_project} | <span class=r>{speaker} | {age}</span></h3>\n")
                    else:
                        f.write(f"<h3>ID: {utt_id} | {child_project} | {speaker}</h3>\n")
                    escaped_utt = raw_utterance.replace('<', '&lt').replace('>', '&gt')
                    f.write(f'<p class="coding">{escaped_utt}</p>\n')
                    f.write(f'<div class="parse"><p>{formatted_tree}</p></div>\n')

                # copy header to footer
                nav_footer = '<div class="nav-footer">' + nav_header + '</div>'
                f.write(nav_footer)
                f.write(self.html_foot)
        sys.stderr.write("\n")

        return html_links

#-------------------------------------------------------
# Main processing class
#-------------------------------------------------------
class ChatProcessor:
    def __init__(self, args):
        self.args = args
        self.pid = ''
        self.child = ''
        self.age = ''
        self.age_days = 0
        self.sNr = 0 # This is now a global utterance counter
        self.childData = {}
        self.outRows = []
        # Per-utterance metadata for the --api_model-only path (no --parameters):
        # tokenisation is deferred to UDPipe itself, so there is no per-word grid to
        # append to outRows until the parsed CoNLL-U comes back. See
        # record_utterance_for_parsing()/restamp_presegmented_output().
        self.pendingUtterances = {}
        self.tagger_input_file = None
        self.tagged_temp_file = None
        self.conllu_input_file = None
        self.presegmented_input_file = None
        self.html_exporter = None
        if args.html_dir:
            file_basename = os.path.basename(args.chat_file)
            file_basename = os.path.splitext(file_basename)[0]
            self.html_exporter = HtmlExporter(args.html_dir, file_basename, chunk_size=args.chunk_html)

    def strip_transcription_noise(self, s):
        """
        Removes language/corpus-specific transcription noise (timed pauses,
        intonation arrows, phoneme-lengthening colons, vocalisation/event codes)
        that is not part of tokenisation proper. Applied once, right after
        cleanUtt(), before the result is captured as '# text'/utt_clean AND
        handed to tokenise() for the tagger/FORM input - so both stay in sync
        instead of '# text' retaining noise that tokenise() alone used to strip.
        """
        if hasattr(self, 'language') and re.search(r'eng|english', self.language):
            # English UK: Forrester has arrows in utterances (for intonation?)
            s = re.sub(r" ?[↗→↓∇] ?", r"", s)  # *FAT:	of the thunder ↗
            s = re.sub(r"(\w):+(\w)", r"\1\2", s)  # n::::O →
            s = re.sub(r"\n\s+\(\d\.\d\).*", r"", s)    # *FAT:	that good darlin' ↗ 10340_13805<BR>	(24.8) 13805_34059
            s = re.sub(r" ?\(\d\.\d\)", r"", s)  # ⌊eh a:::o⌋ → (0.4)
            # English UK Belfast
            s = re.sub(r" ?‡", r"", s)  # oh ‡ aren't they gorgeous !
            # English UK Wells
            s = re.sub(r" ?\(\d+\.\d*\)", r"", s)   # *CHI:	(5.) &=laugh (5.) &=noise (4.) &=noise .
            s = re.sub(r" ?&=\w+", r"", s)          # *CHI:	(5..) &=laugh (5..) &=noise (4..) &=noise .
            s = re.sub(r'\s+', ' ', s).strip()
        return s

    def tokenise(self, s):
        """
        Tokenises a string, with language-specific rules.
        Normally, in CHAT format punctuation should be separated by spaces already. (BeginChar/EndChar)
        German clitics can't be handled: habs, gehts, etc.
        """
        if hasattr(self, 'language') and re.search(r'fra|french', self.language):
            reBeginChar = re.compile(r'([\|\{\(\/\´\`"»«°<])') 
            reEndChar = re.compile(r'([\]\|\}\/\`\"\),\;\:\!\?\.\%»«>])(?=\s|$)')   # also if followed by end of line
            reBeginString = re.compile(r'([dcjlmnstDCJLNMST]\'|[Qq]u\'|[Jj]usqu\'|[Ll]orsqu\')') 
            reEndString = re.compile(r'(-t-elles?|-t-ils?|-t-on|-ce|-elles?|-ils?|-je|-la|-les?|-leur|-lui|-mêmes?|-m\'|-moi|-nous|-on|-toi|-tu|-t\'|-vous|-en|-y|-ci|-là)') 
            s = re.sub(reBeginString, r'\1 ', s)
            s = re.sub(reBeginChar, r'\1 ', s)
            s = re.sub(reEndChar, r' \1', s)
            s = re.sub(reEndString, r' \1', s)
            s = re.sub(r'\s+', ' ', s)
        # Add other languages here with 'elif self.args.language == "other_language":'
        elif hasattr(self, 'language') and re.search(r'ita|italian', self.language):
            # Punctuation and delimiters like French
            s = re.sub(r'([\|\{\(\/\´\`"»«°<])', r'\1 ', s)
            s = re.sub(r'([\]\|\}\/\`\"\),\;\:\!\?\.\%»«>])(?=\s|$)', r' \1', s)
            # Split apostrophe preceding a letter: l', un', c', d', gl', dell', quest', etc.
            #   but NOT split apocope like "po' " (followed by space)
            s = re.sub(r"([a-zA-Z]+')(?=[a-zA-Zà-úÀ-Ú])", r"\1 ", s)
            s = re.sub(r'\s+', ' ', s)
        elif hasattr(self, 'language') and re.search(r'eng|english', self.language):
            s = re.sub(r'n\'t', r" n't", s)  # haven't -> have n't
            s = re.sub(r"I'm", r"I 'm", s)  # it's -> it 's, I've -> I 've
            s = re.sub(r'(\S)\'(s|ve|ll|d|re)', r"\1 '\2", s)  # it's -> it 's, I've -> I 've etc.
        elif hasattr(self, 'language') and re.search(r'deu|german', self.language):
            pass
        else:
            # Default simple tokenization if no language is matched
            s = re.sub(r'([,;?.!])(?=\s|$)', r' \1', s)
            s = re.sub(r'\s+', ' ', s)
        return s

    def build_presegmented_input(self):
        """
        Builds the plain-text, one-utterance-per-line input for UDPipe's own
        tokenizer (tokenizer=presegmented), used for --api_model without
        --parameters. Utterances that cleaned to an empty string are skipped:
        UDPipe silently drops blank lines rather than emitting an empty sentence
        for them (verified live against the API), which would otherwise desync
        every following utterance's metadata - the same class of bug fixed earlier
        for the tagger+api_model meta_map. Returns the ordered list of uttIDs
        actually submitted, matching 1:1 in order with the sentences UDPipe returns.
        """
        sys.stderr.write("Creating temporary presegmented-text file for UDPipe tokenizer...\n")
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', delete=False, suffix=".txt") as temp_f:
            self.presegmented_input_file = temp_f.name
            ordered_ids = []
            skipped = 0
            for uttID, data in self.pendingUtterances.items():
                text = data['utt_text'].strip()
                if not text:
                    skipped += 1
                    continue
                temp_f.write(text + "\n")
                ordered_ids.append(uttID)
        if skipped:
            sys.stderr.write(f"  [INFO] Skipped {skipped} empty utterance(s) (no content after cleaning) - not sent to parser.\n")
        return ordered_ids

    def restamp_presegmented_output(self, raw_parsed, ordered_ids):
        """
        Post-processes UDPipe's tokenizer=presegmented output: replaces UDPipe's own
        per-sentence comments (# newdoc, # newpar, # sent_id, # text) with our own
        metadata (# item_id, # speaker, # age, # child, # project, # text, # chat),
        matched to the submitted utterances by ORDER - build_presegmented_input()
        guarantees one output sentence per submitted line, in order (verified live).
        Also builds self.outRows from the returned tokens - this is the first point
        at which real tokens exist for this code path - skipping multiword-token
        summary rows (e.g. "1-2 he's") the same way _parse_conllu_output() already
        does, so word-numbering stays the plain per-token CoNLL-U ID that dql.py's
        --merge step expects (atomic sub-tokens are always numbered contiguously
        1..N regardless of any MWT grouping over them, so this doesn't introduce
        gaps).
        """
        blocks = [b for b in raw_parsed.strip().split('\n\n') if b.strip()]
        if len(blocks) != len(ordered_ids):
            sys.stderr.write(
                f"  [WARNING] UDPipe returned {len(blocks)} sentences for {len(ordered_ids)} submitted "
                f"utterances - metadata alignment is unreliable; truncating to the shorter of the two.\n"
            )

        restamped_blocks = []
        for uttID, block in zip(ordered_ids, blocks):
            meta = self.pendingUtterances[uttID]
            token_lines = [line for line in block.splitlines() if line and not line.startswith('#')]

            header_lines = [
                f"# item_id = {uttID}",
                f"# speaker = {meta['speaker'] or '_'}",
                f"# age = {meta['age'] or '_'}",
                f"# child = {meta['child'] or '_'}",
                f"# project = {meta['project'] or '_'}",
            ]
            # omitted rather than '_' when empty: both are reserved/parsed fields
            if meta['utt_text']:
                header_lines.append(f"# text = {meta['utt_text']}")
            if meta['utterance']:
                header_lines.append(f"# chat = {meta['utterance']}")
            restamped_blocks.append("\n".join(header_lines) + "\n" + "\n".join(token_lines))

            for line in token_lines:
                cols = line.split('\t')
                if len(cols) < 2 or not cols[0].isdigit():
                    continue  # skip MWT summary rows ("1-2"), same convention as _parse_conllu_output()
                self.outRows.append({
                    'utt_id': f"{uttID}_w{cols[0]}",
                    'utt_nr': meta['utt_nr'],
                    'w_nr': int(cols[0]),
                    'speaker': meta['speaker'],
                    'child_project': meta['child_project'],
                    'language': meta['language'],
                    'child_other': meta['child_other'],
                    'age': meta['age'],
                    'age_days': meta['age_days'],
                    'time_code': meta['time_code'],
                    'word': cols[1],
                    'utterance': meta['utterance'],
                    'utt_clean': meta['utt_clean_val'],
                    'utt_text': meta['utt_text'],
                    'child': meta['child'],
                    'project': meta['project']
                })

        return "\n\n".join(restamped_blocks) + "\n"

    def correct_tagger_output(self, tagged):
        """Corrects known tagger errors for a specific language."""
        if hasattr(self, 'language') and re.search(r'fra|french', self.language):
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
        elif hasattr(self, 'language') and re.search(r'deu|german', self.language):
            pass
        else:
            pass
        return tagged

    def run(self):
        """
        Main entry point using a session-aware streaming parser. 
        v5.1. revised to handle headers correctly, using split after @End (instead of before @Begin).
              This includes @PID in the preamble before the first @Begin.
        """
        try:
            self.tagger_input_file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8', delete=False, suffix=".txt")
            
            opener = gzip.open if self.args.chat_file.endswith('.gz') else open
            encoding = 'utf8'

            with opener(self.args.chat_file, 'rt', encoding=encoding) as f:
                full_content = f.read()

            session_blocks = filter(None, re.split(r'(?<=@End)', full_content))    # FIX v5.1: Split after @End 
            
            # Simple counter for logging (optional)
            total_sessions = len(re.findall(r'@Begin', full_content)) 
            if total_sessions == 0: total_sessions = 1 
            sys.stderr.write(f"Found {total_sessions} session(s) to process.\n")
            
            session_blocks_list = list(session_blocks)
            if not session_blocks_list:
                 session_blocks_list = [full_content]

            for i, session_content in enumerate(session_blocks_list):
                sys.stderr.write(f"\rProcessing session {i}/{total_sessions}...")
                sys.stderr.flush()

                # 1. Parse headers
                # Now that we split after @End, 'session_content' starts with the PID/ID headers
                header_match = re.match(r'((?:(?:@|\t)[^\n]*\n)*)', session_content.lstrip())
                if not header_match:
                    # Skip empty blocks or blocks with only whitespace
                    if not session_content.strip(): continue
                    # Fallback: try to find header if it's not at the very top
                    header_match = re.search(r'((?:(?:@|\t)[^\n]*\n)+)', session_content)
                
                if header_match:
                    header_block = header_match.group(1)
                    self.parse_header(header_block)
                    
                    # 2. Process Utterances using the self.pid set by parse_header
                    # We start processing after the header block
                    utterance_content = session_content[session_content.find(header_block) + len(header_block):]
                    utterance_blocks = re.findall(r'(\*[^\n]*(?:\n(?![*@])[^\n]*)*)', utterance_content)

                    for block in utterance_blocks:
                        self.process_utterance_block(block)

            sys.stderr.write("\nInitial parsing complete.\n")
            self.finalize_output()

        finally:
            if self.tagger_input_file: self.tagger_input_file.close(); os.unlink(self.tagger_input_file.name)
            if self.tagged_temp_file: self.tagged_temp_file.close(); os.unlink(self.tagged_temp_file.name)
            if self.conllu_input_file and os.path.exists(self.conllu_input_file): os.unlink(self.conllu_input_file)
            if self.presegmented_input_file and os.path.exists(self.presegmented_input_file): os.unlink(self.presegmented_input_file)

    def process_utterance_block(self, block):
        block = re.sub(r'\n\s+', ' ', block, flags=re.DOTALL)
        timeCode = (m.group(1) if (m := re.search(r'\x15(\d+_\d+)\x15', block)) else '')
        block_no_time = re.sub(r'\s*\x15.*?\x15', '', block) # remove including spaces
        
        if not (m := re.search(r'^\*([A-Z0-9]+):\s+(.*)', block_no_time.strip())):
            return
        
        speaker, utt = m.groups()
        self.sNr += 1
        uttID = f"{self.pid}_u{self.sNr}"
        
        splitUtt = self.strip_transcription_noise(cleanUtt(utt))
        if self.args.parameters is not None:
            self.tagger_input_file.write(f"<s_{uttID}> {self.tokenise(splitUtt)}\n")
            self.generate_rows_from_tagger(splitUtt, utt.strip(), speaker, uttID, timeCode)
        elif self.args.api_model:
            # No tagger: defer tokenisation to UDPipe's own tokenizer (UD-compliant),
            # instead of pre-splitting with tokenise()'s tagger-oriented rules. The
            # per-word outRows grid for this utterance is built later, from the
            # returned CoNLL-U, by restamp_presegmented_output().
            self.record_utterance_for_parsing(splitUtt, utt.strip(), speaker, uttID, timeCode)
        else:
            self.generate_rows_from_tagger(splitUtt, utt.strip(), speaker, uttID, timeCode)

    def generate_rows_from_tagger(self, splitUtt, raw_utt, speaker, uttID, timeCode):
        clean_val = splitUtt if self.args.utt_clean else ''
        words = self.tokenise(splitUtt).split(' ')
        
        age, age_days, child_other, child_project_id, child_name = self.get_speaker_age(speaker)

        for wNr, w in enumerate(words, 1):
            if not w: continue

            self.outRows.append({
                'utt_id': f"{uttID}_w{wNr}",
                'utt_nr': self.sNr,
                'w_nr': wNr,
                'speaker': speaker,
                'child_project': child_project_id,
                'language': self.language,
                'child_other': child_other,
                'age': age,
                'age_days': age_days,
                'time_code': timeCode,
                'word': w,
                'utterance': raw_utt,
                'utt_clean': clean_val,
                # not CSV columns: source of '# text'/'# child'/'# project' in CoNLL-U,
                # which must be recoverable from the FORM column, unlike the raw CHAT string
                'utt_text': splitUtt,
                'child': child_name,
                'project': self.project
            })

    def record_utterance_for_parsing(self, splitUtt, raw_utt, speaker, uttID, timeCode):
        """
        Records per-utterance metadata only (no word-splitting) for the --api_model
        path when no tagger is used. self.outRows for this utterance is built later,
        from the actual tokens UDPipe's own tokenizer returns, by
        restamp_presegmented_output().
        """
        age, age_days, child_other, child_project_id, child_name = self.get_speaker_age(speaker)
        self.pendingUtterances[uttID] = {
            'utt_nr': self.sNr,
            'speaker': speaker,
            'child_project': child_project_id,
            'language': self.language,
            'child_other': child_other,
            'age': age,
            'age_days': age_days,
            'time_code': timeCode,
            'utterance': raw_utt,
            'utt_clean_val': splitUtt if self.args.utt_clean else '',
            'utt_text': splitUtt,
            'child': child_name,
            'project': self.project
        }

    def parse_header(self, header_block):
        self.childData = {}
        self.project = ""
        self.language = ""
        
        # 1. search PID in header
        if m_pid := re.search(r'@PID:.*?-(\d+)', header_block):
            new_pid_raw = m_pid.group(1)
            new_pid = re.sub(r'^0+', '', new_pid_raw)
            if new_pid != self.pid:  # Only reset if  PID has changed
                self.pid = new_pid
                self.sNr = 0
        # 2. Extract Project and Language from the first @ID line found
        if m_id_gen := re.search(r'@ID:\s+(.*?)\|(.*?)\|', header_block):
            self.language, self.project = m_id_gen.groups()
            if self.html_exporter:
                self.html_exporter.project = self.project
        # 3. Build a map of Speaker Code -> Real Name from @Participants
        code_to_name = {}
        clean_header = re.sub(r'\n\t', ' ', header_block)
        
        if m_part := re.search(r'@Participants:\s+(.*)', clean_header):
            participants_str = m_part.group(1)
            parts = participants_str.split(',')
            for p in parts:
                tokens = p.strip().split()
                if len(tokens) >= 2:
                    code = tokens[0]
                    name = tokens[1]
                    code_to_name[code] = name

        # 3b. Sekali-specific: @ID carries no age field for this corpus; the age at
        #     recording is instead coded in @Media as a YYMMDD ("Y;MM.DD") string.
        media_age_str = ''
        if self.project == 'Sekali':
            if m_media := re.search(r'@Media:\s+(\d{2})(\d{2})(\d{2})', header_block):
                y, mth, d = m_media.groups()
                media_age_str = f"{int(y)};{mth}.{d}"

        # 4. Parse all @ID lines to find ALL Target_Children
        id_lines = re.findall(r'@ID:\s+(.*)', header_block)

        for line in id_lines:
            fields = line.strip().split('|')
            if len(fields) > 7:
                code = fields[2]
                age_str = fields[3]
                role = fields[7]

                # Check if this ID belongs to a target child
                if role == 'Target_Child':
                    if age_str == '24;00.02': age_str = '2;00.02' # Fix known data bug (Italian childes)
                    if not age_str and media_age_str: age_str = media_age_str  # Fallback for Sekali corpus

                    if age_str:
                        _, age_days = parseAge(age_str)
                    else:
                        age_days = 0
                        
                    # Determine Identifier (Name_Project or Code_Project)
                    if code in code_to_name:
                        child_name = code_to_name[code]
                    else:
                        child_name = code 
                        
                    # Normalise inconsistencies
                    child_name = re.sub(r'[éè]', 'e', child_name)
                    child_name = re.sub(r'Ann_Yor', 'Anne_Yor', child_name)
                    child_name = re.sub(r'(Greg|Gregx|Gregoire)_Cha', 'Gregoire_Cha', child_name)
                    child_name = re.sub(r'Sullyvan', 'Sullivan', child_name)
                    
                    full_id = f"{child_name}_{self.project[:3]}"

                    # Store data: self.childData[CODE] = (ID, AgeString, AgeDays, ChildName)
                    self.childData[code] = (full_id, age_str, age_days, child_name)

        # 5. Fallback: If no child data found, assign default CHI
        if not self.childData and 'CHI' in code_to_name:
             self.childData['CHI'] = (f"{code_to_name['CHI']}_{self.project[:3]}", "", 0, code_to_name['CHI'])
        elif not self.childData:
             self.childData['CHI'] = (f"NN_{self.project[:3]}", "", 0, "NN")

    def get_speaker_age(self, speaker):
        """
        Returns (AgeString, AgeDays, Category, ProjectID, ChildName)
        Category is "C" if speaker is a target child, "X" otherwise.
        """
        # 1. Is the speaker a known Target Child?
        if speaker in self.childData:
            # childData[speaker] = (full_id, age_str, age_days, child_name)
            return self.childData[speaker][1], self.childData[speaker][2], "C", self.childData[speaker][0], self.childData[speaker][3]

        # 2. If not, it is an 'Other' (Adult/Investigator)
        # Fallback: Use the first registered child's ID and Age as the "Session Reference"
        ref_age_days = 0
        ref_project_id = ""
        ref_child_name = ""

        if self.childData:
            first_child = next(iter(self.childData.values()))
            ref_project_id = first_child[0] # e.g. "Dylan_Pal"
            ref_age_days = first_child[2]
            ref_child_name = first_child[3]

        return '', ref_age_days, "X", ref_project_id, ref_child_name
    
    def apply_grew_rewrite(self, conllu_file, rule_file):
        """
        Applies Grew rewrite rules to a CoNLL-U file and saves the result.
        """
        sys.stderr.write(f"- Correcting parser output with Grew rewrite rules from {rule_file}...\n")
        
        try:
            # Load the rule system (GRS) and the corpus
            grs = GRS(rule_file)
            corpus = Corpus(conllu_file)
            
            # Apply the rules. 
            # Note: grs.run returns a dict {sent_id: [Graph, ...]} 
            corpus_corrected = grs.run(corpus)
            
            # Write the corrected data back to the CoNLL-U file
            with open(conllu_file, 'w', encoding='utf8') as f:
                for sent_id in corpus_corrected:
                    # Get the list of transformed graphs
                    graphs = corpus_corrected[sent_id]
                    
                    # Take the first solution (assuming deterministic rules)
                    if len(graphs) > 0:
                        f.write(graphs[0].to_conll() + "\n")
                    else:
                        sys.stderr.write(f"    Warning: No rewrite result for {sent_id}\n")
            
            sys.stderr.write(f"- Rewrite complete. Updated {conllu_file}\n")

        except Exception as e:
            sys.stderr.write(f"  Error during Grew rewrite: {e}\n")
            # sys.exit(1)

    def resolve_filter_pos(self, row):
        """
        Returns the POS value that --pos_output/--pos_utterance should match against.
        Default: the parser's universal POS (UPOS, CoNLL-U column 4 / 'conll_4') when
        --api_model was used - portable across corpora/tagger models, unlike the
        tagger's own tag. Falls back to the tagger's tag ('pos') when --use_tagger_pos
        is given, or when no parser UPOS is available (no --api_model, or this row has
        none, e.g. untagged punctuation-only row).
        """
        if not self.args.use_tagger_pos:
            upos = row.get('conll_4')
            if upos and upos != '_':
                return upos
        return row.get('pos', '')

    def finalize_output(self, *args, **kwargs):
        """Final processing: run tagger and/or parser, write output files"""
        if not self.outRows and not self.pendingUtterances:
            sys.stderr.write("\nNo data rows were generated. Exiting.\n")
            return

        itemPOS, itemLemmas, itemTagged = {}, {}, {}
        parsed_conllu_str = None
        
        if self.args.parameters:
            self.tagger_input_file.seek(0)
            taggerInput = self.tagger_input_file.read()
            if taggerInput:
                _, itemPOS, itemLemmas, itemTagged = self.run_treetagger(taggerInput)

        if self.args.api_model:
            if self.args.parameters:
                # Tagger active: run_treetagger() already built self.conllu_input_file
                # (tagged2conllu()), pre-tokenised by the tagger. UDPipe respects those
                # exact tokens (input=conllu, no tokenizer) and only re-tags/re-parses.
                if self.conllu_input_file and os.path.exists(self.conllu_input_file):
                    parsed_conllu_str = self.run_udpipe_api(self.conllu_input_file, self.args.api_model, chunk_size=self.args.chunk_parse)
            else:
                # No tagger: submit untokenised, CHAT-cleaned utterance text and let
                # UDPipe's own tokenizer produce genuinely UD-compliant tokens.
                ordered_ids = self.build_presegmented_input()
                if ordered_ids:
                    raw_parsed = self.run_udpipe_api(self.presegmented_input_file, self.args.api_model, chunk_size=self.args.chunk_parse, presegmented=True)
                    if raw_parsed:
                        parsed_conllu_str = self.restamp_presegmented_output(raw_parsed, ordered_ids)

        if not self.args.parameters and not self.args.api_model:
            final_csv_path = re.sub(r'\.cha(\.gz)?$', '', self.args.chat_file) + '.csv'
            header = ['utt_id', 'utt_nr', 'w_nr', 'speaker', 'child_project', 'language', 'child_other', 'age', 'age_days', 'time_code', 'word', 'utterance', 'utt_clean']
            with open(final_csv_path, 'w', newline='', encoding='utf8') as f:
                writer = csv.DictWriter(f, delimiter='\t', fieldnames=header, extrasaction='ignore', quoting=csv.QUOTE_NONE, escapechar='\\', quotechar='|')
                writer.writeheader()
                writer.writerows(self.outRows)
            sys.stderr.write(f"\n  OUTPUT: {final_csv_path}\n")
            return
            
        html_links, conllu_data = {}, {}
        if parsed_conllu_str:
            conllu_data = self._parse_conllu_output(parsed_conllu_str)
            if self.html_exporter:
                html_links = self.html_exporter.export(parsed_conllu_str, self.outRows)
            if self.args.write_conllu:
                conllu_output_path = re.sub(r'\.cha(\.gz)?$', '', self.args.chat_file) + '.conllu'
                with open(conllu_output_path, 'w', encoding='utf8') as f_conllu:
                    f_conllu.write(parsed_conllu_str)
                sys.stderr.write(f"Generated standalone CoNLL-U file: {conllu_output_path}\n")

                # version 5.2: Apply Grew Rewrite if requested
                if self.args.rewrite:
                    self.apply_grew_rewrite(conllu_output_path, self.args.rewrite)
                    # reload the data so that CSV/HTML below use the corrected version
                    with open(conllu_output_path, 'r', encoding='utf8') as f:
                        parsed_conllu_str = f.read()
                    conllu_data = self._parse_conllu_output(parsed_conllu_str)

        # Process rows and write initial FULL parsed CSV
        sys.stderr.write("Output tables:\n")
        sys.stderr.write("- Processing rows and writing initial parsed CSV...\n")
        parsed_csv_path = re.sub(r'\.cha(\.gz)?$', '', self.args.chat_file) + '.parsed.csv'
        light_csv_path = re.sub(r'\.cha(\.gz)?$', '', self.args.chat_file) + '.light.csv' # Define light path here

        header_parsed = ['utt_id', 'utt_nr', 'w_nr', 'URLwww', 'URLloc', 'speaker', 'child_project', 'language', 'child_other', 'age', 'age_days', 'time_code', 'word', 'lemma', 'pos', 'utterance', 'utt_clean', 'utt_tagged']
        header_parsed.extend([f'conll_{i}' for i in range(1, 11)])
        header_light = ['utt_id', 'utt_nr', 'w_nr', 'URLwww', 'URLloc', 'speaker', 'child_project', 'language', 'child_other', 'age', 'age_days', 'word', 'lemma', 'pos', 'utterance', 'utt_clean', 'utt_tagged'] # Define light header

        processed_rows_for_initial_write = [] # Store processed rows temporarily

        for row_orig in self.outRows:
            row = row_orig.copy()
            uID, wID_str = re.match(r'(.*)_w(\d+)', row['utt_id']).groups()
            wID = int(wID_str)

            # Add tagger info safely
            try:
                if itemPOS: row['pos'] = itemPOS.get(uID, ['_'] * wID)[wID - 1]
                if itemLemmas: row['lemma'] = itemLemmas.get(uID, ['_'] * wID)[wID - 1]
            except IndexError:
                row['pos'] = '_'
                row['lemma'] = '_'

            if self.args.utt_tagged and itemTagged: row['utt_tagged'] = itemTagged.get(uID, '')

            # Add CoNLL-U data
            conll_row = conllu_data.get(row['utt_id'], [])
            for i, col_val in enumerate(conll_row): row[f'conll_{i+1}'] = col_val

            # Use CoNLL-U pos/lemma if tagger wasn't used
            if not self.args.parameters and self.args.api_model and len(conll_row) > 3:
                row['pos'] = conll_row[3] if len(conll_row) > 3 and conll_row[3] else '_'
                row['lemma'] = conll_row[2] if len(conll_row) > 2 and conll_row[2] else '_'

            # Utterance filtering logic (applied again later for light version)
            if self.args.pos_utterance and not re.search(self.args.pos_utterance, self.resolve_filter_pos(row)):
                 row['utterance'] = row['utt_clean'] = row['utt_tagged'] = ''

            # Construct Hyperlink Strings (with doubled quotes inside)
            local_url_formula = ''
            server_url_formula = ''
            link_info = html_links.get(uID)
            if link_info:
                rel_local_path = os.path.relpath(link_info['local']).replace(os.path.sep, '/')
                local_url = f"http://localhost/{rel_local_path}#{uID}"
                local_url_formula = f'=HYPERLINK("{local_url}"; "LOC")'
                if self.args.server_url:
                    server_url = f"{self.args.server_url.rstrip('/')}/{link_info['file']}#{uID}"
                    server_url_formula = f'=HYPERLINK("{server_url}"; "WWW")'

            row['URLloc'] = local_url_formula
            row['URLwww'] = server_url_formula

            processed_rows_for_initial_write.append(row)

        # DictWriter messes up the =HYPERLINK() formulas by quoting them.
        # - Step 1 write without quotes, use dummy escapechar (required by csv module)
        tmp_file = parsed_csv_path + ".tmp"
        sys.stderr.write(f"- Writing temporary tabular output to {tmp_file}\n")
        with open(tmp_file, 'w', newline='', encoding='utf8') as f_parsed:
            writer_parsed = csv.DictWriter(f_parsed, delimiter='\t', fieldnames=header_parsed,
                                           extrasaction='ignore', quoting=csv.QUOTE_NONE, escapechar='\x1e')
            writer_parsed.writeheader()
            writer_parsed.writerows(processed_rows_for_initial_write)

        """
        "Manual" export step to final CSV files (workaround to preserve valid URLs) 
        (DictWriter unwantedly quotes URLs and makes them uninterpretable in Spreadsheet)
        In this step, we also apply utterance filtering for light version.
        This is not elegant, but avoids the csv module.
        """
        # - Step 2 read temp file and delete escapechar
        sys.stderr.write("- Reading back temporary CSV and writing final files manually...\n")

        light_csv_path = parsed_csv_path.replace("parsed", "light")  # *.light.csv

        def clean_val(x: str) -> str:
            # Remove the dummy escape char that we inserted with csv module
            return x.replace("\x1e", "") if isinstance(x, str) else ""

        # filter light version for pos_output constraint
        def keep_light(row: dict) -> bool:
            pos_val = self.resolve_filter_pos(row)
            if re.search(re.compile(self.args.pos_output), pos_val):
                return True  # print row
            else:
                return False # skip row

        with open(tmp_file, mode='r', encoding='utf-8', newline='') as infile, \
            open(parsed_csv_path, mode='w', encoding='utf-8', newline='') as f_parsed, \
            open(light_csv_path, mode='w', encoding='utf-8', newline='') as f_light:

            # Parse the temp file as TSV; no quoting, same escapechar you used in Step 1
            reader = csv.DictReader(infile, delimiter='\t', quoting=csv.QUOTE_NONE, escapechar='\x1e')

            # Write headers manually (no quoting)
            f_parsed.write('\t'.join(header_parsed) + '\n')
            f_light.write('\t'.join(header_light) + '\n')

            for row in reader:
                # Clean values for the full file
                full_vals = [clean_val(row.get(col, "")) for col in header_parsed]
                f_parsed.write('\t'.join(full_vals) + '\n')

                # Build + optionally filter light rows
                if keep_light(row):
                    light_vals = [clean_val(row.get(col, "")) for col in header_light]
                    f_light.write('\t'.join(light_vals) + '\n')

        sys.stderr.write(f"- Full table (one row per token): {parsed_csv_path}\n")
        sys.stderr.write(f"- Light table (selected columns and filtered tokens): {light_csv_path}\n")
        os.unlink(tmp_file)  # delete temp file after writing

    def _parse_conllu_output(self, conllu_str):
        conllu_data = {}
        current_item_id = None
        for line in conllu_str.splitlines():
            if line.startswith('#'):
                if match := re.match(r"#\s*item_id\s*=\s*(.*)", line):
                    current_item_id = match.group(1).strip()
                continue
            if current_item_id and line:
                cols = line.split('\t')
                if len(cols) >= 2 and cols[0].isdigit():
                    unique_id = f"{current_item_id}_w{cols[0]}"
                    conllu_data[unique_id] = cols
        return conllu_data

    def run_treetagger(self, tagger_input):
        sys.stderr.write("Calling TreeTagger...\n")
        tagger_bin, param_file = './tree-tagger', self.args.parameters
        if not all(map(os.path.exists, [tagger_bin, param_file])): sys.exit(f"Tagger binary or param file not found. Checked: {tagger_bin}, {param_file}")
        self.tagged_temp_file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8', delete=False, suffix=".txt")
        self.tagged_temp_file.write(re.sub(' +', '\n', tagger_input)); self.tagged_temp_file.flush()
        with open(self.tagged_temp_file.name, 'r') as f_in:
            tagged = subprocess.check_output([tagger_bin, param_file, '-token', '-lemma', '-sgml'], stdin=f_in).decode('utf8')
        tagged = process_tagged_data(tagged)
        if self.args.api_model:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', delete=False, suffix=".conllu.in") as temp_f:
                self.conllu_input_file = temp_f.name

            meta_map = {}
            for row in self.outRows:
                utt_id_base = re.match(r'(.*)_w\d+', row['utt_id']).group(1)  # e.g. "18980_u1"
                if utt_id_base not in meta_map:
                    meta_map[utt_id_base] = {
                        'speaker': row.get('speaker') or '_',
                        'age': row.get('age') or '_',
                        'child': row.get('child') or '_',
                        'project': row.get('project') or '_',
                        'text': row.get('utt_text') or '',
                        'chat': row.get('utterance') or ''
                    }
            self.tagged2conllu(tagged, self.conllu_input_file, meta_map)
        words, pos, lemmas, tagged_sents = {}, {}, {}, {}
        sentences = re.split(r'(<s_([^>]+)>)', tagged)
        for i in range(1, len(sentences), 3):
            key = sentences[i+1]
            content_multiline = sentences[i+2].strip()
            lines = [line.split('\t') for line in content_multiline.split('\n') if line and len(line.split('\t')) == 3]
            words[key] = [parts[0] for parts in lines]
            pos[key] = [parts[1] for parts in lines]
            lemmas[key] = [parts[2] for parts in lines]
            content_oneline = re.sub(r'\t([A-Za-z:]+)\t', r'_\1=', content_multiline)
            content_oneline = re.sub(r'\n', ' ', content_oneline)
            content_oneline = self.correct_tagger_output(content_oneline)
            tagged_sents[key] = content_oneline.strip()
        return words, pos, lemmas, tagged_sents

    def tagged2conllu(self, str_in, conllu_out_path, meta_map=None):
        sys.stderr.write(f"Creating temporary CoNLL-U file with lemmas: '{conllu_out_path}'...\n")
        with open(conllu_out_path, 'w', encoding='utf8') as f:
            sentences = re.split(r'(<s_([^>]+)>)', str_in)
            for i in range(1, len(sentences), 3):
                sent_id = sentences[i+1]
                body = sentences[i+2].strip()

                meta = (meta_map or {}).get(sent_id, {})

                f.write(f"# item_id = {sent_id}\n")
                f.write(f"# speaker = {meta.get('speaker', '_')}\n")
                f.write(f"# age = {meta.get('age', '_')}\n")
                f.write(f"# child = {meta.get('child', '_')}\n")
                f.write(f"# project = {meta.get('project', '_')}\n")
                # omitted rather than '_' when empty: both are reserved/parsed fields
                if meta.get('text'):
                    f.write(f"# text = {meta['text']}\n")
                if meta.get('chat'):
                    f.write(f"# chat = {meta['chat']}\n")
                tokens = [line.split('\t') for line in body.split('\n') if line]
                for idx, token_parts in enumerate(tokens):
                    if len(token_parts) != 3: continue
                    word, tt_pos, tt_lemma = token_parts
                    # for robustness, replace empty or <unknown> lemmas/pos with '_'
                    if tt_lemma == '<unknown>' or tt_lemma == '': tt_lemma = '_'
                    if tt_pos == '': tt_pos = '_'
                    line = f"{idx+1}\t{word}\t{tt_lemma}\t_\t{tt_pos}\t_\t_\t_\t_\t_\n"
                    f.write(line)
                f.write("\n")

    def run_udpipe_api(self, input_file, model, chunk_size, presegmented=False):
        """
        presegmented=True: input_file is plain text, one utterance per line (built by
        build_presegmented_input()); UDPipe's own tokenizer segments each line into
        UD-compliant tokens (tokenizer=presegmented preserves our line-based sentence
        boundaries - verified live - unlike its default resegmentation).
        presegmented=False (default): input_file is pre-built CoNLL-U with fixed FORM
        tokens (from tagged2conllu(), i.e. the tagger's own tokenisation); UDPipe
        respects those tokens exactly (input=conllu, no tokenizer) and only re-tags/
        re-parses.
        """
        API_URL = "https://lindat.mff.cuni.cz/services/udpipe/api/process"
        sys.stderr.write(f"Calling Lindat API with UDPipe model '{model}'...\n")
        with open(input_file, 'r', encoding='utf8') as f:
            full_content = f.read()
        sep = '\n' if presegmented else '\n\n'
        sentences = full_content.strip('\n').split(sep) if presegmented else full_content.strip().split(sep)
        total_chunks = (len(sentences) + chunk_size - 1) // chunk_size
        parsed_results = []
        for i in range(0, len(sentences), chunk_size):
            chunk = sentences[i:i + chunk_size]
            chunk_content = sep.join(chunk)
            current_chunk_num = i//chunk_size + 1
            eta = round(len(chunk) / 330)
            progress_msg = f"\r  Sending chunk {current_chunk_num}/{total_chunks} ({len(chunk)} utterances) to API. Processing time ~{eta}s..."
            sys.stderr.write(progress_msg)
            sys.stderr.flush()
            if presegmented:
                params = {'model': model, 'tokenizer': 'presegmented', 'tagger': '', 'parser': ''}
            else:
                params = {'model': model, 'input': 'conllu', 'tagger': '', 'parser': ''}
            response = requests.post(API_URL, data=params, files={'data': chunk_content})
            if response.status_code == 200:
                result = response.json().get('result')
                if result:
                    parsed_results.append(result)
                else:
                    sys.stderr.write(f"\nWarning: API call for chunk {current_chunk_num} succeeded but returned no result.\n")
            else:
                sys.stderr.write(f"\nError: API call for chunk {current_chunk_num} failed with status {response.status_code}: {response.text}\n")
                self._debug_udpipe_chunk(chunk_content, model, small_chunk_size=10, out_path='error_chunk.conllu', presegmented=presegmented)
                return None
        sys.stderr.write("\nAPI processing complete.\n")
        return "".join(parsed_results) if parsed_results else None

    def _debug_udpipe_chunk(self, chunk_content, model, small_chunk_size=10, out_path='error_chunk.conllu', presegmented=False):
        """
        Split a failing CoNLL-U (or presegmented-text) chunk into smaller chunks
        (default: 10 sentences), send each to the UDPipe API; on error write content
        and exit.
        We check for some of the HTTP status codes returned by UDPipe/Lindat:
        200=OK, 400=Bad Request (malformed CoNLL-U), 403=Forbidden, 413=Payload Too Large, 429=Too Many Requests, 500=Server Error, 502–504=Gateway/Timeout issues.
        """
        API_URL = "https://lindat.mff.cuni.cz/services/udpipe/api/process"
        sep = '\n' if presegmented else '\n\n'
        sentences = [s for s in chunk_content.strip(sep).split(sep) if s.strip()]

        total_small = (len(sentences) + small_chunk_size - 1) // small_chunk_size
        sys.stderr.write(f"\nDEBUG: Entering fine-grained UDPipe check ({total_small} mini-chunks of {small_chunk_size} sentences)...\n")

        for j in range(0, len(sentences), small_chunk_size):
            mini = sentences[j:j + small_chunk_size]
            mini_content = sep.join(mini)
            mini_idx = j // small_chunk_size + 1
            sys.stderr.write(f"\r  -> Testing mini-chunk {mini_idx}/{total_small} ({len(mini)} sentences)...")
            sys.stderr.flush()

            try:
                if presegmented:
                    params = {'model': model, 'tokenizer': 'presegmented', 'tagger': '', 'parser': ''}
                else:
                    params = {'model': model, 'input': 'conllu', 'tagger': '', 'parser': ''}
                resp = requests.post(API_URL, data=params, files={'data': mini_content})
            except Exception as e:
                # Network/transport error: save and exit
                with open(out_path, 'w', encoding='utf8') as ef:
                    ef.write(mini_content)
                sys.exit(f"\nFATAL: UDPipe request raised an exception on a mini-chunk: {e}\n"
                        f"       Offending content saved to '{out_path}'. Please inspect/fix and re-run.")

            # Same error logic as the main call:
            bad_status = resp.status_code != 200
            no_result = False
            if not bad_status:
                # Be defensive in JSON parsing
                try:
                    no_result = resp.json().get('result') in (None, '')
                except Exception as e:
                    no_result = True

            if bad_status or no_result:
                with open(out_path, 'w', encoding='utf8') as ef:
                    ef.write(mini_content)
                detail = f"status {resp.status_code}: {resp.text[:500]}..." if bad_status else "200 but empty/invalid result"
                sys.exit(f"\nFATAL: UDPipe failed on a mini-chunk ({len(mini)} sentences): {detail}\n"
                        f"       Offending content saved to '{out_path}'.")
        # If we get here, all mini-chunks succeeded, so the failure is intermittent or due to size/timeout.
        sys.exit("\nDEBUG RESULT: All mini-chunks succeeded in isolation. Consider reducing --chunk_parse.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('chat_file', type=str,  help='The input CHAT file (e.g., french-sample.cha or a .gz file)')
    parser.add_argument('-p', '--parameters', type=str, help='(Optional) TreeTagger parameter file. Requires TreeTagger binary in ./tree-tagger.')
    parser.add_argument('--api_model', type=str, help='(Optional) Name of the UDPipe model for the Lindat API (e.g., french).')
    parser.add_argument('--html_dir', type=str, help='(Optional) Directory to save HTML dependency parse files (keep the name short!). Requires --api_model.')
    parser.add_argument('--server_url', type=str, help='(Optional) Base URL for server links in the final CSV.')
    parser.add_argument('--write_conllu', action='store_true', help='(Optional) Write the final parsed CoNLL-U data to a standalone file. Requires --api_model.')
    parser.add_argument('--chunk_parse', type=int, default=10000, help='Number of utterances per API parsing chunk. Default: 10000.')
    parser.add_argument('--chunk_html', type=int, default=5000, help='Number of utterances per HTML output file. Default: 5000.')
    parser.add_argument('--pos_output', default=".*", type=str, help='Regex to match POS tags. The reduced "light" table will only contain matching rows.\nMatches the parser\'s universal POS (UPOS) when --api_model is used; see --use_tagger_pos.')
    parser.add_argument('--pos_utterance', type=str, help='Regex to match POS tags. The full utterance text will only be printed on matching rows.\nMatches the parser\'s universal POS (UPOS) when --api_model is used; see --use_tagger_pos.\nDefaults to --pos_output\'s value when not given explicitly.')
    parser.add_argument('--use_tagger_pos', action='store_true', help='Make --pos_output/--pos_utterance match the tagger\'s own (language/model-specific) POS tag instead of the parser\'s universal POS (UPOS). Has no effect without --parameters; has no effect on rows the tagger did not tag if --api_model is not set (only source of POS in that case).')
    parser.add_argument('--rewrite', type=str, help='Path to a Grew rule file (.grs) to correct the parsed CoNLL-U output.')
    parser.add_argument('--utt_clean', action='store_true', help='Populate the utt_clean column.')
    parser.add_argument('--utt_tagged', action='store_true', help='Populate the utt_tagged column.')

    args = parser.parse_args()
    # --pos_utterance defaults to --pos_output's value unless given explicitly, so the
    # common "restrict to POS X" case doesn't require passing the same regex twice.
    if args.pos_utterance is None:
        args.pos_utterance = args.pos_output
    processor = ChatProcessor(args)
    processor.run()