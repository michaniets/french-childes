#!/usr/bin/python3

__author__ = "Achim Stein"
__version__ = "2.0"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "02.05.25"
__license__ = "GPL"

import sys
import argparse, re
import os
import fileinput
import datetime
from xmlrpc.client import boolean
import subprocess   # for system commands, here: tree-tagger and udpipe
from collections import defaultdict   #  make dictionaries with initialised keys (avoids KeyError)
import csv
from tag_analyser import TagAnalyser  # previous function analyseTagging is now a class (v1.7)
import json   # for udpipe
import warnings

# global vars
age = child = speaker = utt = uttID = timeCode = splitUtt = pid = progress = ''
sNr = age_days = 0
outRows = []
childData = {}
annotations = {} # init the dictionary for annotations (--add_annotation)
annot_keys = ['annot_refl', 'annot_dat', 'annot_clit', 'annot_mod', 'annot_particle']
for key in annot_keys:
   annotations[key] = None
analyser = TagAnalyser()  # Init the TagAnalyser class
conllu_columns = [
    "ID",        # Token ID
    "FORM",      # Word form or punctuation symbol
    "LEMMA",     # Lemma or stem of the word
    "UPOS",      # Universal part-of-speech tag
    "XPOS",      # Language-specific part-of-speech tag
    "FEATS",     # List of morphological features
    "HEAD",      # Head of the current token (ID of the token's governor)
    "DEPREL",    # Universal dependency relation to the HEAD
    "DEPS",      # Enhanced dependency graph (if available)
    "MISC"       # Miscellaneous information
]
udpipe_model = 'french'  # default for option -u (currently selects gsd model in UDPipe)

