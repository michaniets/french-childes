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
__version__ = "6.0"
__status__ = "9.9.26"
__license__ = "GPL"

import sys
import argparse, re
import os
import subprocess
import csv
import html
import json
import tempfile
import gzip
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
    # Some corpora write CHAT's scope markers as angle quotation marks
    # (<nose spray> as ‹nose spray›, 35945 in the North American English data).
    # Normalised first, so every <...> rule below applies to them too.
    s = s.replace('‹', '<').replace('›', '>')
    # CHAT's omission markers. In '0the' / '0il' / '0ne' the omitted word itself
    # is written out and the rule below restores it. '0w', '0x' and '0zero' are
    # placeholders for an omission whose form is NOT recoverable, so restoring
    # them yields tokens 'w', 'x', 'zero'. They are dropped first, before that
    # rule can see them: 9491 tokens across the five corpora (w/0w 2403,
    # x/0x 4283, zero/0zero 2835). Genuine 'w' and 'x' in a transcript - the
    # German children say 'w wä' - are untouched, and so is '0was'.
    s = re.sub(r'\b0(?:w|x|zero)\b', ' ', s)
    # 0word -> word. Anchored at a word start, not on a preceding space: an
    # utterance-INITIAL '0il' / '0the' / '0I' used to keep its zero (about 2900
    # tokens), and 9126 utterances consisting of nothing but '0.' came out as a
    # token '0' plus a full stop. This also covers '0faire' / '0ne', which had a
    # rule of their own here for exactly that reason.
    s = re.sub(r'(^|\s)0(\S)', r'\1\2', s)
    s = re.sub(r'&=li ', ' ', s)                   # Remove non-canonical liaison markers (mostly in Lyon project)
    s = re.sub(r'<[^>]+> \[//?\] ', '', s)        # Remove retracings <...> [//]
    s = re.sub(r'\[\!\] ?', ' ', s)               # Remove stressing [!]
    # CHAT pauses, unfilled and timed: (.) (..) (...) (3.) (2.5) (5..) (1:20.).
    # This is standard CHAT markup, so it is removed for every language. Two
    # earlier limitations: only the dot-only forms were matched, and only when
    # followed by a space, so an utterance-final '(..)' survived; timed pauses
    # were removed in the English branch of strip_transcription_noise() alone.
    # German therefore kept 34283 timed pauses as literal tokens, which the
    # parser tagged PUNCT, and Italian kept 2916 residues ('..', '2.', '1.5')
    # left behind when the tokeniser split the parentheses off an unremoved
    # utterance-final pause.
    s = re.sub(r'\s*\(\d*:?\d*\.+\d*\)\s*', ' ', s)
    s = re.sub(r'<([^>]+)>\s+\[%[^\]]+\]', r'\1', s) # Keep text before comment <text> [% comment]
    s = re.sub(r'<(0|www|xxx|yyy)[^>]+> ?', '', s)   # Remove unintelligible marked with <>
    # CHAT utterance terminators. Every one of them ends the utterance, so they
    # are normalised to plain sentence punctuation - which also gives the
    # utterance the final PUNCT token UD expects:
    #   +...  trailing off        +..?  trailing off, question
    #   +/.   interrupted         +/?   interrupted question
    #   +//.  self-interrupted    +//?  self-interrupted question
    #   +"/.  quotation follows   +".   quotation precedes
    # The question-marked variants keep the question mark: mapping them to '.'
    # would discard the only record that the utterance was a question.
    # This must run BEFORE the '+<' / '+,' rule below, which strips the '+'
    # alone and left the rest behind as tokens - 245000 of them across the five
    # corpora ('...' 63920, '..' 47888, '/' 63556, '/.' 15449, '//.' 10165,
    # '"/.' 4329, '..?' 1202, '//?' 925, '/?' 612, '".' 549).
    s = re.sub(r'\+"?/{0,2}\.{0,2}\?', ' ? ', s)
    s = re.sub(r'\+"?/{0,2}\.{1,3}', ' . ', s)
    # Utterance-linking markers, none of which is part of the utterance:
    # +< lazy overlap, +, self-completion, ++ other-completion, +^ quick uptake,
    # +" quotation introducer. Only the first two were listed, so the others
    # left their second character standing as a token - '"' 33335, '^' 7180.
    # A bare '+' is the compound marker (ice+cream -> icecream), as before.
    s = re.sub(r'\+[+<,"^]? ?', '', s)
    s = re.sub(r'(0|www|xxx|yyy)\s', '', s)          # Remove unintelligible words
    s = re.sub(r'\[.*?\] ?', '', s)               # Remove all other bracketed content [...]
    # Keep text inside parentheses: (be)cause -> because, (d'ac)cord -> d'accord.
    # Letters incl. accented, apostrophe and hyphen only; digits and dots stay
    # excluded so that a pause the rule above somehow missed is left visible as
    # '(5.)' rather than silently turned into the word '5.'.
    s = re.sub(r"\(([A-Za-zÀ-ÿ'’\-]+)\)", r'\1', s)
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
# Italian enclitics (verb + clitic, clitic + clitic)
#-------------------------------------------------------
# UD treats a verb+clitic form as a multiword token with one syntactic word per
# clitic (sottoporgli -> sottopor + gli, glielo -> glie + lo). Left fused, the
# clitic has no node and therefore no relation, so every clitic query fails on
# enclisis - a loss that is not random, because enclisis is licensed only by
# infinitive, gerund, imperative and 'ecco', i.e. exactly the contexts an
# acquisition study is interested in. The fused form is also out of vocabulary
# for tagger and parser, so the verb's own lemma/POS are lost too (dammelo ->
# lemma 'Dammelare', dagliela -> 'dagliere', checked against the UDPipe API).
#
# Unlike French du/des, the decision cannot be deferred to the parser: a fused
# form carries no evidence, so its analysis comes back arbitrary (lascialo,
# aiutami, mettici -> NOUN/ADJ; girati -> VerbForm=Part in both the imperative
# and the participle context). The split must therefore be decided here, and the
# residual ambiguity recorded rather than silently resolved. Hence two tiers:
#
#   Tier A  the string alone identifies a verb+clitic: 'ecco', the geminated
#           irregular imperatives (dammelo, fammi, vattene), and any host whose
#           residue is a known infinitive or gerund. Always split.
#   Tier B  regular imperative + clitic, homographic with participles, nouns and
#           preposition+article (girati/andati, portale, dagli). Split only when
#           the host is a known imperative form and, for participle-shaped forms,
#           no auxiliary precedes. Marked Enclitic=B in MISC; candidates that
#           fail the test stay fused and are marked Enclitic=Cand, so the
#           remaining recall loss is measurable rather than invisible.

# Clitic clusters, mapped to their UD sub-tokens (glielo -> glie + lo).
IT_CLITIC_CLUSTERS = {
    'melo': ('me', 'lo'), 'mela': ('me', 'la'), 'meli': ('me', 'li'),
    'mele': ('me', 'le'), 'mene': ('me', 'ne'),
    'telo': ('te', 'lo'), 'tela': ('te', 'la'), 'teli': ('te', 'li'),
    'tele': ('te', 'le'), 'tene': ('te', 'ne'),
    'celo': ('ce', 'lo'), 'cela': ('ce', 'la'), 'celi': ('ce', 'li'),
    'cele': ('ce', 'le'), 'cene': ('ce', 'ne'),
    'velo': ('ve', 'lo'), 'vela': ('ve', 'la'), 'veli': ('ve', 'li'),
    'vele': ('ve', 'le'), 'vene': ('ve', 'ne'),
    'selo': ('se', 'lo'), 'sela': ('se', 'la'), 'seli': ('se', 'li'),
    'sele': ('se', 'le'), 'sene': ('se', 'ne'),
    'glielo': ('glie', 'lo'), 'gliela': ('glie', 'la'), 'glieli': ('glie', 'li'),
    'gliele': ('glie', 'le'), 'gliene': ('glie', 'ne'),
}
IT_CLITIC_SINGLES = ('gli', 'mi', 'ti', 'ci', 'vi', 'si', 'lo', 'la', 'li', 'le', 'ne')

# Hosts truncated by gemination before a SINGLE clitic (gold ISDT/PoSTWITA: dammi ->
# dam + mi, dicci -> dic + ci). Before a cluster the doubled consonant goes to the
# clitic instead (vattene -> va + te + ne), which analyse_enclitic() handles separately.
IT_GEMINATE_HOSTS = {'dam', 'dim', 'fam', 'dac', 'dic', 'fac', 'vac', 'stac'}

# The five monosyllabic irregular imperatives (dare/dire/fare/andare/stare) geminate
# the clitic's consonant before a SINGLE clitic - dammi not dami, dicci not dici -
# so the bare stem must never license a Tier B split against a plain single clitic;
# only the geminated form in IT_GEMINATE_HOSTS above does. 'gli' is the one clitic
# that never geminates (dagli/digli are the correct gold forms, not *daggli), so it
# is exempt from this exclusion - see the suffix != 'gli' check in analyse_enclitic().
#
# Each bare stem is also a common ordinary word (preposition 'di'/'da', 3sg
# indicative 'fa'/'va'/'sta'), so without this exclusion, analyse_enclitic() finds a
# spurious host+clitic reading for many real words. Checked exhaustively (5 stems x
# 11 clitics = 55 forms) against the LibreOffice it_IT hunspell dictionary with
# affix expansion; of the 50 non-'gli' combinations, these 20 are real Italian words
# that would otherwise be mis-split: dici, divi, dati, dine, diti, davi, fasi, fati,
# favi, vasi, vati, vala, vale, vali, valo, vane, stami, stasi, stati, stavi.
# (dagli/digli/fagli/vagli/stagli are additionally real words, but stay split: see
# the 'gli' exemption above. 'stati'/'state' were already in IT_ENCLITIC_STOPLIST for
# the separate participle-homograph reason and remain there redundantly.)
IT_MONOSYLLABIC_GEMINATING_IMP = {'da', 'di', 'fa', 'va', 'sta'}

