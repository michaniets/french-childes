# Changelog

Detailed rationale for each version's changes. `README.md` keeps only a short
summary per version; this file has the full reasoning, evidence, and examples
behind each design decision, for anyone who needs to know *why* something works
the way it does before changing it.

## Unreleased - Italian clitic rules made reachable

Two defects meant most of the `clitici` package still never applied, even after
the regex-escaping fix recorded under v5.9 below.

**The rules were structurally unreachable.** Grew matches *injectively*: two
distinct pattern identifiers can never bind the same node. All 12
deprel-reassigning rules identified the clitic's incoming edge as `e: X -> C`,
so `X` could never bind to `H` - which made every one of them inert precisely
when the parser attached the clitic to its own host. Measured over the 124 split
enclitic clitics of Roma: 47.6% were attached to the host (unreachable), 17.7%
were the sentence root, so had no governor node to bind at all (also
unreachable), and only 34.7% were in the one configuration the rules could see.
The symptom is silence - a rule that is plainly correct simply never fires. A
new `clitic_reattach` package now normalises every clitic of a split multiword
token onto its host first, after which the rules bind `e: H -> C` and reach
every case. It only touches wrong attachments: reattachment needs a governor
other than the host (injectivity again), or no host edge at all for the root
case, so a clitic already hanging off its host keeps its label untouched - which
is what preserves a reflexive `expl` the parser asserted.

**Empty MISC values destroyed the whole field.** `init_fix_misc` wrote `fix=`
with an empty value. When Grew reads such a file back, *every* feature on that
node is dropped, `Enclitic=` included, so all the rules silently stop matching.
It is harmless in memory within one pass, so a normal production run was
unaffected and the bug stayed invisible; it bit on any second pass over
already-rewritten output. Now `fix=none`. Note this changes the written value on
every VERB/AUX, so any `dql.py` query filtering that field needs updating; any
CoNLL-U produced before 2026-09-08 still carries the empty form.

**Three further defects, exposed only once the rules became reachable:**

- The `single_12_*` rules overwrote an `expl` the parser had already asserted,
  destroying the reflexive reading of pronominal verbs (*vuoi metterti seduto*:
  `ti` `expl` -> `obj`). They now leave an existing `expl` alone.
- `single_12_iobj_with_object` treated *any* `obj` as the competing object that
  settles the case syntactically, so a misparsed subject pronoun (*mettile tu
  là*, where `tu` is wrongly an object) forced the clitic to `iobj`. The
  competing object must now be a real NP (`NOUN`/`PROPN`), and
  `single_12_undecided` mirrors that guard exactly, so no clitic falls between
  the two rules and keeps the `dep` placeholder.
- `single_12_undecided` is a catch-all, but `Alt` gives no try-order, so it
  claimed cases the lexicon or the syntax could have decided and stamped them
  `todo=` - output showed `fix=single_12_dative_verb` and `todo=obj_or_iobj` on
  the same token. It now runs after the deciding rules have converged, and never
  overwrites a relation they assigned.

Measured on the 112 real enclitic sentences of Roma, with stale `fix=` markers
stripped so the MISC bug does not mask the result: clitics with a wrong analysis
go from 49 (raw parser output) to 7 (rules as they stood) to 0. Nine tokens
change relative to the previous rules - seven clear improvements, none worse. No
clitic is left with the `dep` placeholder and no empty MISC value is written,
both verified by a read-back pass.

Still not working, and not caused by any of the above:
`single_12_dative_verb`/`single_12_transitive_verb` fire correctly in controlled
tests but never once on real data, because the lexicon keys on the host's lemma
and the tagger supplies lemmas it does not contain (`metti` -> `metto`). Every
1st/2nd-person clitic therefore falls through to `single_12_undecided`. The
obj/iobj split over `mi`/`ti`/`ci`/`vi`/`le` should be treated as undecided
rather than measured until host lemmas are corrected.

## v5.9 - Italian enclitics

**Italian enclitics are split into UD syntactic words** (`--split_enclitics
{auto,safe,yes,no}`, default `auto`, Italian auto-detected via `self.language`).
UD treats a verb+clitic form as a multiword token with one syntactic word per
clitic - `sottoporgli` → `sottopor`+`gli`, `glielo` → `glie`+`lo` - and the
pipeline previously produced neither, because with a tagger (`-p`) the token grid
is the tagger's and UDPipe is called with `input=conllu`, so its own tokeniser is
never consulted.