def main(args):
  global age, age_days, child, childData, speaker, utt, uttID, pid, progress, splitUtt, sNr, timeCode, outRows    # needed to modify global vars locally
  age = child = taggerInput = pid = ''
  age_days = 0
  childData = {}  # store age for a child
  with open(args.out_file, 'r', encoding="utf8") as file:  # , newline=''
    sys.stderr.write("Reading " + args.out_file +'\n')
    all = file.read()
    all = re.sub('@End', '*\n', all)  # insert delimiter at end of file
    all = re.sub('@Begin.*?\n@Comment:.*?(dummy file|No transcript).*?\n@End\n', '', all, re.DOTALL)  # remove dummy files
    sentences = all.split('\n*')   # split utterances at '*', e.g. *CHI:
  if len(sentences) <= 1:
    sys.stderr.write("No output sentences found. " + str(len(sentences)) + " Exiting.\n")
    sys.exit(0)
  else:
    sys.stderr.write("Processing " + str(len(sentences)) + ' utterances\n')
  with open('tagthis.tmp', 'w') as tagthis:  # initialise tagger output file
    pass

  for s in sentences:  # sentence = utterance
    # -------------------------------------------------------
    # parse file header
    # -------------------------------------------------------
    # use PID to identify header
    rePID = re.compile('@PID:.*/.*?0*(\d+)')
    if re.search(rePID, s):
      if re.search (r'@Comment:.*dummy file', s):
        pass #continue
      
      m = re.search(rePID, s)
      pid = m.group(1)
      sNr = 0 # reset utterance numbering, so that files can be processed in any order without changing utt_id
      childData = {}  # empty childData bio dictionary
      # check for more than one Target_Child (French: only in Palasis)
      childNr = re.findall(r'@ID:\s+.*\|.*?\|[A-Z]+\|.*?\|.*Target_Child\|', s)
      if len(childNr) > 1:
        for c in childNr:
          m = re.search(r'@ID:\s+.*\|(.*?)\|([A-Z]+)\|(\d.*?)\|.*Target_Child\|', c)
          sys.stderr.write("----- reading header ID %s\n" % (c))
          project = m.group(1)
          key = m.group(2)  # use speaker abbrev as key for bio data
          age, age_days = parseAge(m.group(3))
          child = 'n=' + str(len(childNr)) + '_' + project[:3]
          childData[key] = (child, age, age_days)   # store bio data in dict
      else:
        # just one Target_Child  (TODO: redundant, include above)
        # example: @ID: fra|Paris|CHI|0;11.18|female|||Target_Child|||
        if re.search(r"CHI Target_Child , TAT Tata Babysitter", s):  # correct error in one file header
          s = re.sub("CHI Target_Child , TAT Tata Babysitter", "CHI Anne Target_Child , TAT Tata Babysitter", s)
        reMatch = re.compile('@ID:.*\|(.*?)\|[A-Z]+\|(\d.*?)\|.*Target_Child')
        if re.search(reMatch, s):
          m = re.search(reMatch, s)
          project = m.group(1)
          age, age_days = parseAge(m.group(2))
          # get the child's name, e.g. @Participants:	CHI Tim Target_Child, MOT Mother Mother...
          reMatch = re.compile('@Participants:.*CHI\s(.*?)\sTarget_Child')
          if re.search(reMatch, s):
            m = re.search(reMatch, s)
            child = m.group(1) + '_' + project[:3]  # disambiguate identical child names
            child = re.sub(r'[éè]', 'e', child)  # Anae is not spelt consistently
            child = re.sub(r'Ann_Yor', 'Anne_Yor', child)  # repair inconsistency
            child = re.sub(r'(Greg|Gregx|Gregoire)_Cha', 'Gregoire_Cha', child)  # repair inconsistency
            childData['CHI'] = (child, age, age_days)   # store bio data in dict
      progress = round(sNr/len(sentences)*100, 0)
      sys.stderr.write("Progress: %s%% | PID: %s / CHILD: %s / AGE: %s = %s days\n" % (progress, pid, child, age, str(age_days)))
      continue  # no output for the header
    if pid == '':       # verify if header was parsed
      sys.stderr.write('!!!!! ERROR: missing header info. Check the file header! Exiting at utterance:\n')
      sys.stderr.write(s)
      sys.exit(1)
    # -------------------------------------------------------
    # parse utterance
    # -------------------------------------------------------
    timeCode = utt = mor = speaker = ''
    tags = []
    sNr += 1
    uttID = pid + '_u' + str(sNr)     # args.out_file + '_u' + str(sNr)
    # general substitution
    s = re.sub(r'‹', '<', s)
    s = re.sub(r'›', '>', s)
    s = re.sub(r'\n\s+', ' ', s, re.DOTALL)  # append multi-line to first line
    # get utterance time? code (delimited by ^U)
    if re.search(r'(.*?)', s):
      m = re.search(r'(.*?)', s)
      timeCode = m.group(1)
    s = re.sub(r' ?.*?', '', s)
    # match the annotation line starting with %mor
    reMatch = re.compile('%mor:\s+(.*)')
    if re.search(reMatch, s):
      m = re.search(reMatch, s)
      mor = m.group(1)
    # match speaker and utterance
    reMatch = re.compile('^([A-Z]+):\s+(.*?)\n')
    if re.search(reMatch, s):
      m = re.search(reMatch, s)
      speaker = m.group(1)
      utt = m.group(2)
    splitUtt = cleanUtt(utt)  # clean a copy for splitting in to words
    # concatenate utterances to build taggerInput. Use tag with uttID
    if args.parameters != '':
      with open('tagthis.tmp', 'a') as tagthis:  # for tagger output
        taggerLine = "<s_" + uttID + "> " + tokenise(splitUtt) + '\n'
        tagthis.write(taggerLine)

    # -------------------------------------------------------
    # split utterance into tokens
    # -------------------------------------------------------
    # list of table rows 
    if speaker != '':
      if args.parameters == '':
        outRows = wordPerLineChat(splitUtt, mor)
      else:
        # tokenisation for tree-tagger, optionally UDPipe parsing
        outRows = wordPerLineTagger(splitUtt, mor)


  # ----------------------------------------
  # TreeTagger (option -p)
  # ----------------------------------------
  if args.parameters != '':
    sys.stderr.write('Running TreeTagger on taggerInput\n')
    with open('tagthis.tmp', 'r') as tagthis:
      taggerInput = tagthis.read()
    (itemWords, itemPOS, itemLemmas, itemTagged) = treeTagger(taggerInput)

  # ----------------------------------------
  # Parser (option -h)  NOT YET IMPLEMENTED
  # ----------------------------------------
  #if args.hopsparser != '':
  #  sys.stderr.write('Running Parser...\n')
  #  with open('tagthis.tmp', 'r') as parsethis:
  #    taggerInput = parsethis.read()
  #  (itemWords, itemPOS, itemLemmas, itemTagged) = treeTagger(taggerInput)


  # ----------------------------------------
  # output
  # ----------------------------------------
  # write output table: DictWriter matches header and rows, regardless of the order of fields in row
  outHeader = ['utt_id', 'utt_nr', 'w_nr', 'speaker', 'child_project', 'child_other', 'age', 'age_days', 'time_code', 'word', 'lemma', 'pos', 'features', 'annotation', 'utterance', 'utt_clean', 'utt_tagged']
  if args.add_annotation != '':
    for key, value in annotations.items():
      outHeader.append(key) # create columns for annotation values
  if args.ud_pipe != '':
    for key in conllu_columns:
      outHeader.append(key) # create columns for conllu annotation

  with open(args.out_file + '.csv', 'w', newline='') as out:   # newline '' is needed: we have commas in items
    writer = csv.DictWriter(out, delimiter='\t', fieldnames=outHeader)
    writer.writeheader()
    writer.writerows(outRows)

  # add tagger output
  if args.parameters != '':
    sys.stderr.write('Adding tagger output for each utterance...\n')
    addTagging(args.out_file + '.csv', args.out_file + '.tagged.csv', outHeader, itemWords, itemPOS, itemLemmas, itemTagged)
    # write output
    sys.stderr.write(f"\nOUTPUT: {args.out_file}.tagged.csv\n")
    sys.stderr.write("  you can delete the temporary file: " + args.out_file + '.csv\n')
    sys.stderr.write("  you can delete the temporary files: tag*.tmp\n")
  else:
    sys.stderr.write("output was written to: " + args.out_file + '.csv\n')
  if args.ud_pipe != '':
    sys.stderr.write("CoNLL-U columns were added to the table. To extract CoNLL-U files use this script:\n> python childes-csv2conllu.py output.csv > output.conllu\n")
  if args.conllu != '':
    help_conllu = """PARSING:
      CoNLL-U was written to parseme.conllu. Run a parser on it, or call UDPipe like so:
      1. slice into files of 10000 sentences (UDPipe doesn't seem to digest larger files)
      > conll-util.py -S 10000 parseme.conllu
      2a. send each slice to UDPipe, pipe through Python to convert JSON to CoNLL-U:
      > for i in parseme_*.conllu; do echo "--------- $i"; curl -F data=@$i  -F model=french -F tagger= -F parser= -F input=conllu https://lindat.mff.cuni.cz/services/udpipe/api/process | python3 -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['result'])" > output-$i; done 
      2b. if JSON library produces errors convert json to conllu using json2conll.py
      > for i in {1..42}; do file="output-parseme_${i}.conllu.json"; echo "------- $file"; python3 json2conll.py $file >> childes-all.conllu; done
      """
    sys.stderr.write(help_conllu)
  