# Seed verb lexicon. Deliberately small and child-language oriented; it exists to
# license the split, not to describe the language, and is meant to be replaced by
# a list extracted from the UD Italian treebanks (--verb_lexicon).
IT_VERBS = """
accendere aggiustare aiutare alzare andare aprire arrabbiare arrivare asciugare
ascoltare aspettare attaccare avere baciare bagnare ballare bere buttare cacciare
cadere cambiare camminare cantare capire cercare chiamare chiedere chiudere
colorare cominciare comprare contare coprire correre costruire credere dare dire
disegnare diventare dividere dormire entrare essere fare fermare finire giocare
girare gonfiare guardare infilare lanciare lasciare lavare legare leggere mangiare
mettere mostrare muovere nascondere parlare passare pensare perdere pescare
pettinare piacere piangere piegare portare posare potere prendere preparare
provare pulire raccontare restare ricordare ridere riempire rimanere rispondere
rompere rubare salire salutare saltare sapere sbagliare scappare scegliere
scendere sciogliere scrivere sedere seguire sentire soffiare sognare sorridere
spegnere spingere sporcare spostare staccare stare stringere studiare svegliare
tagliare telefonare tenere tirare toccare togliere tornare trovare tuffare usare
uscire vedere venire versare vestire viaggiare vincere volare volere
""".split()

# Irregular imperative/2sg forms that the regular pattern below does not generate.
IT_IRREGULAR_IMP = {
    'fare': ('fa', 'fai', 'fate', 'facciamo'), 'dare': ('da', 'dai', 'date', 'diamo'),
    'dire': ('di', 'dite', 'diciamo'), 'andare': ('va', 'vai', 'andate', 'andiamo'),
    'stare': ('sta', 'stai', 'state', 'stiamo'), 'venire': ('vieni', 'venite'),
    'tenere': ('tieni', 'tenete'), 'sedere': ('siedi', 'sedete'), 'uscire': ('esci', 'uscite'),
    'togliere': ('togli', 'togliete'), 'scegliere': ('scegli', 'scegliete'),
    'spegnere': ('spegni', 'spegnete'), 'rimanere': ('rimani', 'rimanete'),
    'sapere': ('sappi',), 'essere': ('sii', 'siate'), 'avere': ('abbi', 'abbiate'),
    'bere': ('bevi', 'bevete'), 'salire': ('sali', 'salite'),
}
# Gerunds that are not stem + ando/endo.
IT_IRREGULAR_GER = {'fare': 'facendo', 'dire': 'dicendo', 'bere': 'bevendo'}

# Forms that survive the lexicon test but are not verb+clitic. Kept short on
# purpose: the lexicon check below rejects almost all homographs by itself
# (natale, palline, macchine, chiavi, animali all fail it).
IT_ENCLITIC_STOPLIST = {'portale', 'portali', 'cantale', 'finale', 'finali', 'natale',
                        # participles and nouns that are also possible imperative+clitic
                        # forms; overwhelmingly the former, so never split them
                        'fatti', 'fatto', 'fatte', 'detti', 'dette', 'stati', 'state'}

# Auxiliaries: a preceding one makes a participle reading of a form like
# 'girati'/'arrivati' far more likely than an imperative one.
IT_AUXILIARIES = {
    'sono', 'sei', 'è', 'e', 'siamo', 'siete', 'era', 'eri', 'ero', 'erano', 'eravamo',
    'eravate', 'sarà', 'saranno', 'sarei', 'stato', 'stata', 'stati', 'state',
    'ho', 'hai', 'ha', 'abbiamo', 'avete', 'hanno', 'avevo', 'avevi', 'aveva',
    'avevamo', 'avevano', 'avrà', 'avranno', 'avrei',
}

# Italian preposizioni articolate: preposition + definite article written as one
# word. Only 'di' also forms the PARTITIVE article ('Max legge dei libri'), which
# UD keeps as a single DET, so di-forms are genuinely ambiguous between DET and
# ADP+DET and must be left fused for the parser to decide - exactly like French
# du/des, and for the same measured reason: in UD_Italian-ISDT a split form heads
# an 'obj' in 1 of 15814 cases (0.01%), an unsplit partitive in 57% of 75. Fusing
# gets both readings right (dei libri -> obj, il gusto del pane -> nmod).
#
# a/in/su/con never form a partitive, so they are always ADP+DET. Left fused the
# parser loses the preposition and reads the noun as a core argument ('è andata
# al mare' -> mare/nsubj, 'sta sul tavolo' -> tavolo/obj: 23 of 117 such forms
# were misanalysed in one Roma file). They are therefore pre-split here, and the
# fused surface is restored as a multiword token by the 'amalgami' rules.
IT_CONTRACTIONS = {
    'al': 'a il', 'allo': 'a lo', 'alla': 'a la', 'ai': 'a i',
    'agli': 'a gli', 'alle': 'a le', "all'": "a l'",
    'dal': 'da il', "dall'": "da l'",
    'nel': 'in il', 'nello': 'in lo', 'nella': 'in la', 'nei': 'in i',
    'negli': 'in gli', 'nelle': 'in le', "nell'": "in l'",
    'sul': 'su il', 'sullo': 'su lo', 'sulla': 'su la', 'sui': 'su i',
    'sugli': 'su gli', 'sulle': 'su le', "sull'": "su l'",
    'col': 'con il', 'coi': 'con i',
}

# da-forms that are homographic with 'dare' (dai = 'you give' / 'come on!',
# dalla/dallo/dalle/dagli = da' + enclitic) are deliberately NOT in the table
# above. ISDT is newswire and has dai 166x as a contraction against 2x as a verb,
# but child language inverts that: in Roma 'dai' is 17x VERB ('me lo dai?'), 7x
# ADV ('dai!') and only about 6x the contraction, and 'dalla a mamma' is 'give it
# to mum'. Splitting them would corrupt a frequent verb to repair a rare
# contraction, so they stay fused and keep the obl error. Same reasoning as
# IT_MONOSYLLABIC_GEMINATING_IMP.
IT_CONTRACTIONS_VETOED = {'dai', 'dallo', 'dalla', 'dalle', 'dagli'}


# German preposition+article contractions. UD German has exactly one class of
# multiword token - "the contractions of prepositions and definite articles"
# (universaldependencies.org/de) - and the split is unconditional: in
# UD_German-GSD all 4774 of these are split and none is left whole, superlative
# 'am' included. So there is nothing for a post-parse rule to decide and no .grs
# is needed; childes.py writes the range line itself.
#
# Leaving them fused is not merely a surface matter: the parser reads 'ins Bett'
# as DET + obj rather than ADP + DET + obl (checked against the API), the same
# way French 'au' loses its preposition.
#
# The -m, -s and -r forms are unambiguous. The -n forms are not: colloquial
# 'aufn' is 'auf den' but can be 'auf einen', and 'was fürn Auto' is 'für ein'
# (5 of 41 'fürn' in this corpus). They are expanded to the definite reading,
# which is the majority one, because the alternative is to lose them entirely.
DE_CONTRACTIONS = {
    # + dem
    'im': ('in', 'dem'), 'am': ('an', 'dem'), 'beim': ('bei', 'dem'),
    'vom': ('von', 'dem'), 'zum': ('zu', 'dem'), 'aufm': ('auf', 'dem'),
    'ausm': ('aus', 'dem'), 'mitm': ('mit', 'dem'), 'nachm': ('nach', 'dem'),
    'unterm': ('unter', 'dem'), 'vorm': ('vor', 'dem'), 'hinterm': ('hinter', 'dem'),
    'überm': ('über', 'dem'),
    "auf'm": ('auf', 'dem'), "aus'm": ('aus', 'dem'), "mit'm": ('mit', 'dem'),
    # + der
    'zur': ('zu', 'der'),
    # + das
    'ins': ('in', 'das'), 'ans': ('an', 'das'), 'aufs': ('auf', 'das'),
    'ums': ('um', 'das'), 'übers': ('über', 'das'), 'fürs': ('für', 'das'),
    'durchs': ('durch', 'das'), 'unters': ('unter', 'das'), 'vors': ('vor', 'das'),
    'hinters': ('hinter', 'das'),
    "in's": ('in', 'das'), "an's": ('an', 'das'), "auf's": ('auf', 'das'),
    "um's": ('um', 'das'), "über's": ('über', 'das'), "für's": ('für', 'das'),
    "durch's": ('durch', 'das'), "unter's": ('unter', 'das'), "vor's": ('vor', 'das'),
    "hinter's": ('hinter', 'das'),
    # + den (colloquial, see the caveat above)
    'aufn': ('auf', 'den'), 'fürn': ('für', 'den'), 'übern': ('über', 'den'),
    'untern': ('unter', 'den'), 'mitn': ('mit', 'den'),
}

# Forms the pattern would generate that are ordinary words in this corpus, and
# must never be split: 'Bein' (leg, 504x - 172 of them after am/das/dem/ein),
# 'vorn' (the adverb, 'von vorn'), 'Hintern' (every occurrence checked is the
# noun), plus CHAT artefacts like 'inn(en)drin' and 'Zun(ge)'.
DE_CONTRACTIONS_VETOED = {'bein', 'vorn', 'hintern', 'inn', 'zun', 'ann',
                          'auss', 'umm', 'mits', 'beis', 'zus', 'aufr', 'ausr'}

# Stems that may carry an enclitic 's (= es): everything except a preposition,
# which would make it a contraction instead and is handled above.
DE_CLITIC_S = re.compile(r"^(.+[a-zäöüß])'s$", re.IGNORECASE)


def _it_verb_forms(lemmas):
    """
    Builds the sets of host forms the splitter accepts, from a list of infinitives:
    truncated infinitives (mangiare -> mangiar), gerunds (mangiando), and the
    imperative/2sg forms that can carry an enclitic (guarda, guardate, guardiamo).
    Returns (infinitives, gerunds, imperatives); 'infinitives' maps the truncated
    form back to its lemma, which the tagger repair below needs.
    """
    inf, ger, imp = {}, set(), set()
    for lemma in lemmas:
        if len(lemma) < 4:
            continue
        # gold truncation: mangiare -> mangiar, but sottoporre -> sottopor (not -porr)
        inf[lemma[:-2] if lemma.endswith('rre') else lemma[:-1]] = lemma
        stem, ending = lemma[:-3], lemma[-3:]
        if lemma.endswith('orre'):                # imporre -> imponi, imponendo
            imp.add(lemma[:-3] + 'ni')
            ger.add(lemma[:-3] + 'nendo')
        if ending == 'are':
            ger.add(stem + 'ando')
            imp.update((stem + 'a', stem + 'ate', stem + 'iamo'))
        elif ending in ('ere', 'ire'):
            ger.add(stem + 'endo')
            imp.update((stem + 'i', stem + ending[0] + 'te', stem + 'iamo'))
        if lemma in IT_IRREGULAR_GER:
            ger.add(IT_IRREGULAR_GER[lemma])
        imp.update(IT_IRREGULAR_IMP.get(lemma, ()))
    return inf, ger, imp