- *The problem.* Left fused, the clitic has no node and therefore no relation, so
  every pattern in `childes-italian.query` (`V -[obj|iobj|expl]-> PRO`) silently
  fails on enclisis. The loss is not random: enclisis is licensed only by
  infinitive, gerund, imperative and `ecco`, so the missing observations are
  confounded with non-finiteness and directive force - the very variables an
  acquisition study is measuring. The fused form is also out of vocabulary for
  tagger and parser, so the verb's own lemma and mood are lost with it (`dammelo`
  → lemma `Dammelare`, `dagliela` → `dagliere`, checked against the UDPipe API).
  Across the 184 Italian CHILDES files in `~/ling/korpora/it/CHILDES` (388k
  tokens) the splitter finds about 4,100 enclitic tokens, roughly a quarter to a
  third of all clitic occurrences.
- *Why the French solution does not transfer.* For `du`/`des` the decision is
  deferred to the parser, because the fused form is frequent in training and its
  deprel is therefore informative. An Italian enclitic form is out of vocabulary
  instead, so the parser has nothing to contribute: with full sentential context
  `lascialo`, `aiutami`, `sedetevi`, `mettici` come back NOUN or ADJ, and `girati`
  is given `VerbForm=Part` in both _adesso girati verso di me_ and _le scarpe sono
  girati male_ - the one feature that would discriminate is the one it gets
  wrong. The decision must therefore be taken before parsing, and what is
  genuinely undecidable recorded rather than resolved.
- *Two tiers, in `childes.py`.* **Tier A** covers hosts the string alone
  identifies: `ecco`, the geminated irregular imperatives (`dammelo`, `fammi`,
  `dicci`), any host bearing a clitic cluster (`raccontaglielo`, `andiamocene`), a
  free-standing `glie-` cluster, and any infinitive or gerund host. These are
  always split. **Tier B** covers regular imperative hosts, which are homographic
  with participles (`girati`/`andati`), nouns (`portale`), and preposition+article
  (`dagli`); they are split only when a verb lexicon licenses the host and, for
  participle-shaped forms, no auxiliary precedes in the utterance. A Tier B
  candidate that fails the test stays fused and is marked `Enclitic=Cand` in
  MISC, so the remaining recall loss can be counted instead of disappearing;
  splits themselves are marked `Enclitic=A`/`Enclitic=B`. `--split_enclitics
  safe` keeps Tier A only, which on the corpus above splits 2,451 tokens and
  flags 1,801 candidates.
- *Choosing between analyses.* Among the competing segmentations of a token, the
  one with the **longest licensed host** wins. That is what separates
  `guardatelo` = `guardate`+`lo` from the shorter and wrong `guarda`+`te`+`lo`,
  and `fagli` = `fa`+`gli` from `fag`+`li`; it is also what correctly separates
  `fatelo` (`fate`+`lo`, regular 2pl imperative) from `fattelo`
  (`fa`+`te`+`lo`, monosyllabic imperative + cluster) purely from which literal
  spelling was typed. Before a cluster a doubled consonant belongs to the clitic
  (`vattene` → `va`+`te`+`ne`), before a single clitic it stays with the host
  (`dammi` → `dam`+`mi`); both conventions were read off UD_Italian-ISDT and
  -PoSTWITA rather than assumed, and the splitter reproduces 18 of 18 clitic
  segmentations attested there. This single/cluster asymmetry - `dammi` keeps the
  gemination, `vattene` doesn't - looked like an inconsistency worth "fixing" on
  first read, but it is gold-attested behaviour, not a bug: `vattene`/`Vattene`
  are the *only* cluster-gemination forms attested in any of 7 checked Italian
  treebanks, and both keep the host bare. Real Roma-corpus forms like `fattelo`,
  `dammelo`, `fammela` are not attested in any treebank either way, so there is no
  gold evidence to override `vattene` with - left as-is.
- *The 5 monosyllabic imperatives require a gemination exception of their own.*
  `da`/`di`/`fa`/`va`/`sta` (dare/dire/fare/andare/stare) always geminate the
  clitic's consonant before a *single* clitic (`dammi` not `dami`, `dicci` not
  `dici`), so the bare stem must never license a Tier B split against a plain
  single clitic - only the geminated form does. Without this exception, these
  bare stems (also common ordinary words: `di` = "of", `fa`/`va`/`sta` = 3sg
  indicative) mis-split real words as host+clitic: `dici` (di+ci; the real word
  is "you say"), `divi` (celebrities), `dati`/`davi` (data/you were giving),
  `vasi`/`vati`/`vane` (vases/bards/vain), `stavi` (you were - very common).
  Checked exhaustively (5 stems × 11 clitics = 55 forms) against the LibreOffice
  `it_IT` hunspell dictionary with affix expansion: 20 of the 50 non-`gli`
  combinations are real dictionary words. `gli` is exempted from the exception,
  since it never geminates (`dagli`/`digli` are the correct gold split, not
  `*daggli`) - `IT_MONOSYLLABIC_GEMINATING_IMP` in `childes.py`.