#-------------------------------------------------------
# functions
#-------------------------------------------------------

def parseAge(age):
  # parse the age string, correct errors, return age in days
  year = months = days = 0
  m = re.search(r'(\d+);', age)
  if m:
    year = m.group(1)
  m = re.search(r'\d+;(\d+)', age)
  if m:
    months = m.group(1)
  m = re.search(r'\d+;\d+\.(\d+)', age)
  if m:
    days = m.group(1)
  #age = year + ';' + months + '.' + days
  age_days = int(int(year) * 365 + int(months) * 30.4 + int(days))
  return(age, age_days)

def addTagging(inputFile, outputFile, outHeader, itemWords, itemPOS, itemLemmas, itemTagged):
  # read the csv output file and add information from TreeTagger output
  with open(inputFile, 'r') as csvfile:    # csv file with empty pos, lemma
    with open(outputFile, 'w') as csvout:  # csv with filled columns
      writer = csv.writer(csvout, delimiter = "\t")
      reader = csv.reader(csvfile, delimiter = "\t")
      data = list(reader)
      total_rows = len(data)  # Get total number of rows for progress calculation
      print(f"Adding tagger output to csv table ({total_rows} rows)...")
      # Iterate through each row and modify a specific cell in each row
      for l, row in enumerate(data):
        if l % 100 == 0:  # progress every 100 rows
          progress = (l / total_rows) * 100
          sys.stderr.write(f'\r  Merging with tagger output: {progress:.1f}% complete')
          sys.stderr.flush()  # Ensure it gets printed immediately

        reMatch = re.compile('(.*)_w(\d+)') # get utterance ID (=key) and word number...
        if re.search(reMatch, data[l][0]):  # ... from the first col of the row
          m = re.search(reMatch, data[l][0])
          uID = m.group(1)
          wID = m.group(2)
          lemma = itemLemmas[uID].split(' ')
          pos = itemPOS[uID].split(' ')
          # get column indexes from header
          lemmaIndex = outHeader.index("lemma") if "lemma" in outHeader else None
          posIndex = outHeader.index("pos") if "pos" in outHeader else None
          uttIndex = outHeader.index("utterance") if "utterance" in outHeader else None
          # insert new lemma (col 9), pos (10), note (11)
          try:
            data[l][lemmaIndex] = lemma[int(wID)-1]
          except IndexError:
            print('   INDEX ERROR inserting lemma: %s\n' % data[l])
          try:
            data[l][posIndex] = pos[int(wID)-1]
          except IndexError:
            print('   INDEX ERROR inserting pos: %s\n' % data[l])

          # ----------------------------------------
          # output options
          # ----------------------------------------
          # -m : parse tagged output -- TODO: is option -m redundant (now -a)
          if args.match_tagging != '':
            tagged = itemTagged[uID]
            try:
              if re.search(re.compile(args.match_tagging), pos[int(wID)-1]): # if tagger pos matches argument
                # --add_annotation: get the annotation values, store at index of header column
                if args.add_annotation != '':
                  annotations = analyser.analyse(tagged, lemma[int(wID) - 1])  # class call version >= 1.7
                  for key, value in annotations.items():
                    thisIndex = outHeader.index(key) if key in outHeader else None
                    data[l][thisIndex] = annotations[key]
            except IndexError:
              print('   INDEX ERROR annotation index %s of: %s\n' % (str(int(wID)-1), data[l]))
          # add a column with the tagger analysis 
          if args.tagger_output:
            index = outHeader.index("utt_tagged")
            reMatch = re.compile(args.pos_utterance)
            if posIndex <= len(data[l]) and re.search(reMatch, data[l][posIndex]):
              data[l][index] = tagged  # add the tagged string
          # output option depending on tagger output
          if args.pos_utterance:
            uttIndex = outHeader.index("utterance") if "utterance" in outHeader else None
            reMatch = re.compile(args.pos_utterance)
            if posIndex <= len(data[l]) and not re.search(reMatch, data[l][posIndex]):
              data[l][uttIndex] = ''  # add the utterance

          # output table row
          writer.writerow(row)
        else:
          # output header row
          writer.writerow(row)