#-------------------------------------------------------
# HTML export class for UD parsed data
#-------------------------------------------------------
INDEX_PAGE = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>CHILDES parses</title><style>
:root{--fg:#1a1a1a;--bg:#fff;--mut:#666;--line:#ddd;--acc:#06c;--head:#f6f6f6}
@media(prefers-color-scheme:dark){:root{--fg:#e0e0e0;--bg:#17191d;--mut:#9aa;--line:#333;
 --acc:#6aa9ff;--head:#22252a}}
body{font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--fg);
 background:var(--bg);margin:0 auto;padding:28px 18px;max-width:820px}
h1{font-size:19px;margin:0 0 2px}
p.sub{color:var(--mut);margin:0 0 20px;font-size:13px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--head);font-size:12px;font-weight:600;color:var(--mut)}
td.n{text-align:right;color:var(--mut);white-space:nowrap}
td.p a{display:inline-block;min-width:1.7em;text-align:center;margin:1px 2px;padding:1px 5px;
 border:1px solid var(--line);border-radius:4px;color:var(--acc);text-decoration:none}
td.p a:hover{border-color:var(--acc)}
</style></head><body>
<h1>CHILDES parses</h1>
<p class=sub>Directory <code>__DIR__</code>. Each number is one page of utterances;
open a page and use its filter box, or follow a link of the form
<code>page.html#&lt;item_id&gt;</code> from the tables.</p>
<table><tr><th>corpus</th><th>pages</th><th>n</th><th>size</th></tr>
__ROWS__
</table></body></html>"""

class HtmlExporter:
    """
    Writes the parses as a self-contained viewer: the sentences are embedded as
    compact JSON and the dependency arcs are drawn in the browser as SVG.

    The previous version emitted one pre-rendered block of coloured markup per
    sentence, which cost about 600 bytes each - 65% of it markup - and left no
    structure to draw a real tree from. Storing the data instead is roughly three
    times smaller and lets the page draw arcs, filter, and stay readable.

    No dependencies, no CDN, no server: one file that works over file://.
    Filenames and #item_id anchors are unchanged, so the URL columns in the CSV
    keep resolving.
    """

    PAGE = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>CHILDES parses: __TITLE__</title><style>
:root{--fg:#1a1a1a;--bg:#fff;--mut:#666;--line:#ddd;--code:#f6f6f6;
 --chi:#0a5c2e;--acc:#06c;--tok:#111;--pos:#0a6;--dep:#06c;--mwt:#999}
@media(prefers-color-scheme:dark){:root{--fg:#e0e0e0;--bg:#17191d;--mut:#9aa;--line:#333;
 --code:#22252a;--chi:#4cc38a;--acc:#6aa9ff;--tok:#eee;--pos:#4cc9a0;--dep:#6aa9ff;--mwt:#888}}
*{box-sizing:border-box}
body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--fg);
 background:var(--bg);margin:0}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
 padding:10px 16px;z-index:9;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#q{font:14px inherit;padding:6px 10px;width:min(380px,55vw);border:1px solid var(--line);
 border-radius:6px;background:var(--bg);color:var(--fg)}
#n{color:var(--mut);font-size:13px}
nav a{color:var(--acc);text-decoration:none;margin:0 6px}
main{padding:4px 16px 40vh;max-width:1100px}
.s{border-bottom:1px solid var(--line);padding:9px 0}
.s:target{background:#ffe89a33;border-radius:4px}
.h{font-size:12px;color:var(--mut)}
.h b{color:var(--acc);font-weight:600}
.chi .h em{color:var(--chi);font-weight:700;font-style:normal}
.u{margin:3px 0;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;
 background:var(--code);padding:5px 9px;border-left:3px solid var(--line);border-radius:3px;
 overflow-x:auto;white-space:pre-wrap}
.chi .u{border-left-color:var(--chi)}
details>summary{cursor:pointer;color:var(--acc);font-size:12px;list-style:none;padding:2px 0}
details>summary::before{content:"\25B8 tree"}
details[open]>summary::before{content:"\25BE tree"}
.t{overflow-x:auto}
svg{display:block}
.tk{fill:var(--tok);font:13px ui-monospace,Menlo,monospace}
.ps{fill:var(--pos);font:10px ui-monospace,Menlo,monospace}
.dp{fill:var(--dep);font:10px ui-monospace,Menlo,monospace}
.mw{fill:var(--mwt);font:10px ui-monospace,Menlo,monospace}
path{fill:none;stroke:var(--mut);stroke-width:1.2}
.err{color:#c33;font-style:italic;font-size:12px}
</style></head><body>
<header><nav>__NAV__</nav><input id=q placeholder="filter by word, speaker or id…" autocomplete=off>
<span id=n></span></header><main id=m></main>
<script id=d type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('d').textContent),M=document.getElementById('m'),
 N=document.getElementById('n');
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function svg(t,mwt){
 const CW=8,PAD=14,GAP=18;let x=PAD;const xs=[];
 t.forEach(k=>{const w=Math.max(k[1].length,k[2].length,(k[4]||'').length)*CW;xs.push(x+w/2);x+=w+GAP;});
 const W=x+PAD,md=t.reduce((m,k)=>Math.max(m,k[3]?Math.abs(k[0]-k[3]):0),1),
  AH=Math.min(26+md*13,160),H=AH+62;let p='';
 const ms={};(mwt||[]).forEach(g=>ms[g[0]]=g[2]);
 t.forEach((k,i)=>{
  const h=k[3];
  if(h>0&&xs[h-1]!==undefined){
   const a=xs[i],b=xs[h-1],d=Math.abs(k[0]-h),y=AH-Math.min(d*13,AH-18),dir=b>a?1:-1;
   p+=`<path d="M${a} ${AH} C${a} ${y} ${b} ${y} ${b} ${AH}"/>`;
   p+=`<path d="M${b-7*dir} ${AH-6} L${b} ${AH} L${b-7*dir} ${AH+3}" stroke-width="1"/>`;
   p+=`<text class=dp x=${(a+b)/2} y=${y-4} text-anchor=middle>${esc(k[4])}</text>`;}
  p+=`<text class=tk x=${xs[i]} y=${AH+20} text-anchor=middle>${esc(k[1])}</text>`;
  p+=`<text class=ps x=${xs[i]} y=${AH+34} text-anchor=middle>${esc(k[2])}</text>`;
  if(ms[k[0]])p+=`<text class=mw x=${xs[i]} y=${AH+48} text-anchor=middle>⟨${esc(ms[k[0]])}⟩</text>`;});
 return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${p}</svg>`;}
function card(o){
 return `<div class="s${o.s==='CHI'?' chi':''}" id="${esc(o.i)}"><div class=h>ID: <b>${esc(o.i)}</b>`+
  ` | ${esc(o.p)} | <em>${esc(o.s)} | ${esc(o.a)}</em></div><div class=u>${esc(o.c)}</div>`+
  `<details><summary></summary><div class=t></div></details></div>`;}
function render(list){
 M.innerHTML=list.map(card).join('');
 N.textContent=list.length+' of '+D.length+' utterances';
 M.querySelectorAll('details').forEach((dt,k)=>dt.addEventListener('toggle',()=>{
  if(!dt.open||dt.dataset.done)return;dt.dataset.done=1;const o=list[k];
  dt.querySelector('.t').innerHTML=o.e?`<p class=err>no tree for this sentence: ${esc(o.e)}</p>`
   :svg(o.t,o.m);}));}
let shown=D.slice(0,400);render(shown);
document.getElementById('q').addEventListener('input',e=>{
 const v=e.target.value.toLowerCase().trim();
 render((v?D.filter(o=>(o.c+' '+o.i+' '+o.s).toLowerCase().includes(v)):D).slice(0,400));});
function jump(){const id=decodeURIComponent(location.hash.slice(1));if(!id)return;
 if(!document.getElementById(id)){const o=D.find(x=>x.i===id);if(o)render([o]);}
 const el=document.getElementById(id);
 if(el){el.scrollIntoView();const dt=el.querySelector('details');if(dt)dt.open=true;}}
addEventListener('hashchange',jump);jump();
</script></body></html>"""

    def __init__(self, output_dir, file_basename, chunk_size=1000):
        self.output_dir = output_dir
        self.file_basename = file_basename
        self.chunk_size = chunk_size
        self.project = ''
        os.makedirs(output_dir, exist_ok=True)

    def write_index(self):
        """
        Writes an index.html listing every viewer file in the output directory.

        The directory accumulates across runs - one childes.py run handles one
        corpus and writes <proj><chunk>.html - so the index is rebuilt from what
        is actually on disk rather than from this run alone, and corpora
        converted earlier stay listed. The corpus name comes from each file's
        own <title>, which is the only place the full name survives (the
        filenames are truncated to three letters to keep URLs short).
        """
        files = [f for f in os.listdir(self.output_dir)
                 if f.endswith('.html') and f != 'index.html']
        if not files:
            return

        def chunk_no(name):
            m = re.match(r'.*?(\d+)\.html$', name)
            return int(m.group(1)) if m else 0

        corpora = {}
        for f in sorted(files, key=lambda n: (re.sub(r'\d+\.html$', '', n), chunk_no(n))):
            path = os.path.join(self.output_dir, f)
            try:
                with open(path, encoding='utf8') as fh:
                    head = fh.read(4096)
            except OSError:
                continue
            m = re.search(r'<title>(.*?)</title>', head, re.S)
            title = (m.group(1).strip() if m else f)
            title = re.sub(r'^CHILDES parses:\s*', '', title)
            size = os.path.getsize(path)
            corpora.setdefault(title, []).append((f, size))

        rows = []
        for corpus in sorted(corpora):
            links = ' '.join(
                f'<a href="{html.escape(f)}">{chunk_no(f) + 1}</a>' for f, _ in corpora[corpus])
            total = sum(sz for _, sz in corpora[corpus]) / 1024
            rows.append(f'<tr><td>{html.escape(corpus)}</td><td class=p>{links}</td>'
                        f'<td class=n>{len(corpora[corpus])}</td>'
                        f'<td class=n>{total:,.0f} KB</td></tr>')

        page = INDEX_PAGE.replace('__ROWS__', '\n'.join(rows)).replace(
            '__DIR__', html.escape(os.path.basename(os.path.abspath(self.output_dir))))
        with open(os.path.join(self.output_dir, 'index.html'), 'w', encoding='utf8') as f:
            f.write(page)
        sys.stderr.write(f"- Index of {len(files)} page(s) in {self.output_dir}/index.html\n")

    def export(self, parsed_conllu_str, original_rows):
        sentences = parse(parsed_conllu_str)

        header_info_map = {}
        for row in original_rows:
            base = re.match(r'(.*)_w\d+', row['utt_id']).group(1)
            if base not in header_info_map:
                header_info_map[base] = {
                    'child_project': row['child_project'],
                    'speaker': row['speaker'],
                    'age': row['age'] if row['age'] else '_',
                    'utterance': row['utterance'],
                }

        html_links = {}
        total_chunks = (len(sentences) + self.chunk_size - 1) // self.chunk_size
        for chunk_id in range(total_chunks):
            sys.stderr.write(f"\rWriting HTML files to {self.output_dir} "
                             f"for chunk {chunk_id+1}/{total_chunks}")
            sys.stderr.flush()
            chunk = sentences[chunk_id * self.chunk_size:(chunk_id + 1) * self.chunk_size]
            html_filename = f"{self.project[:3]}{chunk_id}.html"
            html_filepath = os.path.join(self.output_dir, html_filename)

            data = []
            for sentence in chunk:
                if 'item_id' not in sentence.metadata:
                    continue
                utt_id = sentence.metadata['item_id']
                info = header_info_map.get(utt_id, {})
                html_links[utt_id] = {'local': html_filepath, 'file': html_filename}

                toks, mwt = [], []
                for tok in sentence:
                    tid = tok['id']
                    if isinstance(tid, tuple):
                        if tid[1] == '-':
                            mwt.append([tid[0], tid[2], tok['form']])
                        continue
                    head = tok['head'] if isinstance(tok['head'], int) else 0
                    toks.append([tid, tok['form'], tok['upos'] or '_', head, tok['deprel'] or '_'])

                # Same check as before: a malformed graph (typically a cycle, so no
                # root) is reported in the page instead of silently disappearing.
                err = ''
                try:
                    sentence.to_tree()
                except Exception as e:
                    err = str(e)
                    sys.stderr.write(f"\nCould not generate tree for {utt_id}: {e}\n")

                data.append({'i': utt_id, 'p': info.get('child_project', 'N/A'),
                             's': info.get('speaker', 'N/A'), 'a': info.get('age', '_'),
                             'c': info.get('utterance', '[Utterance not found]'),
                             't': toks, 'm': mwt, 'e': err})

            nav = f"<b>CHILDES project {self.project}</b>"
            if chunk_id > 0:
                nav = f'<a href="{self.project[:3]}{chunk_id-1}.html">&laquo; previous</a>' + nav
            if chunk_id < total_chunks - 1:
                nav += f'<a href="{self.project[:3]}{chunk_id+1}.html">next &raquo;</a>'

            page = (self.PAGE
                    .replace('__TITLE__', html.escape(self.file_basename))
                    .replace('__NAV__', nav)
                    .replace('__DATA__', json.dumps(data, ensure_ascii=False,
                                                    separators=(',', ':'))))
            with open(html_filepath, 'w', encoding='utf8') as f:
                f.write(page)
        sys.stderr.write("\n")
        self.write_index()

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
        self.encliticInfo = {}   # uttID -> {'groups': [...], 'misc': {...}}, see split_italian_enclitics()
        self._it_hosts = None
        self._it_stoplist = None
        self.conllu_input_file = None
        self.presegmented_input_file = None
        self.html_exporter = None
        if args.html_dir:
            file_basename = os.path.basename(args.chat_file)
            file_basename = os.path.splitext(file_basename)[0]
            self.html_exporter = HtmlExporter(args.html_dir, file_basename, chunk_size=args.chunk_html)

    def fuse_contractions(self):
        """
        Whether preposition+determiner contractions must be kept fused as a single
        token (French du/des/au/aux) by tokenising here, instead of letting UDPipe's
        own tokenizer decide whether to split them.

        Splitting them costs dependency accuracy, because the split representation
        and the 'obj' relation are near-disjoint in the training data: in
        UD_French-GSD (train), a split du/des has an 'obj' head noun in 81 of 6795
        cases (1.2%), an unsplit one in 680 of 1675 (41%). Once the tokenizer has
        split, the parser has almost no evidence for 'obj' and returns 'obl:arg'
        instead - which silently destroys the obj/obl:arg distinction. Verified
        against the API for french-gsd/-sequoia/-partut/-spoken: none of them
        analyses a partitive direct object ('Max mange du sucre') as 'obj'.

        Only relevant where the tokenizer's decision is context-dependent AND
        entails a change of deprel. English 'gonna' -> 'gon'+'na' is unconditional
        and deprel-neutral, so UD tokenisation is kept there.
        """
        if self.args.fuse_contractions == 'yes': return True
        if self.args.fuse_contractions == 'no': return False
        return bool(getattr(self, 'language', '') and re.search(r'fra|french|ita|italian', self.language))

    def split_german_here(self):
        """
        Whether German tokenisation must be done here rather than left to UDPipe.

        UDPipe's own tokenizer splits the standard contractions it was trained on
        (im, ins, am ...) but not the colloquial ones that spoken data is full of:
        aufm, aufn, ausm, mitm and the apostrophised durch's, über's - about 220
        tokens in this corpus that would otherwise stay fused, plus a further
        inconsistency between a run with a tagger and one without, since the
        tagger path never reaches UDPipe's tokenizer at all.
        """
        return bool(re.search(r'deu|german', getattr(self, 'language', '') or ''))

    def split_enclitics(self):
        """
        Whether Italian verb+clitic forms are split into UD syntactic words here,
        and how far. Returns 'none', 'A' (unambiguous hosts only) or 'AB'.

        Unlike the French du/des case there is nothing to defer to the parser: a
        fused enclitic form is out of vocabulary, so its analysis comes back
        arbitrary and cannot be used to decide the split afterwards. See the
        module-level comment above IT_CLITIC_CLUSTERS.
        """
        mode = self.args.split_enclitics
        if mode == 'no': return 'none'
        if mode == 'safe': return 'A'
        if mode == 'yes': return 'AB'
        return 'AB' if re.search(r'ita|italian', getattr(self, 'language', '') or '') else 'none'

    def italian_hosts(self):
        """
        Host forms the splitter accepts, built once from IT_VERBS plus any lemmas in
        --verb_lexicon (first tab-separated column, '%' comments and a 'lemma'
        header ignored - the format of french-verbs.grewlex.tsv).
        """
        if self._it_hosts is None:
            lemmas = list(IT_VERBS)
            path = getattr(self.args, 'verb_lexicon', None)
            if path and os.path.exists(path):
                with open(path, encoding='utf8') as f:
                    for line in f:
                        lemma = line.split('\t')[0].strip()
                        if lemma and lemma != 'lemma' and not lemma.startswith('%'):
                            lemmas.append(lemma)
                sys.stderr.write(f"\n- Enclitic splitting: {len(lemmas)} verb lemmas ({path}).\n")
            self._it_hosts = _it_verb_forms(lemmas)
        return self._it_hosts

    def enclitic_stoplist(self):
        """
        Forms that must never be split, however well they parse as host + clitic.
        A verb lexicon raises recall but also creates collisions: 'dici' is a form
        of dire, yet also parses as the imperative di + ci, and 'animali'/'porti'
        as anima+li / por+ti once animare and porre are in the lexicon. The list in
        --enclitic_stoplist vetoes them; the one shipped with this distribution
        holds every form ending in a clitic string that the UD Italian treebanks
        annotate as a simple token, i.e. as evidence that it is not enclitic.
        """
        if self._it_stoplist is None:
            self._it_stoplist = set(IT_ENCLITIC_STOPLIST)
            path = getattr(self.args, 'enclitic_stoplist', None)
            if path and os.path.exists(path):
                with open(path, encoding='utf8') as f:
                    self._it_stoplist.update(w.strip().lower() for w in f
                                             if w.strip() and not w.startswith('%'))
                sys.stderr.write(f"- Enclitic splitting: {len(self._it_stoplist)} forms vetoed ({path}).\n")
        return self._it_stoplist

    def analyse_enclitic(self, token):
        """
        Analyses one token as host + clitic(s), or returns None.

        Among the competing analyses the one with the LONGEST licensed host wins.
        That is what separates guardatelo = guardate + lo from the shorter and
        wrong guarda + te + lo, and fagli = fa + gli from fag + li (both gold).
        A cluster whose first element repeats the host's final consonant absorbs
        the gemination (vattene -> va + te + ne, dammelo -> da + me + lo), while
        before a single clitic the host keeps it (dammi -> dam + mi) - both
        conventions taken from UD_Italian-ISDT/PoSTWITA rather than assumed. The
        one exception is 'gli', which never geminates (dagli/digli are gold, not
        *daggli) - see IT_MONOSYLLABIC_GEMINATING_IMP for why the exception matters:
        without it, the bare stem also licenses splits like dici/stavi/vasi, which
        are ordinary real words, not host+clitic.

        Returns (subtokens, tier): 'A' where the string alone identifies a
        verb+clitic (ecco, geminated imperative stem, infinitive, gerund, or any
        clitic cluster), 'B' for a regular imperative host, which is homographic
        with participles, nouns and preposition+article.
        """
        inf, ger, imp = self.italian_hosts()
        low = token.lower()
        # a bare cluster: only the glie- series is unambiguous as a free token
        # (melo, tela, vela are ordinary words), gold glielo -> glie + lo
        if low in IT_CLITIC_CLUSTERS and low.startswith('glie'):
            first, second = IT_CLITIC_CLUSTERS[low]
            return ([token[:len(first)], second], 'A')
        if len(low) < 4 or low in self.enclitic_stoplist():
            return None

        def licensed(residue):
            if residue == 'ecco' or residue in inf or residue in ger:
                return 'A'
            return 'B' if residue in imp else None

        best = None      # (host, clitics, tier), longest host wins
        for suffix in list(IT_CLITIC_CLUSTERS) + list(IT_CLITIC_SINGLES):
            if not low.endswith(suffix):
                continue
            residue = low[:-len(suffix)]
            if len(residue) < 2:
                continue
            cluster = IT_CLITIC_CLUSTERS.get(suffix)
            if cluster:
                # a cluster licenses even an imperative host, so tier A throughout;
                # absorption is tried first, since before a cluster the doubled
                # consonant belongs to the clitic (vattene -> va + te + ne, gold)
                if residue[-1] == cluster[0][0] and licensed(residue[:-1]):
                    residue, tier = residue[:-1], 'A'
                else:
                    tier = 'A' if licensed(residue) or residue in IT_GEMINATE_HOSTS else None
                clitics = list(cluster)
            else:
                if residue in IT_GEMINATE_HOSTS:
                    tier = 'A'
                elif suffix != 'gli' and residue in IT_MONOSYLLABIC_GEMINATING_IMP:
                    tier = None   # bare stem + single clitic (not gli): needs gemination, see IT_MONOSYLLABIC_GEMINATING_IMP
                else:
                    tier = licensed(residue)
                clitics = [suffix]
            if tier is None:
                continue
            if best is None or len(residue) > len(best[0]):
                best = (residue, clitics, tier)
        if best is None:
            return None
        residue, clitics, tier = best
        return ([token[:len(residue)]] + clitics, tier)   # keep the host's own capitalisation

    def split_italian_enclitics(self, s, mode):
        """
        Splits enclitics in an already tokenised string. Returns the new token
        string, the multiword-token groups (start, end, original form, tier) and a
        {token index: MISC} map recording what was done, so that both are
        recoverable when the CoNLL-U for the parser is written.

        Tier B is applied only when the fused form is not participle-shaped
        (girati/arrivati) or when no auxiliary precedes it in the utterance, which
        is what distinguishes 'adesso girati' from 'sono arrivati'. A Tier B
        candidate that fails the test is left fused and marked Enclitic=Cand, so
        the remaining recall loss can be counted instead of disappearing silently.
        """
        tokens = s.split(' ')
        out, groups, misc = [], [], {}
        for i, token in enumerate(tokens):
            analysis = self.analyse_enclitic(token) if token else None
            if analysis:
                parts, tier = analysis
                low = token.lower()
                # girati/andati: imperative+ti or participle plural. Only the second
                # takes an auxiliary, so a preceding one blocks the split.
                ambiguous_with_participle = re.search(r'[aiu]t[ie]$', low) is not None
                # capivi/soffiavi: imperative+vi or 2sg imperfect, which is far more
                # frequent. The 2pl imperative (sedetevi) keeps its -ate/-ete/-ite.
                ambiguous_with_imperfect = (parts[-1] == 'vi' and len(parts) == 2
                                            and re.search(r'[aei]vi$', low) is not None
                                            and not re.search(r'(at|et|it)e$', parts[0].lower()))
                split_it = tier == 'A' or (mode == 'AB' and not ambiguous_with_imperfect and (
                    not ambiguous_with_participle
                    or not any(t.lower() in IT_AUXILIARIES for t in tokens[:i])))
                if split_it:
                    start = len(out) + 1
                    groups.append((start, start + len(parts) - 1, token, tier))
                    misc[start] = 'Enclitic=' + tier
                    out.extend(parts)
                    continue
                misc[len(out) + 1] = 'Enclitic=Cand'
            out.append(token)
        return ' '.join(out), groups, misc

    def fix_italian_split_tags(self, tagged):
        """
        Repairs the tagger's output for the sub-tokens the splitter created: a
        truncated infinitive (prender, far) or a geminated imperative stem (dam,
        fam) is not a word, so TreeTagger returns <unknown> for it. The parser's
        own UPOS/lemma are unaffected; this only keeps the tagger columns usable
        (and with them --pos_output/--pos_utterance, which select on them).
        """
        inf, _ger, _imp = self.italian_hosts()
        stems = {'dam': 'dare', 'dac': 'dare', 'dim': 'dire', 'dic': 'dire',
                 'fam': 'fare', 'fac': 'fare', 'vac': 'andare', 'vat': 'andare',
                 'stac': 'stare', 'stat': 'stare'}
        lines = []
        for line in tagged.split('\n'):
            cols = line.split('\t')
            if len(cols) == 3 and (cols[2] == '<unknown>' or cols[2] == ''):
                form = cols[0].lower()
                if form in inf:
                    cols[1], cols[2] = 'VER:infi', inf[form]
                elif form in stems:
                    cols[1], cols[2] = 'VER:impe', stems[form]
                elif form == 'glie':
                    cols[1], cols[2] = 'PRO:pers', 'gli'
                line = '\t'.join(cols)
            lines.append(line)
        return '\n'.join(lines)

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
            # English UK Belfast
            s = re.sub(r" ?‡", r"", s)  # oh ‡ aren't they gorgeous !
            # „ is the mirror image of ‡: CHAT marks a satellite that FOLLOWS
            # (a tag question or vocative) - "she's a character „ isn't she ?".
            # Left in, the parser reads it as a token and attaches it as parataxis
            # or conj, which the validator rejects at level 3. 76003 in the UK data.
            s = re.sub(r" ?„", r"", s)
            # English UK Wells. The timed pauses in these utterances - '(5.)
            # &=laugh (5..) &=noise' - are removed by cleanUtt() for every
            # language now; only the event codes are handled here.
            s = re.sub(r" ?&=\w+", r"", s)
            s = re.sub(r'\s+', ' ', s).strip()
        return s

    def split_german_contractions(self, s, mwt, misc):
        """
        Splits German preposition+article contractions into their two syntactic
        words and records the multiword token, and separates an enclitic 's.

        'im Haus' -> '3-4 im' / 'in' / 'dem'; 'geht's' -> 'geht' + "'s". The
        contraction is a multiword token because the two words are written as one
        (UD German's only such class); the clitic is not, because UD German writes
        it as two plain tokens with SpaceAfter=No on the stem - which
        add_space_after() derives from '# text' on its own.

        Unlike Italian this needs no post-parse rule: the expansion is fixed, so
        nothing depends on the eventual analysis.

        Runs after split_italian_enclitics(), so any groups and MISC keys it
        returned are re-indexed for the tokens inserted here.
        """
        toks = s.split()
        out, shift, groups = [], {}, []
        for i, t in enumerate(toks, 1):
            shift[i] = len(out) + 1
            low = t.lower()
            if low in DE_CONTRACTIONS_VETOED:
                out.append(t)
                continue
            rep = DE_CONTRACTIONS.get(low)
            if rep:
                prep, art = rep
                if t[:1].isupper():
                    prep = prep.capitalize()
                groups.append((len(out) + 1, len(out) + 2, t, 'C'))
                out.extend([prep, art])
                continue
            m = DE_CLITIC_S.match(t)
            if m and m.group(1).lower() not in DE_CONTRACTIONS:
                out.extend([m.group(1), "'s"])       # geht's -> geht + 's
                continue
            out.append(t)
        if len(out) == len(toks):
            return s, mwt, misc
        mwt = [(shift[a], shift[b], f, tier) for (a, b, f, tier) in mwt] + groups
        misc = {shift[k]: v for k, v in misc.items()}
        return ' '.join(out), mwt, misc

    def _it_split_contractions(self, s, mwt, misc):
        """
        Splits Italian preposizioni articolate on the finished token list:
        'nella' -> 'in la', "sull'" -> "su l'", 'Al' -> 'A il'.

        The preposition carries Amalgama=<original form> in MISC, and the
        'amalgami' rules re-fuse ONLY marked pairs. Matching on the forms alone
        would be wrong: modern Italian writes 'con il/la' uncontracted (1147
        occurrences in this corpus against 508 'col'), so a form-based rule would
        silently rewrite genuine 'con la' as 'colla' - which is also the noun
        'glue'. Marking keeps the surface faithful and restores the capital for
        free. di-forms are not listed (ambiguous, must stay fused) and neither
        are the dare-homographs (IT_CONTRACTIONS_VETOED).

        Runs after split_italian_enclitics(), so the multiword-token groups and
        MISC keys it returned are re-indexed here for the tokens inserted.
        """
        toks = s.split()
        out, shift, marks = [], {}, {}
        for i, t in enumerate(toks, 1):
            shift[i] = len(out) + 1
            rep = IT_CONTRACTIONS.get(t.lower())
            if rep is None:
                out.append(t)
                continue
            prep, art = rep.split(' ', 1)
            if t[:1].isupper():
                prep = prep.capitalize()
            marks[len(out) + 1] = 'Amalgama=' + t
            out.extend([prep, art])
        if not marks:
            return s, mwt, misc
        mwt = [(shift[a], shift[b], f, tier) for (a, b, f, tier) in mwt]
        misc = {shift[k]: v for k, v in misc.items()}
        misc.update(marks)
        return ' '.join(out), mwt, misc

    def tokenise(self, s, split_contractions=False, return_mwt=False):
        """
        Tokenises a string, with language-specific rules.
        Normally, in CHAT format punctuation should be separated by spaces already. (BeginChar/EndChar)
        German clitics can't be handled: habs, gehts, etc.

        split_contractions: only set when the result is submitted to the parser with
        fixed tokens (fuse_contractions()). The unambiguous contractions are then
        pre-split - French au/aux into 'à le' / 'à les', Italian a/da/in/su/con
        forms into 'a il', 'in la' etc. (see IT_CONTRACTIONS). None of these has a
        partitive reading, so they are always preposition + article; leaving them
        fused loses the preposition and the parser reads the noun as a core
        argument ('il va au parc' -> parc/obj instead of obl:arg, 'è andata al
        mare' -> mare/nsubj). The ambiguous ones - French du/des, Italian di-forms
        - stay fused instead, because only the eventual deprel can decide them.
        Not applied for tagger input, where the token grid must stay aligned with
        TreeTagger's own tokenisation.

        return_mwt: also return the multiword-token groups and the MISC map produced
        by Italian enclitic splitting (see split_italian_enclitics()). Unlike the
        French contractions this applies on both paths, tagger and parser alike,
        because with a tagger the token grid it produces IS what the parser receives.
        """
        mwt, misc = [], {}
        if hasattr(self, 'language') and re.search(r'fra|french', self.language):
            if split_contractions:
                s = re.sub(r'\bAux\b', 'À les', s)
                s = re.sub(r'\baux\b', 'à les', s)
                s = re.sub(r'\bAu\b', 'À le', s)
                s = re.sub(r'\bau\b', 'à le', s)
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
            # Only reached when UDPipe does not tokenise (no --api_model). With a
            # parser the presegmented path is used instead, and its tokenizer -
            # trained on UD_English-CHILDES - writes the multiword tokens these
            # rules cannot: don't -> 2-3 don't / do / n't, wanna -> wan / na.
            # 'm was previously handled only for the literal "I'm"; it is just
            # another suffix.
            s = re.sub(r"n't\b", r" n't", s)                      # haven't -> have n't
            s = re.sub(r"(\S)'(s|ve|ll|d|re|m)\b", r"\1 '\2", s)   # it's -> it 's, I'm -> I 'm
        elif hasattr(self, 'language') and re.search(r'deu|german', self.language):
            # CHAT already spaces punctuation in these corpora, but not always
            s = re.sub(r'([,;?.!])(?=\s|$)', r' \1', s)
            s = re.sub(r'\s+', ' ', s)
        else:
            # Default simple tokenization if no language is matched
            s = re.sub(r'([,;?.!])(?=\s|$)', r' \1', s)
            s = re.sub(r'\s+', ' ', s)
        # after tokenisation proper, so that the splitter sees separated punctuation.
        # Outside the language branches above, so that --split_enclitics yes still
        # works on a corpus whose @Languages header does not identify it as Italian.
        mode = self.split_enclitics()
        if mode != 'none' and s.strip():
            s, mwt, misc = self.split_italian_enclitics(s.strip(), mode)
        # Contractions last, on the finished token list, so the marks it writes
        # are keyed by the final token indices (see _it_split_contractions).
        if split_contractions and s.strip() and re.search(
                r'ita|italian', getattr(self, 'language', '') or ''):
            s, mwt, misc = self._it_split_contractions(s, mwt, misc)
        # German: unconditional, so it applies on the tagger path too - both
        # tokens2conllu() and tagged2conllu() write the range lines from these
        # groups, and TreeTagger tags 'in'/'dem' better than it tags 'im'.
        if s.strip() and re.search(r'deu|german', getattr(self, 'language', '') or ''):
            s, mwt, misc = self.split_german_contractions(s, mwt, misc)
        return (s, mwt, misc) if return_mwt else s

    def tokens2conllu(self):
        """Creates a basic CoNLL-U file from tokens when TreeTagger is not used."""
        sys.stderr.write("Creating temporary CoNLL-U file from tokens for parsing...\n")
        
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', delete=False, suffix=".conllu.in") as temp_f:
            self.conllu_input_file = temp_f.name

        # Group words by utterance ID to reconstruct sentences, storing metadata safely
        utterances = {}
        for row in self.outRows:
            utt_id_base = re.match(r'(.*)_w\d+', row['utt_id']).group(1)
            if utt_id_base not in utterances:
                utterances[utt_id_base] = {
                    'tokens': [],
                    'speaker': row.get('speaker') or '_',
                    'age': row.get('age') or '_',
                    'child': row.get('child') or '_',
                    'project': row.get('project') or '_',
                    'text': row.get('utt_text') or '',
                    'chat': row.get('utterance') or ''
                }
            utterances[utt_id_base]['tokens'].append(row['word'])

        with open(self.conllu_input_file, 'w', encoding='utf8') as f:
            for utt_id, data in utterances.items():
                # sent_id is what the UD validator requires; item_id is kept
                # because dql.py, the CSV URL columns and the HTML anchors use it
                f.write(f"# sent_id = {utt_id}\n")
                f.write(f"# item_id = {utt_id}\n")
                f.write(f"# speaker = {data['speaker']}\n")
                f.write(f"# age = {data['age']}\n")
                f.write(f"# child = {data['child']}\n")
                f.write(f"# project = {data['project']}\n")
                # omitted rather than '_' when empty: both are reserved/parsed fields
                if data['text']:
                    f.write(f"# text = {data['text']}\n")
                if data['chat']:
                    f.write(f"# chat = {data['chat']}\n")
                # Italian enclitics: the sub-tokens are ours, so the multiword-token
                # line that groups them is ours to write too. UDPipe passes range lines
                # and MISC through unchanged with input=conllu (verified against the API).
                info = self.encliticInfo.get(utt_id, {})
                starts = {g[0]: g for g in info.get('groups', [])}
                misc = info.get('misc', {})
                for idx, token in enumerate(data['tokens'], 1):
                    if idx in starts:
                        start, end, form, _tier = starts[idx]
                        f.write(f"{start}-{end}\t{form}\t_\t_\t_\t_\t_\t_\t_\t_\n")
                    # Basic CoNLL-U: ID, FORM, and underscores for the rest
                    line = f"{idx}\t{token}\t_\t_\t_\t_\t_\t_\t_\t{misc.get(idx, '_')}\n"
                    f.write(line)
                f.write("\n")   # blank line: CoNLL-U sentence separator

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
        metadata (# sent_id, # item_id, # speaker, # age, # child, # project, # text, # chat),
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
                f"# sent_id = {uttID}",
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
        # --tag_ud_tokens (requires --parameters and --api_model together): parse first,
        # UD-tokenised, then tag those tokens afterward (run_tagger_on_ud_tokens()) for
        # an additional tagger pos/lemma - so tokenisation defers to UDPipe here too,
        # same as the plain --api_model-only case.
        use_tag_ud_tokens = self.args.tag_ud_tokens and self.args.parameters and self.args.api_model
        if self.args.parameters is not None and not use_tag_ud_tokens:
            self.tagger_input_file.write(f"<s_{uttID}> {self.tokenise(splitUtt)}\n")
            self.generate_rows_from_tagger(splitUtt, utt.strip(), speaker, uttID, timeCode)
        elif (self.args.api_model and not self.fuse_contractions()
              and self.split_enclitics() == 'none' and not self.split_german_here()):
            # No tagger, or --tag_ud_tokens: defer tokenisation to UDPipe's own
            # tokenizer (UD-compliant), instead of pre-splitting with tokenise()'s
            # tagger-oriented rules. The per-word outRows grid for this utterance is
            # built later, from the returned CoNLL-U, by restamp_presegmented_output().
            self.record_utterance_for_parsing(splitUtt, utt.strip(), speaker, uttID, timeCode)
        else:
            # Tokenise here: no parser at all, or fuse_contractions()/split_enclitics()
            # applies. Contractions are pre-split only when this feeds the parser:
            # du/des stay fused (ambiguous), au/aux are split (never partitive) - see
            # tokenise(). Italian enclitics are split on either path, because UDPipe's
            # own MWT splitter covers only about a third of them and its coverage is
            # correlated with construction type (infinitives yes, imperatives largely
            # not), which would bias the very distinction being counted.
            self.generate_rows_from_tagger(splitUtt, utt.strip(), speaker, uttID, timeCode,
                                           split_contractions=bool(self.args.api_model))

    def generate_rows_from_tagger(self, splitUtt, raw_utt, speaker, uttID, timeCode, split_contractions=False):
        clean_val = splitUtt if self.args.utt_clean else ''
        tokenised, mwt, misc = self.tokenise(splitUtt, split_contractions=split_contractions, return_mwt=True)
        words = tokenised.split(' ')
        if mwt or misc:
            # keyed by utterance, so tagged2conllu()/tokens2conllu() can restore the
            # multiword-token lines the split implies when they write the parser input
            self.encliticInfo[uttID] = {'groups': mwt, 'misc': misc}
        
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
        tagger's own tag. Falls back to the tagger's tag when --use_tagger_pos is
        given: 'tagger_pos' if present (--tag_ud_tokens combined mode), else 'pos'
        (plain --parameters mode, where 'pos' itself is the tagger's tag). Also
        falls back to 'pos' when no parser UPOS is available at all (no --api_model,
        or this row has none, e.g. untagged punctuation-only row).
        """
        if not self.args.use_tagger_pos:
            upos = row.get('conll_4')
            if upos and upos != '_':
                return upos
        else:
            tagger_pos = row.get('tagger_pos')
            if tagger_pos and tagger_pos != '_':
                return tagger_pos
        return row.get('pos', '')

    def finalize_output(self, *args, **kwargs):
        """Final processing: run tagger and/or parser, write output files"""
        if not self.outRows and not self.pendingUtterances:
            sys.stderr.write("\nNo data rows were generated. Exiting.\n")
            return

        itemPOS, itemLemmas, itemTagged = {}, {}, {}
        tagUdPOS, tagUdLemmas = {}, {}
        parsed_conllu_str = None

        # --tag_ud_tokens: parse first (UD tokenisation), tag those tokens afterward
        # for an additional pos/lemma. Requires both --parameters and --api_model;
        # silently has no effect otherwise (matches --utt_tagged/--use_tagger_pos style).
        use_tag_ud_tokens = self.args.tag_ud_tokens and self.args.parameters and self.args.api_model
        if self.args.tag_ud_tokens and not use_tag_ud_tokens:
            sys.stderr.write("  [INFO] --tag_ud_tokens has no effect without both --parameters and --api_model.\n")

        if self.args.parameters and not use_tag_ud_tokens:
            self.tagger_input_file.seek(0)
            taggerInput = self.tagger_input_file.read()
            if taggerInput:
                _, itemPOS, itemLemmas, itemTagged = self.run_treetagger(taggerInput)

        if self.args.api_model:
            # Two possible parser inputs; a file may need both, since fuse_contractions()
            # is evaluated per session and a concatenated file can mix languages.
            # Fixed-token input (input=conllu) covers: tagger-tokenised utterances, and
            # utterances we tokenised ourselves because contractions must stay fused.
            # Presegmented input covers utterances whose tokenisation was left to UDPipe.
            parsed_parts = []

            if self.args.parameters and not use_tag_ud_tokens:
                # Tagger active: run_treetagger() already built self.conllu_input_file
                # (tagged2conllu()), pre-tokenised by the tagger. UDPipe respects those
                # exact tokens (input=conllu, no tokenizer) and only re-tags/re-parses.
                if self.conllu_input_file and os.path.exists(self.conllu_input_file):
                    part = self.run_udpipe_api(self.conllu_input_file, self.args.api_model, chunk_size=self.args.chunk_parse)
                    if part: parsed_parts.append(part)
            else:
                if self.outRows:
                    # Tokenised here (fused contractions): submit those exact tokens,
                    # so the tokenizer cannot split e.g. French du/des and cost us the
                    # obj/obl:arg distinction. See fuse_contractions().
                    self.tokens2conllu()
                    if self.conllu_input_file and os.path.exists(self.conllu_input_file):
                        part = self.run_udpipe_api(self.conllu_input_file, self.args.api_model, chunk_size=self.args.chunk_parse)
                        if part: parsed_parts.append(part)

                if self.pendingUtterances:
                    # Tokenisation deferred: submit untokenised, CHAT-cleaned utterance
                    # text and let UDPipe's own tokenizer produce UD-compliant tokens.
                    ordered_ids = self.build_presegmented_input()
                    if ordered_ids:
                        raw_parsed = self.run_udpipe_api(self.presegmented_input_file, self.args.api_model, chunk_size=self.args.chunk_parse, presegmented=True)
                        if raw_parsed:
                            parsed_parts.append(self.restamp_presegmented_output(raw_parsed, ordered_ids))


            parsed_conllu_str = "".join(parsed_parts) if parsed_parts else None

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
                    # a rule may have changed the token count, which would shift
                    # every column joined on '<utt>_w<n>' from that point on
                    self.realign_rows_to_conllu(parsed_conllu_str)

                # SpaceAfter last, on the final tokens, and written back so the
                # file on disk carries it too
                parsed_conllu_str = self.add_space_after(parsed_conllu_str)
                parsed_conllu_str = self.ensure_udpipe_header(parsed_conllu_str)
                conllu_data = self._parse_conllu_output(parsed_conllu_str)
                with open(conllu_output_path, 'w', encoding='utf8') as f_conllu:
                    f_conllu.write(parsed_conllu_str)

            # After the rewrite and the re-gridding, so the tagger sees the final
            # tokenisation: a rule that splits a contraction turns 'della' into
            # 'di' + 'la', and the results are consumed by word index, so tagging
            # the pre-rewrite tokens would both mis-tag the group and shift every
            # tagger_pos/tagger_lemma after it.
            if use_tag_ud_tokens and self.outRows:
                tagUdPOS, tagUdLemmas = self.run_tagger_on_ud_tokens()

            # After the rewrite, so the trees show the corrected analysis and their
            # token numbering matches the final CoNLL-U (a rule that splits a
            # contraction inserts a node and shifts every id after it).
            if self.html_exporter:
                html_links = self.html_exporter.export(parsed_conllu_str, self.outRows)

        # Process rows and write initial FULL parsed CSV
        sys.stderr.write("Output tables:\n")
        sys.stderr.write("- Processing rows and writing initial parsed CSV...\n")
        parsed_csv_path = re.sub(r'\.cha(\.gz)?$', '', self.args.chat_file) + '.parsed.csv'
        light_csv_path = re.sub(r'\.cha(\.gz)?$', '', self.args.chat_file) + '.light.csv' # Define light path here

        header_parsed = ['utt_id', 'utt_nr', 'w_nr', 'URLwww', 'URLloc', 'speaker', 'child_project', 'language', 'child_other', 'age', 'age_days', 'time_code', 'word', 'lemma', 'pos', 'tagger_lemma', 'tagger_pos', 'utterance', 'utt_clean', 'utt_tagged']
        header_parsed.extend([f'conll_{i}' for i in range(1, 11)])
        header_light = ['utt_id', 'utt_nr', 'w_nr', 'URLwww', 'URLloc', 'speaker', 'child_project', 'language', 'child_other', 'age', 'age_days', 'word', 'lemma', 'pos', 'tagger_lemma', 'tagger_pos', 'utterance', 'utt_clean', 'utt_tagged'] # Define light header

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

            # --tag_ud_tokens: additional tagger pos/lemma alongside the parser's own
            # UPOS/lemma (added to 'tagger_pos'/'tagger_lemma', 'pos'/'lemma' stay UD-based)
            if use_tag_ud_tokens:
                try:
                    if tagUdPOS: row['tagger_pos'] = tagUdPOS.get(uID, ['_'] * wID)[wID - 1]
                    if tagUdLemmas: row['tagger_lemma'] = tagUdLemmas.get(uID, ['_'] * wID)[wID - 1]
                except IndexError:
                    row['tagger_pos'] = '_'
                    row['tagger_lemma'] = '_'

            if self.args.utt_tagged and itemTagged: row['utt_tagged'] = itemTagged.get(uID, '')

            # Add CoNLL-U data
            conll_row = conllu_data.get(row['utt_id'], [])
            for i, col_val in enumerate(conll_row): row[f'conll_{i+1}'] = col_val

            # Use CoNLL-U pos/lemma when tokenisation was UD-based: either no tagger
            # was used at all, or --tag_ud_tokens deferred tokenisation to the parser
            if (not self.args.parameters or use_tag_ud_tokens) and self.args.api_model and len(conll_row) > 3:
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

    def ensure_udpipe_header(self, conllu_str):
        """
        Puts a single UDPipe provenance block at the top of the file.

        The API echoes '# generator', '# udpipe_model' and '# udpipe_model_licence'
        on the first sentence of every response, but that is not something to rely
        on: restamp_presegmented_output() rebuilds each sentence from its tokens and
        drops them (verified), and with several chunks or several parser paths in
        one file they would otherwise appear repeatedly, in the middle of the file.

        Any copies the API supplied are removed and one block is written from the
        model we actually asked for, so the provenance is recorded exactly once and
        is correct whichever path produced the sentences.
        """
        drop = ('# generator =', '# udpipe_model =', '# udpipe_model_licence =')
        kept = [l for l in conllu_str.split('\n') if not l.startswith(drop)]
        header = ("# generator = UDPipe 2, https://lindat.mff.cuni.cz/services/udpipe\n"
                  f"# udpipe_model = {self.args.api_model}\n"
                  "# udpipe_model_licence = CC BY-NC-SA\n")
        return header + '\n'.join(kept).lstrip('\n')

    def add_space_after(self, conllu_str):
        """
        Sets SpaceAfter=No wherever '# text' has no space between two tokens.

        UD reconstructs the raw text from the tokens, so a token not followed by a
        space must say so. CHAT writes 'storia?', 'bimbo.', "l'hai" without spaces
        while the tokeniser separates them, and the validator rejects the file at
        level 2 (missing-spaceafter) - 11272 times over the Italian corpora, which
        is the whole of that gate's failures apart from 30 non-tree sentences.

        The surface unit is the multiword token where there is one (its range line
        carries the form and the space information), otherwise the word. Tokens are
        walked against '# text'; a sentence whose tokens do not reconstruct it is
        left untouched rather than guessed at. Measured over 103370 sentences of
        Italian output, all of them reconstruct.
        """
        out, changed, skipped = [], 0, 0
        for block in conllu_str.split('\n\n'):
            if not block.strip():
                continue
            lines = block.split('\n')
            text = None
            for l in lines:
                if l.startswith('# text ='):
                    text = l.split('=', 1)[1].strip()
            rows = [l.split('\t') for l in lines if l and not l.startswith('#')]
            rows = [r for r in rows if len(r) == 10]
            if text is None or not rows:
                out.append(block)
                continue

            # surface units: a range line, else a word not covered by one
            units, skip = [], 0
            for i, r in enumerate(rows):
                if '-' in r[0]:
                    lo, hi = (int(x) for x in r[0].split('-'))
                    units.append(i); skip = hi - lo + 1
                elif skip:
                    skip -= 1
                elif '.' not in r[0]:
                    units.append(i)

            pos, nospace, ok = 0, [], True
            for i in units:
                while pos < len(text) and text[pos] == ' ':
                    pos += 1
                form = rows[i][1]
                if not text.startswith(form, pos):
                    ok = False
                    break
                pos += len(form)
                if pos < len(text) and text[pos] != ' ':
                    nospace.append(i)
            if not ok or pos < len(text.rstrip()):
                skipped += 1
                out.append(block)
                continue

            for i in nospace:
                misc = rows[i][9]
                if 'SpaceAfter=' in misc:
                    continue
                rows[i][9] = 'SpaceAfter=No' if misc == '_' else misc + '|SpaceAfter=No'
                changed += 1

            body = ['\t'.join(r) for r in rows]
            head = [l for l in lines if l.startswith('#')]
            out.append('\n'.join(head + body))

        if changed:
            sys.stderr.write(f"- Marked {changed} token(s) SpaceAfter=No from '# text'.\n")
        if skipped:
            sys.stderr.write(f"  [WARNING] {skipped} sentence(s) whose tokens do not "
                             f"reconstruct '# text' were left without SpaceAfter.\n")
        return '\n\n'.join(out) + '\n\n'

    def realign_rows_to_conllu(self, conllu_str):
        """
        Re-grids self.outRows onto the token sequence of the final CoNLL-U.

        A rewrite rule may change the number of tokens: split_di / split_du turn
        one fused determiner into a preposition plus an article, inserting a node.
        outRows is built from childes.py's own tokenisation, before parsing, so
        from that point on every CoNLL-U id is one higher than the row that claims
        it. The columns are joined positionally on '<utt>_w<n>', so the shift is
        silent: the word column keeps the fused form while lemma/pos come from the
        following token. dql.py --merge has the same contract - it looks up
        '<sent_id>_w<node_id>' taken from the query result - so codings land on the
        wrong row too.

        Enclitics are unaffected because childes.py splits them itself, before
        parsing, so both sides already agree.

        Alignment walks the two sequences: equal forms map one to one, and where
        they differ the multiword-token range covering the CoNLL-U token carries
        the original fused form, which identifies the group that corresponds to a
        single old row. An utterance that does not align is left as it was, with a
        warning, rather than being silently regridded.
        """
        by_utt, order = {}, []
        for row in self.outRows:
            uid = re.match(r'(.*)_w\d+', row['utt_id']).group(1)
            if uid not in by_utt:
                by_utt[uid] = []
                order.append(uid)
            by_utt[uid].append(row)

        # CoNLL-U word tokens and multiword ranges, per utterance
        sents, cur, uid = {}, [], None
        for line in conllu_str.splitlines():
            if line.startswith('#'):
                if m := re.match(r'#\s*item_id\s*=\s*(.*)', line):
                    uid = m.group(1).strip()
                continue
            if not line.strip():
                if uid:
                    sents[uid] = cur
                cur, uid = [], None
            else:
                cur.append(line.split('\t'))
        if uid:
            sents[uid] = cur

        new_rows, regridded, failed = [], 0, 0
        for uid in order:
            old = by_utt[uid]
            toks = sents.get(uid)
            if not toks:
                new_rows.extend(old)
                continue
            words = [t for t in toks if '-' not in t[0] and '.' not in t[0]]
            mwt = {int(t[0].split('-')[0]): (int(t[0].split('-')[1]), t[1])
                   for t in toks if '-' in t[0]}

            mapped, i, j, ok = [], 0, 0, True
            while i < len(old) and j < len(words):
                wid = int(words[j][0])
                if old[i]['word'] == words[j][1]:
                    mapped.append((words[j], old[i])); i += 1; j += 1
                elif wid in mwt and mwt[wid][1] == old[i]['word']:
                    for k in range(wid, mwt[wid][0] + 1):   # the whole group
                        mapped.append((words[j], old[i])); j += 1
                    i += 1
                else:
                    ok = False; break
            if not (ok and i == len(old) and j == len(words)):
                failed += 1
                new_rows.extend(old)
                continue
            if len(mapped) != len(old):
                regridded += 1
            for tok, src in mapped:
                row = src.copy()
                row['word'] = tok[1]
                row['utt_id'] = f"{uid}_w{tok[0]}"
                row['w_nr'] = tok[0]
                new_rows.append(row)

        if regridded:
            sys.stderr.write(f"- Re-gridded {regridded} utterance(s) whose token count "
                             f"changed during rewriting.\n")
        if failed:
            sys.stderr.write(f"  [WARNING] {failed} utterance(s) could not be aligned with "
                             f"the CoNLL-U and were left unchanged.\n")
        self.outRows = new_rows

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

    def run_treetagger(self, tagger_input, build_conllu_input=True):
        """
        build_conllu_input=False skips the (redundant) step of also building a
        CoNLL-U-for-parsing from the tagger's output - used by
        run_tagger_on_ud_tokens() (--tag_ud_tokens), where parsing has already
        happened and this call is only for an additional tagger pos/lemma.
        """
        sys.stderr.write("Calling TreeTagger...\n")
        tagger_bin, param_file = './tree-tagger', self.args.parameters
        if not all(map(os.path.exists, [tagger_bin, param_file])): sys.exit(f"Tagger binary or param file not found. Checked: {tagger_bin}, {param_file}")
        self.tagged_temp_file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf8', delete=False, suffix=".txt")
        self.tagged_temp_file.write(re.sub(' +', '\n', tagger_input)); self.tagged_temp_file.flush()
        with open(self.tagged_temp_file.name, 'r') as f_in:
            tagged = subprocess.check_output([tagger_bin, param_file, '-token', '-lemma', '-sgml'], stdin=f_in).decode('utf8')
        tagged = process_tagged_data(tagged)
        if self.split_enclitics() != 'none':
            tagged = self.fix_italian_split_tags(tagged)
        if build_conllu_input and self.args.api_model:
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

    def run_tagger_on_ud_tokens(self):
        """
        --tag_ud_tokens: runs TreeTagger on the already UD-tokenised output
        (self.outRows, built by restamp_presegmented_output()) to obtain an
        ADDITIONAL tagger POS/lemma alongside the parser's own UPOS/lemma. Does not
        touch tokenisation/FORM, which stays UD-compliant; the results are merged
        into 'tagger_pos'/'tagger_lemma' by the caller, matched by utt_id, exactly
        like itemPOS/itemLemmas are for plain --parameters.
        """
        sys.stderr.write("Running TreeTagger on UD-tokenised output for additional pos/lemma...\n")
        utterances = {}
        for row in self.outRows:
            utt_id_base = re.match(r'(.*)_w\d+', row['utt_id']).group(1)
            utterances.setdefault(utt_id_base, []).append(row['word'])

        tagger_input = "\n".join(f"<s_{uid}> {' '.join(words)}" for uid, words in utterances.items()) + "\n"
        _, tagUdPOS, tagUdLemmas, _ = self.run_treetagger(tagger_input, build_conllu_input=False)
        return tagUdPOS, tagUdLemmas

    def tagged2conllu(self, str_in, conllu_out_path, meta_map=None):
        sys.stderr.write(f"Creating temporary CoNLL-U file with lemmas: '{conllu_out_path}'...\n")
        with open(conllu_out_path, 'w', encoding='utf8') as f:
            sentences = re.split(r'(<s_([^>]+)>)', str_in)
            for i in range(1, len(sentences), 3):
                sent_id = sentences[i+1]
                body = sentences[i+2].strip()

                meta = (meta_map or {}).get(sent_id, {})

                f.write(f"# sent_id = {sent_id}\n")
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
                # Italian enclitics: see tokens2conllu() for why the multiword-token
                # lines are written here rather than left to UDPipe's tokenizer.
                info = self.encliticInfo.get(sent_id, {})
                starts = {g[0]: g for g in info.get('groups', [])}
                enclitic_misc = info.get('misc', {})
                tokens = [line.split('\t') for line in body.split('\n') if line]
                for idx, token_parts in enumerate(tokens):
                    if len(token_parts) != 3: continue
                    word, tt_pos, tt_lemma = token_parts
                    # for robustness, replace empty or <unknown> lemmas/pos with '_'
                    if tt_lemma == '<unknown>' or tt_lemma == '': tt_lemma = '_'
                    if tt_pos == '': tt_pos = '_'
                    if idx + 1 in starts:
                        start, end, form, _tier = starts[idx + 1]
                        f.write(f"{start}-{end}\t{form}\t_\t_\t_\t_\t_\t_\t_\t_\n")
                    line = f"{idx+1}\t{word}\t{tt_lemma}\t_\t{tt_pos}\t_\t_\t_\t_\t{enclitic_misc.get(idx+1, '_')}\n"
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
    parser.add_argument('--chunk_html', type=int, default=1000, help='Number of utterances per HTML output file. Default: 1000.')
    parser.add_argument('--pos_output', default=".*", type=str, help='Regex to match POS tags. The reduced "light" table will only contain matching rows.\nMatches the parser\'s universal POS (UPOS) when --api_model is used; see --use_tagger_pos.')
    parser.add_argument('--pos_utterance', type=str, help='Regex to match POS tags. The full utterance text will only be printed on matching rows.\nMatches the parser\'s universal POS (UPOS) when --api_model is used; see --use_tagger_pos.\nDefaults to --pos_output\'s value when not given explicitly.')
    parser.add_argument('--use_tagger_pos', action='store_true', help='Make --pos_output/--pos_utterance match the tagger\'s own (language/model-specific) POS tag instead of the parser\'s universal POS (UPOS). Has no effect without --parameters; has no effect on rows the tagger did not tag if --api_model is not set (only source of POS in that case).')
    parser.add_argument('--tag_ud_tokens', action='store_true', help='Requires both --parameters and --api_model. Reverses the default order: parses first with UDPipe\'s own UD-compliant tokenizer, then runs the tagger on those tokens for an ADDITIONAL pos/lemma (columns tagger_pos/tagger_lemma) rather than tagger-tokenising before parsing. \'pos\'/\'lemma\' stay UD-based (parser UPOS/lemma), as in plain --api_model-only mode. No effect if only one of --parameters/--api_model is given.')
    parser.add_argument('--fuse_contractions', choices=['auto','yes','no'], default='auto', help="Keep preposition+determiner contractions (French du/des/au/aux) fused as one token by\n"
                        "tokenising in childes.py, instead of letting UDPipe's tokenizer split them.\n"
                        "Splitting them costs the obj/obl:arg distinction: in UD_French-GSD a split du/des has an\n"
                        "'obj' head noun in 1.2%% of cases vs 41%% unsplit, so the parser returns obl:arg instead of obj.\n"
                        "'auto' (default) applies this to French only; 'yes'/'no' force it for any language.\n"
                        "Only affects runs without --parameters (with a tagger, tokens are fixed by the tagger anyway).")
    parser.add_argument('--split_enclitics', choices=['auto','safe','yes','no'], default='auto', help=
                        "Split Italian verb+clitic forms into UD syntactic words (mettilo -> metti+lo,\n"
                        "glielo -> glie+lo) and write the multiword-token line for them.\n"
                        "Left fused, the clitic has no node and therefore no relation, so every clitic\n"
                        "query fails on enclisis; the verb's own lemma is lost as well (dammelo ->\n"
                        "'Dammelare'). The decision cannot be deferred to the parser as it is for French\n"
                        "du/des, because a fused enclitic form is out of vocabulary.\n"
                        "'auto' (default) applies tiers A and B to Italian only; 'safe' restricts this to\n"
                        "tier A (hosts the string alone identifies: ecco, dammelo, prenderlo), leaving the\n"
                        "ambiguous tier B (mettilo, girati) fused but marked Enclitic=Cand in MISC;\n"
                        "'yes' applies the Italian rules whatever the detected language (for corpora whose\n"
                        "@Languages header does not identify them), 'no' disables them.")
    parser.add_argument('--enclitic_stoplist', type=str, help='Path to a list of forms (one per line) that must never be split as Italian\nverb+clitic, however well they parse as one. See --split_enclitics.')
    parser.add_argument('--verb_lexicon', type=str, help='Path to a verb lexicon (TSV, lemma in the first column) extending the built-in\nlist used to license Italian enclitic splitting. See --split_enclitics.')
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