- *Lexicons (optional, `--verb_lexicon` and `--enclitic_stoplist`).*
  `italian-verbs.grewlex.tsv` holds 1,570 verb lemmas with the argument frames
  observed for them in ISDT and PoSTWITA (`Obj`, `Iobj`, `Refl`, `Freq`). The
  frames are recorded separately on purpose: a single valency label would be
  arbitrary for most Italian verbs, which freely combine frames (_dare qc a qn_,
  _darsi_, _darne_), so `yes` means attested, never exclusive. `italian-noclitic.txt`
  vetoes 5,326 forms that the treebanks annotate as simple tokens - without it a
  verb lexicon raises recall but also creates collisions, splitting `dici` as
  `di`+`ci` and `animali` as `anima`+`li` (470 tokens on this corpus). Without
  either file the built-in seed lexicon is used, at lower recall.
- *Stage 2, in `italian-isdt-ud.grs` (package `clitici`).* The parser handles the
  accusative reliably once the token is split, but not the dative or reflexive
  (`porta me lo` → `me`/`nsubj`, `va te ne` → `te`/`nsubj`, `fa mi vedere` →
  `mi`/`obj`), and it frequently attaches the clitic to the wrong head. The rules
  therefore reassign the relation from the gold distribution (`lo`/`la`/`li` 97%
  `obj`, `gli`/`glie` 94-100% `iobj`, `ne` 88% `iobj`, `si` 61% `expl`), use the
  fixed Italian cluster order - dative/reflexive before accusative - to resolve
  clusters without any lexicon, and fall back to the verb's attested frames only
  for a single `mi`/`ti`/`ci`/`vi`/`le`. What none of these decides is marked
  `todo=obj_or_iobj` rather than guessed, so it can be counted before any
  obj/iobj ratio over 1st/2nd person clitics is trusted.

### Regex escaping bug (found while extending the above)

Every clitic-identifying pattern in `clitici` used bare `(a|b|c)` alternation
inside `form=re"..."`. Grew's `re"..."` is OCaml `Str`-style (POSIX basic regex),
where `( ) |` are literal characters unless backslash-escaped - confirmed
empirically (0 matches with bare `(a|b|c)`, 1 match with `\(a\|b\|c\)`; Grew's
own documentation page's example, `re"(make|create)"`, also fails to match on
this backend). This meant `clitic_features`, `single_acc`, and every other rule
using this pattern had never fired, in production or otherwise. All 26
occurrences corrected. See `CLAUDE.md` for the general gotcha.

A correction to what was originally recorded here: this fix was reported as
"confirmed firing, 0 `fix=` occurrences before and 2301 after". That figure does
not show what it appeared to. `init_fix_misc` stamps an (empty) `fix=` on every
VERB/AUX and was added in the same session, so the count measured only that the
GRS was being loaded at all - the clitic rules themselves still fired zero times
in production. Escaping the regexes was necessary but not sufficient; see the
next section.

### `enclitic_host_repair` package (new)

The split boundaries `childes.py` produces are correct, but the parser
frequently mistags the host (`spegni` → DET, `dam` → NOUN) - a fused enclitic
form is out of vocabulary, and even split, short/rare hosts (the geminated Tier
A stems, uncommon regular imperatives) get too little training signal for ISDT
to tag correctly. This package forces `upos`/`xpos`/FEATS from the host's own
shape - the same information `childes.py` used to license the split in the first
place - rather than leaving the tagger's wrong guess, branching by shape (each
checked against gold data across 7 Italian treebanks before writing it):

- `ecco` → `ADV` (never `VERB`; 6/6 gold hits across the 7 treebanks are
  `ADV`/`INTJ`).
- ends in `r` → `VERB`, `VerbForm=Inf` (infinitive truncation: `far`/`dar`/
  `dir`/...).
- ends in `ando`/`endo` → `VERB`, `VerbForm=Ger` (full gerund, not truncated;
  199 `Ger` vs 27 `Conv` gold hits checked across treebanks - using `Ger` for
  consistency with ISDT/PoSTWITA, which the rest of this file follows).