def analyseTagging(tagged, lemma):
    for key in annot_keys:
      annotations[key] = None  # empty the dict for annotations
    # -------------------------------------------------------
    # --- Annotate reflexives
    # -------------------------------------------------------
    reRefl = re.compile(' [^_]+_.*?=se [^_]+_VER.*?=(?P<lemma>\w+)')
    if re.search(reRefl, tagged):
        m = re.search(reRefl, tagged)
        matchedLemma = m.group('lemma')
        if lemma == matchedLemma:  # Annotate only rows where lemma is identical
            annotations['annot_refl'] = 'refl'
    # -------------------------------------------------------
    # --- Annotate 'dative' complements with à, au, lui
    # -------------------------------------------------------
    reDat = re.compile('[^_]+_VER.*?=(?P<lemma>\w+) (à|au|aux)_[^ ]+')
    if re.search(reDat, tagged):
        m = re.search(reDat, tagged)
        matchedLemma = m.group('lemma')
        if lemma == matchedLemma:  # Annotate only rows where lemma is identical
            annotations['annot_dat'] = 'aPP'    
    # -------------------------------------------------------
    # --- Annotate object clitics
    # -------------------------------------------------------
    # use escape lemma for regex to avoid errors caused by special characters
    reDatCl = re.compile(rf'(lui|leur)_PRO:clo[^ ]+ [^_]+_(VER|AUX).*?=(?P<lemma>{re.escape(lemma)})')
    reAccCl = re.compile(rf'(le|la|les)_PRO:clo[^ ]+ [^_]+_(VER|AUX).*?=(?P<lemma>{re.escape(lemma)})')
    reAccDatCl = re.compile(rf'(le|la|les)_PRO:clo[^ ]+ (lui|leur)_PRO:clo[^ ]+ [^_]+_(VER|AUX).*?=(?P<lemma>{re.escape(lemma)})')
    if re.search(reDatCl, tagged):
        annotations['annot_clit'] = 'dat'
    if re.search(reAccCl, tagged):
        annotations['annot_clit'] = 'acc'
    if re.search(reAccDatCl, tagged):
        annotations['annot_clit'] = 'accdat'
    # -------------------------------------------------------
    # --- Annotate Modal verbs
    # -------------------------------------------------------
    reOnlyModals = re.compile('(devoir|falloir|pouvoir|savoir|vouloir)')  # only modals
    reModalLemmas = re.compile('[^ ]+')  # only modals
    reModCl = re.compile(rf'[^ _]+_.*?=(?P<lemma>{lemma})( [^_]+_ADV=\S+)*( [^_]+_PRO:clo=\S+).*? [^_]+_VER:infi=(?P<verb>\S+)')
    reModVerb = re.compile(rf'[^ _]+_.*?=(?P<lemma>{lemma})( [^_]+_ADV=\S+)*.*? [^_]+_(VER|AUX):infi=(?P<verb>\S+)')
    reModCompl = re.compile(rf'[^ _]+_.*?=(?P<lemma>{lemma})( [^_]+_ADV=\S+)* [^_]+_(KON|PRO:int)')
    reModObj = re.compile(rf'[^ _]+_[^=]+=(?P<lemma>{lemma}) [^_]+_(DET:.*?|PRO:rel|PRO:dem)=')
    reClMod = re.compile(rf'([^ _]+_PRO:clo=\S+) [^_]+_.*?=(?P<lemma>{lemma})( pas_ADV=pas)?.*? [^_]+_VER:infi=(?P<verb>\S+)')
    if re.search(reOnlyModals, lemma):
      prefix = "modal"  # mark modal verbs by prefix 'mod'
    else:
      prefix = "verb"
    if re.search(reModCl, tagged):  
      thisAnnot = prefix + '-clit-verb'
    elif re.search(reClMod, tagged):
        thisAnnot = 'clit-' + prefix  # no clit-modal order in the corpus
    elif re.search(reModObj, tagged):
      thisAnnot = prefix + '-obj'
    elif re.search(reModVerb, tagged):
      thisAnnot = prefix + '-verb'
    elif re.search(reModCompl, tagged):
      thisAnnot = prefix + '-clause'
    else:
      thisAnnot = prefix + '-noRule'
    annotations['annot_mod'] = thisAnnot  # store annotation in dict
    # -------------------------------------------------------
    # --- Annotate verb particles (just a try, for project H1)
    # -------------------------------------------------------
    reParticle = re.compile('(dessus|dessous|dehors|avant|derrière|en-.*)')
    reVPart = re.compile(rf'[^ _]+_VER:.*?=(?P<lemma>{lemma}) (?P<part>{reParticle.pattern}_ADV=\S+)')
    if re.search(reVPart, tagged):
      annotations['annot_particle'] = 'verb-part_' + re.search(reVPart, tagged).group('part') # matchedPart

    return annotations

def insertAtIndex(add, list, index):
  # insert 'add' in list at index
  #if len(list) < index+1:
  if index < len(list):
    list[index] = add
  else:
    sys.stderr.write('INDEX ERROR FOR LIST of len=' + str(len(list)) + ' index='+ str(index) + ' >>' + str(list) + '\n')
  return(list)

