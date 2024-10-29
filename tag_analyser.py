# tag_analyser.py

__author__ = "Achim Stein"
__version__ = "1.0"
__email__ = "achim.stein@ling.uni-stuttgart.de"
__status__ = "25.10.24"
__license__ = "GPL"

'''
- input: string consisting of annotated tokens:  word_tag=lemma word_tag=lemma etc.
- annotation was added by TreeTagger using the PERCEO parameters for spoken French.
- matches regexes against this string, sets annotation values on match
- returns a dictionary of these annotation values
'''

import re

class TagAnalyser:
    def __init__(self):
        self.annot_keys = ['annot_refl', 'annot_dat', 'annot_clit', 'annot_mod', 'annot_particle']
        self.annotations = {key: None for key in self.annot_keys}

    def analyse(self, tagged, lemma):
        # Clears annotations dictionary
        for key in self.annot_keys:
            self.annotations[key] = None  
        # --- Annotate reflexives
        reRefl = re.compile(' [^_]+_.*?=se [^_]+_VER.*?=(?P<lemma>\w+)')
        if re.search(reRefl, tagged):
            m = re.search(reRefl, tagged)
            matchedLemma = m.group('lemma')
            if lemma == matchedLemma:
                self.annotations['annot_refl'] = 'refl'
        # --- Annotate dative complements
        reDat = re.compile('[^_]+_VER.*?=(?P<lemma>\w+) (à|au|aux)_[^ ]+')
        if re.search(reDat, tagged):
            m = re.search(reDat, tagged)
            matchedLemma = m.group('lemma')
            if lemma == matchedLemma:
                self.annotations['annot_dat'] = 'aPP'
        # --- Annotate object clitics
        reDatCl = re.compile(rf'(lui|leur)_PRO:clo[^ ]+ [^_]+_(VER|AUX).*?=(?P<lemma>{lemma})')
        reAccCl = re.compile(rf'(le|la|les)_PRO:clo[^ ]+ [^_]+_(VER|AUX).*?=(?P<lemma>{lemma})')
        reAccDatCl = re.compile(rf'(le|la|les)_PRO:clo[^ ]+ (lui|leur)_PRO:clo[^ ]+ [^_]+_(VER|AUX).*?=(?P<lemma>{lemma})')
        if re.search(reDatCl, tagged):
            self.annotations['annot_clit'] = 'dat'
        if re.search(reAccCl, tagged):
            self.annotations['annot_clit'] = 'acc'
        if re.search(reAccDatCl, tagged):
            self.annotations['annot_clit'] = 'accdat'
        # --- Annotate modal verbs (verb+bare infinitives)
        reOnlyModals = re.compile('(devoir|falloir|pouvoir|savoir|vouloir)')
        reModCl = re.compile(rf'[^ _]+_.*?=(?P<lemma>{lemma})( [^_]+_ADV=\S+)*( [^_]+_PRO:clo=\S+).*? [^_]+_VER:infi=(?P<verb>\S+)')
        reModVerb = re.compile(rf'[^ _]+_.*?=(?P<lemma>{lemma})( [^_]+_ADV=\S+)* [^_]+_(VER|AUX):infi=(?P<verb>\S+)')
        reModCompl = re.compile(rf'[^ _]+_.*?=(?P<lemma>{lemma})( [^_]+_ADV=\S+)* [^_]+_(KON|PRO:int)')
        reModObj = re.compile(rf'[^ _]+_[^=]+=(?P<lemma>{lemma}) [^_]+_(DET:.*?|PRO:rel|PRO:dem)=')
        reClMod = re.compile(rf'([^ _]+_PRO:clo=\S+) [^_]+_.*?=(?P<lemma>{lemma})( pas_ADV=pas)?.*? [^_]+_VER:infi=(?P<verb>\S+)')
        if re.search(reOnlyModals, lemma):
            prefix = "modal"  
        else:
            prefix = "verb"
        if re.search(reModCl, tagged):  
            self.annotations['annot_mod'] = prefix + '-clit-verb'
        elif re.search(reClMod, tagged):
            self.annotations['annot_mod'] = 'clit-' + prefix
        elif re.search(reModObj, tagged):
            self.annotations['annot_mod'] = prefix + '-obj'
        elif re.search(reModVerb, tagged):
            self.annotations['annot_mod'] = prefix + '-verb'
        elif re.search(reModCompl, tagged):
            self.annotations['annot_mod'] = prefix + '-clause'
        else:
            self.annotations['annot_mod'] = prefix + '-noRule'
        # --- Annotate verb particles
        reParticle = re.compile('(dessus|dessous|dehors|avant|derrière|en-.*)')
        reVPart = re.compile(rf'[^ _]+_VER:.*?=(?P<lemma>{lemma}) (?P<part>{reParticle.pattern}_ADV=\S+)')
        if re.search(reVPart, tagged):
            self.annotations['annot_particle'] = 'verb-part_' + re.search(reVPart, tagged).group('part')
        
        return self.annotations