- ends in `[aei]te` → `VERB`, `Mood=Imp|Tense=Pres|Person=2|Number=Plur` (2pl
  imperative).
- ends in `iamo` → `VERB`, `Mood=Imp|Tense=Pres|Person=1|Number=Plur` (1pl
  imperative).
- everything else → `VERB`, `Mood=Imp|Tense=Pres|Person=2|Number=Sing` (2sg;
  Tier B is only ever imperative by `childes.py`'s own construction, and the
  other Tier A shapes - `ecco`/infinitive/gerund - are excluded by the branches
  above).

Only touches hosts not already correctly tagged (`without {H[upos=VERB]}`, or
`upos=ADV` for `ecco`), so already-correct parser output is never overwritten;
stale features from the wrong tag (`Gender`, `PronType`, `Definite`, `Degree`)
are cleared, not just added to. Lemma is corrected only for the closed set of
geminated/monosyllabic Tier A hosts (5 source verbs, unambiguous from the host
string alone: `dam`/`dac`/`da`→`dare`, `dim`/`dic`/`di`→`dire`,
`fam`/`fac`/`fa`→`fare`, `vac`/`va`→`andare`, `stac`/`sta`→`stare`).
Open-vocabulary Tier B hosts (`spegni`, `metti`, `fate`, ...) keep whatever
lemma the tagger guessed - not recoverable here without a form→lemma
dictionary, which this pipeline does not have. Runs before `clitici` in the
`strat`, since `clitici`'s lexicon-based rules (`single_12_dative_verb`,
`single_12_transitive_verb`) match on the host's lemma.

### Cluster-rule false positives (found while testing the above)

The cluster rules (`cluster_first_dat` etc.) matched purely on linear adjacency
(`H < C1 < C2`), with nothing checking that C1/C2 are actually part of the same
enclitic split as H. `dammi la casetta`: `la` (`casetta`'s own article,
unrelated to `dammi`) was being reassigned as `dammi`'s second clitic, since
`mi` then `la` are adjacent and both clitic-shaped. Fixed by requiring
`textform="_"` on every clitic pattern (`C`/`C1`/`C2`): reliably true only for a
non-initial member of an actual multiword split - `childes.py`'s own clitic
sub-tokens - never true for an ordinary standalone word, confirmed via Grew's
own node representation. Verified the false positive is gone and genuine
two-clitic clusters (`dammelo`) still match correctly with the added
constraint.

## v5.8 - French contractions and tokenisation

**Tokenisation without a tagger.** When `--api_model` is used without
`-p/--parameters`, `childes.py` no longer pre-splits words with its own
(TreeTagger-oriented) rules before sending them to UDPipe. It sends cleaned,
untokenised utterance text and lets UDPipe tokenise it (`tokenizer=presegmented`),
so tokens follow the Universal Dependencies guidelines for that language,
including multiword tokens (e.g. English `gonna` → `gon`+`na`). Utterances that
clean down to nothing (pure event/pause coding, e.g. `(5.) &=laugh`) are dropped
before submission rather than sent as blank lines, which would otherwise
desynchronise every following utterance's metadata. This does not affect runs
that use TreeTagger (`-p`).

**French is an exception, handled in two stages, because UDPipe's own tokeniser
gets `du`/`des`/`au`/`aux` wrong in a way that changes the dependency analysis,
not just the surface form.**

- *The problem.* UDPipe splits `du`/`des` into `de`(ADP)+`le`/`les`(DET)
  unconditionally, regardless of syntactic role - even for direct objects and
  subjects. This matters because in UD_French-GSD the split representation and
  the `obj` relation are near-disjoint: a split `du`/`des` has an `obj` head noun
  in 81 of 6795 cases (1.2%), an unsplit one in 680 of 1675 (41%). Once the
  tokeniser has split, the parser has effectively no training evidence for `obj`
  and returns `obl:arg` instead - checked against `french-gsd`, `-sequoia`,
  `-partut` and `-spoken`, none of which analyses a partitive direct object
  (_Max mange du sucre_) as `obj`, and `-gsd` even mislabels subjects this way
  (_des enfants jouent_ → `obl:mod` instead of `nsubj`). `au`/`aux` fail in the
  mirror direction: left fused, the parser reads the following noun as a direct
  object instead of an oblique (_il va au parc_ → `parc`/`obj`), because it
  lacks the preposition it needs to see.