def wordPerLineTagger(splitUtt, mor):
  # for TreeTagger annotation: build one line (table row) for each token in utterance
  child_other = ''
  age = tags = ''
  age_days = wNr = 0
  thisRow = {}
  words = tokenise(splitUtt).split(' ')
  # Parse with UDPipe 
  global udpipe_model # use the model specified with option --ud_pipe
  if args.ud_pipe != '':
    udpipe_output = parse_with_udpipe(tokenise(splitUtt)) # use same tokeniser
    print(f"UDPipe output: {udpipe_output}")
  # build row for output
  for w in words:
    if w == '':
      continue
    wNr += 1
    t = l = f = ''  # will be filled by TreeTagger output
    w = re.sub(r'@.*', '', w)
    # control if utterance is printed
    splitUttPrint = ''
    if args.tagger_input:
      splitUttPrint = splitUtt
    uttPrint = utt
    if args.first_utterance and wNr > 1:
      uttPrint = splitUttPrint = ''
    # if there is childData for this speaker (=child), insert the child's age
    if childData.get(speaker) != None:
      child_other = "C"
      age = childData[speaker][1]
      age_days = childData[speaker][2]
    else:  # for caretakers, annotate the child's age (age_days)
      child_other = "X"
      for caretaker, data in childData.items():
        # check if there is an age_days variable 
        if len(data) > 2 and caretaker == "CHI":  # exclude multi-child corpus (Palasis)
            age_days = data[2]
    # build output line for word
    thisRow = {
      'utt_id': uttID + '_w' + str(wNr),
      'utt_nr': sNr,
      'w_nr': wNr,
      'speaker': speaker,
      'child_project' : child,
      'child_other' : child_other,
      'age': age,
      'age_days': age_days,
      'time_code': timeCode,
      'word': w,
      'pos': t,
      'lemma': l,
      'features': f,
      'annotation': '',
      'utterance': uttPrint,
      'utt_clean': splitUttPrint
      }
    # Append the conllu columns for this word (or nothing if UDPipe fails)
    if args.ud_pipe != '':
      udpipe_model = args.ud_pipe
      conllu_data = get_conllu_word(wNr, udpipe_output) or {}  # empty dict if None
      thisRow.update(conllu_data) 
    outRows.append(thisRow)   # append dictionary for this row to the list of rows
  return(outRows)

def parse_with_udpipe(udpipe_input):
  """
  Takes tokenised utterance, launches UDPipe using curl
  see https://lindat.mff.cuni.cz/services/udpipe/api-reference.php
  """
  # UDPipe call returns JSON output. Collect and decode
  udpipe_input = clean_for_udpipe(udpipe_input)
  print(f"Progress: %s%% | Calling UDPipe with model %s: %s\n" % (progress, udpipe_model, udpipe_input))
  udpipe_command = [
    "curl", "-F", f"data={udpipe_input}",
    "-F", f"model={udpipe_model}",
    "-F", "tokenizer=no",
    "-F", "tagger=",
    "-F", "parser=",
    "https://lindat.mff.cuni.cz/services/udpipe/api/process"
  ]
  result = subprocess.run(udpipe_command, capture_output=True, text=True)
  try:
      response_json = result.stdout
      response_dict = json.loads(response_json)  # load the JSON
      udpipe_output = response_dict.get("result", "")
  except json.JSONDecodeError:
      warnings.warn("Error: Failed to decode JSON from curl output.")
      udpipe_output = dummy_conllu(udpipe_input)
  except Exception as e:
      warnings.warn(f"Unexpected error: {e}")
      udpipe_output = dummy_conllu(udpipe_input)
  return udpipe_output

def clean_for_udpipe (s):
  # UDPipe needs more cleaning. Parentheses need to be deleted.
  s = re.sub(r'\((.*?)\)', r'\1', s) # delete 0 at beginning of words
  s = re.sub(r'<(.*?)>', r'\1', s) # delete 0 at beginning of words
  return s

def get_conllu_word(word_id, udpipe_output):
    """
    retrieves the conllu columns for a specific word ID
    returns a dict conllu attributes for this ID
    """
    for line in udpipe_output.strip().split("\n"):
        if line.strip() and not line.startswith("#"):
            token_data = line.split("\t")
            if token_data[0] == str(word_id):
                # zip returns tuples [("ID", "1"), ("FORM", "word") etc] - dict takes first element as key
                return dict(zip(conllu_columns, token_data))
    return None

def dummy_conllu(udpipe_input):
    # Create a dummy CoNLL-U output string based on udpipe_input, with 9 columns filled.
    dummy_output = "# Fallback dummy output due to error\n"
    for i, line in enumerate(udpipe_input.strip().split('\n'), 1):
        word = line.split()[0]  # Assume word is the first item in each line
        # Construct the 9 columns for each word, filling in placeholders as needed
        dummy_output += f"{i}\tERROR\t_\t_\t_\t_\t_\t_\t_\t_\n"
    return dummy_output

def wordPerLineChat(splitUtt, mor):
  # for CHAT format: build one line (table row) for each token in utterance
  child_other = ''
  age = tags = ''
  age_days = wNr = 0
  thisRow = {}
  words = splitUtt.split(' ')
  if mor != '':
    tags = mor.split(' ')
  if len(words) == len(tags):
    equal = 'YES'
  else:
    equal = 'NO '
  wNr = 0
  thisRow = {}
  for w in words:
    wNr += 1
    t = l = f = ''  # tag (CHILDES)
    w = re.sub(r'@.*', '', w)
    if len(tags) >= wNr:
      # parse morphological annotation (%mor line)
      if mor != '':
        t = tags[wNr-1]
        if re.search(r'(.*)\|(.*)', t):
          m = re.search(r'(.*)\|(.*)', t)  # split tag and lemma
          t = m.group(1)
          l = m.group(2)
          if re.search(r'(.*?)[-&](.*)', l):
            m = re.search(r'(.*?)[-&](.*)', l)  # split lemma and morphology (lemma-INF, lemma$PRES...)
            l = m.group(1)
            f = m.group(2)
    # if there is childData for this speaker (=child), insert the child's age
    if childData.get(speaker) != None:
      child_other = "C"
      age = childData[speaker][1]
      age_days = childData[speaker][2]
    else:  # for caretakers, annotate the child's age (age_days)
      child_other = "X"
      for caretaker, data in childData.items():
        # check if there is an age_days variable 
        if len(data) > 2 and caretaker == "CHI":  # exclude multi-child corpus (Palasis)
            age_days = data[2]
    # build output line for word
    thisRow = {
      'utt_id': uttID + '_w' + str(wNr),
      'utt_nr': sNr,
      'w_nr': wNr,
      'speaker': speaker,
      'child_project' : child,
      'age': age,
      'age_days': age_days,
      'time_code': timeCode,
      'word': w,
      'pos': t,
      'lemma': l,
      'features': f,
      'annotation': equal,
      'utterance': utt
      }
    outRows.append(thisRow)   # append dictionary for this row to list of rows
  return(outRows)

def cleanUtt(s):
    # delete specific CHILDES annotation not needed for pos tagging (WIP - TODO check CHILDES documentation)
    # input:  unprocessed utterance
    # output: utterance cleaned of special annotation
    s = re.sub(r' 0([\S+])', r' \1', s) # delete 0 at beginning of words
    s = re.sub(r'0faire ', 'faire ', s) # faire + Inf is transcribed as '0faire' in York
    s = re.sub(r'<[^>]+> \[//?\] ', '', s) # repetitions (not in %mor), e.g. mais <je t'avais dit que> [/] je t'avais dit que ...
    s = re.sub(r'\[\!\] ?', ' ', s) 
    s = re.sub(r' ?\(\.\) ', ' , ', s)  # pauses (unknown to tagger) > comma
    s = re.sub(r'<([^>]+)>\s+\[%[^\]]+\]', r'\1', s) # corrections: qui <va> [% sdi=vais] la raconter . > va
    s = re.sub(r'<(0|www|xxx|yyy)[^>]+> ?', '', s) 
    s = re.sub(r'\+[<,]? ?', '', s)  
    s = re.sub(r'(0|www|xxx|yyy)\s', '', s)  # xxx = incomprehensible – yyy = separate phonetic coding
    s = re.sub(r'\[.*?\] ?', '', s)  # no words
    s = re.sub(r'\(([A-Za-z]+)\)', r'\1', s)  # delete parentheses around chars
    s = re.sub(r' \+/+', ' ', s)  # annotations for pauses (?) e.g. +//.
    s = re.sub(r'[_=]', ' ', s)  # eliminate _ and = 
    s = re.sub(r'[<>]', '', s)  # eliminate remaining '<>'
    s = re.sub(r'\s+', ' ', s)  # reduce spaces
    return(s)

def tokenise(s):
    # tokenise sentence for TreeTagger  (WIP - TODO: add rules from tokenise.pl + add Italian rules)
    # input:  unprocessed sentence
    # output: sentence tokenised for TreeTagger
    # 1) define cutoff characters and strings at beginning and end of tokens
    reBeginChar = re.compile('(\[\|\{\(\/\'\´\`"»«°<)') 
    reEndChar = re.compile('(\]\|\}\/\'\`\"\),\;\:\!\?\.\%»«>)') 
    reBeginString = re.compile('([dcjlmnstDCJLNMST]\'|[Qq]u\'|[Jj]usqu\'|[Ll]orsqu\')') 
    reEndString = re.compile('(-t-elles?|-t-ils?|-t-on|-ce|-elles?|-ils?|-je|-la|-les?|-leur|-lui|-mêmes?|-m\'|-moi|-nous|-on|-toi|-tu|-t\'|-vous|-en|-y|-ci|-là)') 
    # 2) cut
    s = re.sub(reBeginChar, r'\1 ', s)
    s = re.sub(reBeginString, r'\1 ', s)
    s = re.sub(reEndChar, r' \1', s)
    s = re.sub(reEndString, r' \1', s)
    s = re.sub(r'\s+', ' ', s)  # reduce spaces
    return(s)