- *The fix has to happen twice, because deprel resolves the ambiguity but the
  surface form doesn't.* `du`/`des` are genuinely ambiguous between a
  partitive/indefinite determiner (single token, e.g. _Max mange du sucre_) and
  a preposition+determiner contraction (two syntactic words, e.g. _le goût du
  sucre_); which reading applies depends on the eventual analysis, which the
  tokeniser runs before. So **stage 1**, in `childes.py`
  (`--fuse_contractions {auto,yes,no}`, default `auto`, French auto-detected via
  `self.language`): submit `du`/`des` to the parser as a single fused token
  (whichever reading turns out to be correct, the parser now has the evidence it
  needs for the right deprel) and `au`/`aux` pre-split into `à le`/`à les`
  (never ambiguous, so no need to wait for the analysis). **Stage 2**, in
  `french-gsd-ud.grs` (package `amalgames`): once deprel is known, derive the
  UD-conformant surface form from it - `nmod`/`obl*` ⇒ expand `du`/`des` into a
  `de`+`le`/`les` multiword token; `obj`/`nsubj` ⇒ leave as a single DET
  (UD_French-GSD's own convention for the partitive/indefinite article);
  `au`/`aux` are fused back into a multiword token now that their deprel is
  correct. An intransitive verb (per `french-verbs.grewlex.tsv`) with a
  `du`/`des` "object" is first relabelled `obj`→`obl:arg`, since that's a de-PP
  rather than a true object, which then lets the `du`/`des` split rule apply.
  Rules log which one fired in `fix` (on the determiner or preposition they
  changed, since a contraction need not involve a verb).
- Other languages are unaffected: the criterion for stage 1 is that the
  tokeniser's decision be context-dependent _and_ entail a change of deprel,
  which does not hold for e.g. English `gonna` → `gon`+`na`.
  `--fuse_contractions yes`/`no` forces the behaviour for any language if
  needed. German contractions are the easy, context-independent case (Grünewald
  & Friedrich, [UDW 2020](https://universaldependencies.org/udw20/papers/2020.udw2020-1.11.pdf));
  Italian raises a different problem, handled by `--split_enclitics` (see v5.9
  above); Spanish is untested.
- A file mixing languages across `@PID` sessions is handled: whichever input
  builders have content are used, and the parsed results are combined.

**CoNLL-U header metadata.** Sentence headers now also carry `# child = <name>`
(unabbreviated) and `# project = <name>`, alongside the existing `# item_id`,
`# speaker`, `# age`, `# text`, `# chat`. `# text` is now guaranteed to reflect
the actual tokens (transcription noise such as timed pauses, intonation arrows,
and event codes like `&=laugh` is stripped from it, matching what is
tagged/parsed); `# chat` keeps the original CHAT-coded line unchanged.

**`--tag_ud_tokens`** (requires both `-p/--parameters` and `--api_model`):
reverses the default order of the two. Normally, when both are given, the
tagger tokenises first and the parser respects those exact tokens; `pos`/`lemma`
are the tagger's tag/lemma. With `--tag_ud_tokens`, the parser tokenises first
(UD-compliant, as above), and the tagger runs _afterward_ on those tokens purely
to add a **second**, independent tag/lemma in new `tagger_pos`/`tagger_lemma`
columns. `pos`/`lemma` then hold the parser's UPOS/lemma instead of the
tagger's. Off by default, so existing workflows are unaffected.

**CHAT-cleaning fixes:**

- `&=word` event/vocalisation codes (e.g. `&=laughs`, `&=noise`) are now fully
  removed instead of leaving a stray `&` plus a spurious real-looking word in
  the tagged/parsed output.
- Parenthesised omissions, e.g. `(be)cause` → `because`, now also match
  accented letters, apostrophes and hyphens, not just plain ASCII. `(d'ac)cord`
  previously left the parentheses in the parser input, tokenising as
  `(`/`d'`/`ac)cord` (a stray PUNCT and a bogus NOUN); it now cleans to
  `d'accord`.

**Bug fix:** a metadata-desync in `run_treetagger()`/`tagged2conllu()` (used
with `-p` together with `--api_model`) could attach one session's
`# speaker`/`# age`/`# text`/`# chat` to a different session's tokens whenever
utterance numbers repeated across `@PID` boundaries.

## v5.7 - POS-filter portability

`--pos_output`/`--pos_utterance` match the parser's universal POS (UPOS) by
default when `--api_model` is used, rather than the tagger's own
language/model-specific tag - so the same regex (e.g. `VERB`) works across
corpora and tagger models. `--use_tagger_pos` restores matching against the
tagger's tag. `--pos_utterance` defaults to `--pos_output`'s value when not
given explicitly.