def treeTagger(str):
    # input:  concatenated target items
    # output: tagged items stored in dictionaries with item IDs as key
    itemTagged = {}  # this dict stores tagged items in the format  Word_POS_Lemma ...
    itemLemmas = {}  # this dict stores Lemmas only
    itemPOS = {}     # this dict stores POS tags only
    itemWords = {}   # this dict stores words only
    taggerBin = os.path.expanduser('./tree-tagger')     # TreeTagger binary
    paramFile = os.path.expanduser(args.parameters)     # TreeTagger parameters
    if not os.path.exists(taggerBin):   # verify if tagger files exist
        print("tree-tagger binary not found:", taggerBin, " - trying current working directory...")
        taggerBin = os.path.expanduser('./tree-tagger')     # TreeTagger binary
        if not os.path.exists(taggerBin):   # verify if tagger files exist
            print("tree-tagger binary not found:", taggerBin, " - quitting.")
            quit()
    if not os.path.exists(paramFile):
        print("Parameter file not found:", paramFile, " -  trying current working directory...")
        paramFile = os.path.expanduser('./italian-utf.par')    # TreeTagger parameters
        if not os.path.exists(paramFile):
            print("Parameter file not found:", paramFile, " - quitting.")
            quit()
    str = re.sub(r' +', r'\n', str)      # 1 word per line
    with open('tagged.tmp', 'w') as tmp:
      tmp.write(str)  # write header
    # system call for TreeTagger: cat <tmp file>|tree-tagger parameters options
    #    next line takes pipe output as input
    #    check_output() returns output as a byte string that needs to be decoded using decode()
    p1 = subprocess.Popen(["cat", 'tagged.tmp'], stdout=subprocess.PIPE)
    tagged = subprocess.check_output([taggerBin, paramFile, '-token', '-lemma', '-sgml'], stdin=p1.stdout)
    tagged = tagged.decode('utf8')
    tagged = process_tagged_data(tagged)  # correct lemmas
    if args.hops != '' or args.conllu:
      tagged2conllu(tagged)  # write tabular format for CoNLL
    tagged = re.sub(r'\t([A-Za-z:]+)\t', r'_\1=', tagged)   # create annotation format: word_pos=lemma ...
    tagged = re.sub(r'\n', ' ', tagged)                     # put everything on one line
    tagged = correct_tagger_output(tagged)                    # correct errors
    for sentence in tagged.split("<s_"): #taggedItems: split the concatenated items
        if sentence == "":   # first element is empty: ignore
            continue
        reItem = re.compile('^([^>]+)> (.*)') # e.g.: <s_paris-julie.cha_u18342>
        if re.search(reItem, sentence):  # get the item number from the rest of code, e.g. (<s_)A23
            m = re.search(reItem, sentence)
            sentence = re.sub(r'^([^>]+)> ', ' ', sentence)  # leave an initial space for word matching
        else:
            print("Error: no item number found in item:", sentence)
#            quit()
        # generate output fields from each item
        key = m.group(1)
        itemTagged[key] = m.group(2)     #   dict   itemNr : sentence
        posLemmas = re.findall(r'=(.*?)[ $]', sentence)   # gets the list of lemmas...
        posTags   = re.findall(r'_(.*?)=', sentence)   # gets the list of tags...
        posWords  = re.findall(r' (.*?)_', sentence)   # gets the list of words...
        itemLemmas[key] = ' '.join(posLemmas)     #  ... and stores it in dictionary, 
        itemPOS[key] = ' '.join(posTags)     #  ... and stores it in dictionary
        itemWords[key] = ' '.join(posWords)     #  ... and stores it in dictionary
    return(itemWords, itemPOS, itemLemmas, itemTagged)

def process_tagged_data(tagged):
    print("\nCorrecting two-token lemmas introduced by PERCEO parameters, e.g. 'se endormir'")
    lines = tagged.strip().split('\n')
    processed_lines = []
    for line in lines:
        columns = line.split('\t')
        if len(columns) == 3 and re.search(' ', columns[2]):
            print(f"   - deleting first element in: {columns[2]}")
            columns[2] = re.sub(r'.*? ', '', columns[2])  # delete everything before space
        processed_lines.append('\t'.join(columns))
    concat_lines = '\n'.join(processed_lines)
    return concat_lines

def correct_tagger_output (tagged):
  print(f"Correcting the tagger output:")
  tagged = re.sub(r'([,\?])_NAM=<unknown>', r'\1_PON=,', tagged)
  tagged, count = re.subn('Marie_VER:pres=marier', 'Marie_NAM=Marie', tagged)
  print(f"   - {count} substitutions for: Marie")
  tagged, count = re.subn(r'( allez[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER:impe=NEWLEM:aller', tagged)
  print(f"   - {count} substitutions for: aller")
  tagged, count = re.subn(r'( attend[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:attendre', tagged)
  print(f"   - {count} substitutions for: attendre")
  tagged, count = re.subn(r'( dis[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:dire', tagged)
  print(f"   - {count} substitutions for: dire")
  tagged, count = re.subn(r'( enl.v.[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:enlever', tagged)
  print(f"   - {count} substitutions for: enlever")
  tagged, count = re.subn(r'( fai[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:faire', tagged)
  print(f"   - {count} substitutions for: faire")
  tagged, count = re.subn(r'( fini[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:finir', tagged)
  print(f"   - {count} substitutions for: finir")
  tagged, count = re.subn(r'( prend[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:prendre', tagged)
  print(f"   - {count} substitutions for: prendre")
  tagged, count = re.subn(r'( mett[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:mettre', tagged)
  print(f"   - {count} substitutions for: mettre")
  tagged, count = re.subn(r'( regard[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:regarder', tagged)
  print(f"   - {count} substitutions for: regarder")
  tagged, count = re.subn(r'( tomb[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:tomber', tagged)
  print(f"   - {count} substitutions for: tomber")
  tagged, count = re.subn(r'( vu[^_ ]*)_([^= ]+)=<unknown>', r' \1_VER=NEWLEM:voir', tagged)
  print(f"   - {count} substitutions for: voir")
  tagged, count = re.subn(r'( ![^_ ]*)_([^= ]+)=<unknown>', r' !_PON=!', tagged)
  print(f"   - {count} substitutions for: !")
  tagged, count = re.subn('NEWLEM:', '', tagged)
  print(f"  Total corrected lemmas: {count}")
  print("  Remaining <unknown>: ", len(re.findall(r'VER:[^=]+=<unknown>', tagged)))
  return(tagged)


def tagged2conllu_NEW(input_str, pos_utterance=None):
    conllu_out = 'parseme.conllu'
    print(f"Creating output file '{conllu_out}' for dependency parsing...")

    # Prepare to write the output
    with open(conllu_out, 'w') as parsetmp:
        sNr = wNr = 0
        out = ''
        lines = input_str.split("\n")

        for line in lines:
            line = line.strip()  # Remove leading/trailing whitespace
            if not line:
                continue  # Skip empty lines

            # Convert 3-column tagger output to 10-column CoNLL-U format
            print(f"DEBUG {line}")
            exit(0)
            match = re.match(r'^(.*)\t(.*)\t(.*)$', line)
            if match:
                # If the line has the expected three columns, proceed with conversion
                form, lemma, pos = match.groups()
                # Build the CoNLL-U line
                conllu_line = f"{wNr + 1}\t{form}\t{lemma}\t_\t{pos}\t_\t_\t_\t_\t_"
                out += conllu_line + "\n"
                wNr += 1
            else:
                print(f"Warning: Line does not match expected format: {line}")

            if re.search(r'^# item', line):
                # Check if it's a new sentence and write the previous one if it meets criteria
                if sNr > 0 and wNr > 0:
                    if not pos_utterance or re.search(r'\t' + pos_utterance, out):
                        parsetmp.write(f"{out}\n")  # Write the last sentence
                sNr += 1
                wNr = 0  # Reset word number for new sentence
                out = f"{line}\n"  # Store meta info for the new sentence

        # Write the final sentence if conditions are met
        if wNr > 0 and (not pos_utterance or re.search(r'\t' + pos_utterance, out)):
            parsetmp.write(f"{out}\n")
    parsetmp.close()
    return input_str

def tagged2conllu(str):
  conllu_out = 'parseme.conllu'
  print(f"Creating output file '{conllu_out}' for dependency parsing...")
  # convert 3-column tagger output to 10-column conllu format
  str = re.sub(r'(.*)\t(.*)\t(.*)', r'\1\t\3\t_\t\2\t_\t_\t_\t_\t_', str)
  reItem = re.compile('<s_([^>]+)>') # e.g.: <s_paris-julie.cha_u18342>
  str = re.sub(reItem, r'# item_id = \1', str)   # create CoNLL-U IDs
  # for each sentence, insert word numbers and write
  with open(conllu_out, 'w') as parsetmp:
    sNr = wNr = 0
    out = ''
    for line in str.split("\n"):
      if re.search(r'^# item', line):
        sNr += 1
        if sNr > 1 and wNr > 0:
          reVerb = re.compile('\t' + args.pos_utterance)
#          if re.search(reVerb, out):   # for now, only write sentences with verbs
          parsetmp.write(f"{out}\n")   # write the previous sentence
        wNr = 0 # reset variables
        out = ''
        out = f"{line}\n"  # store meta info for next sentence
      else:
        wNr += 1
        out += f"{wNr}\t{line}\n"  # append
    parsetmp.close()
  return(str)

###########################################################################
# main function
###########################################################################

if __name__ == "__main__":
   parser = argparse.ArgumentParser(
       description='''
Converts CHILDES CHAT format into one word per line table.
- Aligns words with matching information from annotation in %mor.
- Discards other annotation lines (%sit etc).

Examples:
> childes.py -m VER --pos_utterance VER --tagger_input -p perceo-spoken-french-utf.par Geneva.cha   

Add annotation based on the tagged string:
> childes.py -m VER --add_annotation --tagger_output --pos_utterance VER -p perceo-spoken-french-utf.par childes-all.cha
''', formatter_class = argparse.RawTextHelpFormatter   # allows triple quoting for multiple-line text
       )
   parser.add_argument('out_file', type=str,  help='output file')
   parser.add_argument(
        '-F', '--first_utterance', action='store_true',
        help='print utterance only for first token')
   parser.add_argument(
       '-a', '--add_annotation', action='store_true',
       help='add annotation based on rules matching the tagger output. Calls tag_analyser.py')
   parser.add_argument(
       '-c', '--conllu', action='store_true',
       help='create a parallel table in CoNLL-U format, as input for a dependency parser')
   parser.add_argument(
       '--hops', default = "", type = str,
       help='run hops parser with this model (NOT YET IMPLEMENTED: use --conllu and UDPipe instead)')
   parser.add_argument(
       '-m', '--match_tagging', default = "", type = str,
       help='match the tagger output against this regex')
   parser.add_argument(
       '-p', '--parameters', default = "", type = str,
       help='run TreeTagger with this parameter file')
   parser.add_argument(
       '--pos_utterance', default = "", type = str,
       help='print utterance only if pos matches this regex')
   parser.add_argument(
       '--tagger_input', action='store_true',
       help='print utterance as converted for tagger')
   parser.add_argument(
       '--tagger_output', action='store_true',
       help='print utterance as converted for tagger')
#   parser.add_argument(
#       '--tagger_output', nargs='?', const = "VER", default = "VER", type = str,
#       help='print utterance as converted for tagger (default "VER" if not provided)')
   parser.add_argument(
       '-u', '--ud_pipe', default = "", type = str,
       help='run UDPipe parser with this model (extremely slow: calls API for each utterance; use --conllu and UDPipe instead)')
   args = parser.parse_args()
   main(args)
