"""Sentence-scope reading for the phrase cue guard.

The lexical layer in :mod:`app.semantic_guard` matches a fixed cue inventory.
It read scope from the text *before* a matched cue, which is correct for an
adjacent ``not`` and wrong for every operator whose scope is a clause:

* an operator that sits *after* the cue ("… was unavailable, probably");
* an operator in the *antecedent* clause ("If the ward was busy, the checklist
  was unavailable"), where the same marker abstains when the cue sits on the
  other side of the comma;
* a clause whose subject is a pronoun ("…, and others say it was available"),
  where no cue can match at all because every cue phrase names its subject.

This module supplies the missing unit — the clause, with its own subject phrase
— and three readings over it: pronoun resolution, conditional scope by clause,
and sentence-initial operator span. It does not touch the cue inventory: a cue
is still a fixed string, and this layer only *derives* an occurrence of that
string in a clause whose subject was elided to a pronoun.

A condition has two spellings. The marked one is ``if``/``unless``/``provided
that``; the unmarked one is the subjunctive inversion, where the auxiliary comes
first and the subject behind it — "Had the ward been busy, …", "Were the
checklist unavailable, …", "Should the binder be missing, …". Both open a
condition, so this layer reads them at every placement it reads ``if``, and the
inversion reaches clauses coordinated after it for the same reason. What it
cannot see is a condition it has no marker for: an inversion inside a quotation
sits mid-clause behind the quotation's frame, so it opens nothing and is not
seen; an inversion inside a reported clause *is* read, as a condition, because
reporting does not change what the marker proposes; and a bare participle with
no auxiliary in front of it ("the checklist been unavailable") names no marker
at all.

Three rules are deliberately absent because the existing pins forbid them:

* a subject quantifier over a reporting verb ("No one confirmed that the
  checklist was unavailable") keeps certifying — pinned by
  ``tests/test_semantic_guard_negation_corpus.py`` (``CU-MATRIX-CONFIRM``);
* a mid-clause temporal ``when`` does not scope its clause over a later one,
  because ``when`` presupposes its clause as fact;
* a negated predicate under a pronoun ("…, and others say it was not
  available") is not read as the opposite cue: this guard abstains, it never
  flips a direction.
"""
import re
from dataclasses import dataclass

# --- clause boundaries ------------------------------------------------------

#: A hard terminator ends the sentence, so scope does not cross it. A comma and
#: a semicolon end a *clause* but not the sentence: an operator opened at the
#: start of a sentence can still reach across them (see ``hedge_scope_at``).
_SENTENCE_TERMINATORS = frozenset(".!?\n")
_SEPARATOR = re.compile(r"[.!?\n,;]")

#: Broader than ``semantic_guard._REPORTING_VERB`` on purpose: that list decides
#: whether a quantifier scopes over a cue, this one only finds where a reported
#: clause starts so ``others say it …`` has a subject "it". The base forms are
#: included because the segmentation needs them ("others say", "they claim").
_REPORTING_VERB = re.compile(
    r"\b(?:say|says|said|saying|claim|claims|claimed|report|reports|reported|"
    r"mention|mentions|mentioned|note|notes|noted|state|states|stated|"
    r"argue|argues|argued|suggest|suggests|suggested|deny|denies|denied|"
    r"tell|tells|told|write|writes|wrote|confirm|confirms|confirmed)\b",
    re.IGNORECASE,
)
_COMPLEMENTISER = re.compile(r"^\s+(?:(?:that|whether)\s+)?", re.IGNORECASE)

#: A conditional marker that *opens* a clause. ``when`` is excluded on purpose:
#: the lexical layer reads it as a conditional opening the cue's own clause, but
#: it is a temporal presupposition, so a ``when`` clause asserts its content and
#: does not propose a following clause.
_CONDITIONAL_OPENING = re.compile(
    r"^\s*(?:even\s+)?(?:if|unless|provided\s+that)\b", re.IGNORECASE)
#: The same markers anywhere, for a conditional placed *after* the cue
#: ("… was unavailable if the ward was busy").
_CONDITIONAL_MARKER = re.compile(
    r"\b(?:if|unless|provided\s+that)\b", re.IGNORECASE)
#: An inverted subjunctive conditional puts the auxiliary *first* and the
#: subject second, with no ``if`` to key on: "Had the ward been busy, …", "Were
#: the checklist unavailable, …", "Should the binder be missing, …". The same
#: three words are ordinary verbs in "The team had enough time" and "We were
#: short staffed", so position — not vocabulary — is what separates the two.
_INVERSION_OPENING = re.compile(r"^\s*(?P<aux>had|were|should)\b", re.IGNORECASE)
#: The same inversion after a boundary, for the postposed form ("… was
#: unavailable had the ward been busy").
_INVERSION_AFTER = re.compile(
    r"(?:^\s*|[,;]\s*|\b(?:and|but|or|so|then|yet|nor)\s+)"
    r"(?P<aux>had|were|should)\b",
    re.IGNORECASE,
)
#: Words that cannot open a predicate. When the word after the auxiliary and its
#: subject is one of these, the clause is not read as an inversion: "Were the
#: checklist and the binder …" has a coordinated subject, not a predicate.
_INVERSION_NON_PREDICATE = frozenset({
    "and", "or", "but", "of", "in", "on", "at", "to", "for", "with", "from",
    "by", "as", "than", "that", "which", "who", "whom", "whose", "when",
    "where", "while", "because", "if", "unless", "so", "then",
})
#: A contrastive opening sets the clause against what precedes it, so an
#: operator before it does not reach through.
_CONTRAST_OPENING = re.compile(
    r"^\s*(?:but|however|yet|although|though|whereas)\b", re.IGNORECASE)
#: A coordinator or subordinator gives the conjunct its own scope, which is what
#: keeps "Perhaps the ward was busy, and the checklist was unavailable"
#: certifying while the semicolon variant abstains.
_SYNDETIC_OPENING = re.compile(
    r"^\s*(?:and|but|or|so|yet|however|although|though|because|while|whereas|"
    r"then|therefore|thus|which|also|even|nor)\b",
    re.IGNORECASE,
)
_CONNECTIVE_PREFIX = re.compile(
    r"^(?:and|but|so|yet|then|or|also|thus|therefore|however|still|instead|"
    r"meanwhile)\b[\s,]*",
    re.IGNORECASE,
)
#: Sentence-initial epistemic adverbs. Same vocabulary as
#: ``semantic_guard._HEDGE_FRAME``; only the sentence-initial position matters
#: here, because the cue's own clause is already read by the lexical layer.
_HEDGE_LEAD = re.compile(
    r"^\s*(?:perhaps|possibly|probably|maybe|presumably|apparently|conceivably)\b"
    r"|^\s*it\s+(?:seems|appears)\b"
    r"|^\s*(?:it\s+is|it\s+was)\s+(?:possible|likely|probable)\b",
    re.IGNORECASE,
)

# --- subjects ---------------------------------------------------------------

#: Nouns whose plural carries no trailing ``s``. Without this set the antecedent
#: search treats "staff" as singular, so ``"…, and staff say it was available"``
#: resolved ``it`` to *staff* and never reached the checklist, while the same
#: sentence with "others" resolved correctly — one construction, two verdicts,
#: decided by a spelling. The set is closed on purpose: only words whose plural
#: cannot be detected from their shape.
_INVARIANT_PLURALS = frozenset({"staff", "people", "others", "police", "children"})

_SINGULAR_PRONOUNS = frozenset(
    {"it", "its", "this", "that", "he", "she", "him", "her", "one"})
_PLURAL_PRONOUNS = frozenset({"they", "them", "their", "these", "those"})
_PRONOUNS = _SINGULAR_PRONOUNS | _PLURAL_PRONOUNS
#: "There was no checklist" has no referent, so it is not an antecedent.
_NON_REFERENTIAL = frozenset({"there", "here"})
_DETERMINERS = frozenset(
    {"the", "a", "an", "this", "that", "these", "those", "its", "their", "his",
     "her", "my", "our", "your", "some", "any", "no", "every", "each", "all",
     "both", "another", "other"})
_AUXILIARIES = frozenset(
    "am is are was were be been being do does did have has had can could will "
    "would shall should may might must".split())
_BARE_VERBS = frozenset(
    "not never ran run went got gets keeps kept took made said says".split())


def _tokens(text):
    return [token for token in re.split(r"\s+", text.strip()) if token]


def _clean(token):
    return token.lower().strip(".,;:!?\"'()")


def _is_verbish(token):
    word = _clean(token)
    if not word:
        return False
    if word in _AUXILIARIES or word in _BARE_VERBS:
        return True
    return len(word) > 3 and word.endswith("ed")


def _is_pronoun(phrase):
    return _clean(phrase) in _PRONOUNS


def _number(token):
    word = _clean(token)
    if word in _SINGULAR_PRONOUNS:
        return "singular"
    if word in _PLURAL_PRONOUNS or word in _INVARIANT_PLURALS:
        return "plural"
    if word.endswith("s") and not word.endswith("ss"):
        return "plural"
    return "singular"


def _normalise(text):
    return re.sub(r"\s+", " ", text).strip(" ,.;:!?\"'()")


def _same_referent(antecedent, subject_part):
    """Does the resolved antecedent name the cue's own subject?

    The antecedent has to carry *exactly* the cue's subject words, minus its
    determiner: "the checklist" names the subject of "checklist was available",
    and "the printed checklist" names the subject of "printed checklist was
    unavailable" but not of the shorter cue. Comparing heads alone would let a
    modified cue be attributed through the bare noun.
    """
    antecedent_words = [_clean(word) for word in _tokens(antecedent)]
    bare = [word for word in antecedent_words if word not in _DETERMINERS]
    phrase_words = [_clean(word) for word in _tokens(subject_part)]
    return (bare or antecedent_words) == phrase_words


#: Sentence-initial adverbs whose morphology does not mark them as adverbs, plus
#: the common ``-ly`` ones. Used only to find the subject, never to decide a
#: stance: a hedge is read by the guard's own inventory.
_SENTENCE_ADVERBS = frozenset({
    "however", "moreover", "furthermore", "therefore", "thus", "meanwhile",
    "overall", "indeed", "notably", "interestingly", "reportedly",
    "apparently", "accordingly", "consequently", "nevertheless",
})


def _subject_span(text, start, end):
    """The leading subject phrase of ``text[start:end]``, with its offsets.

    Returns ``(phrase, phrase_start, phrase_end, number)`` or ``None``. The
    reading is deliberately shallow — a determiner-led noun phrase, a pronoun,
    or a bare first noun — because the only decision that depends on it is
    whether a clause's subject *is* a pronoun to be resolved.
    """
    window = text[start:end]
    connective = _CONNECTIVE_PREFIX.match(window)
    offset = start + (connective.end() if connective is not None else 0)
    while offset < end and text[offset] in " \t":
        offset += 1
    # A sentence-initial adverb is an operator, not a subject. Left in place it
    # takes the subject slot — "Notably the checklist was unavailable" got the
    # subject "Notably" — and the pronoun chain then finds no referent for the
    # cue, so an opposing clause is silently dropped again. Only skip when a
    # subject follows; a one-word clause keeps its word.
    while True:
        probe = _tokens(text[offset:end])
        if len(probe) < 2:
            break
        head = _clean(probe[0])
        if head not in _SENTENCE_ADVERBS and not head.endswith("ly"):
            break
        offset += len(probe[0])
        while offset < end and text[offset] in " \t":
            offset += 1
    window = text[offset:end]
    words = _tokens(window)
    if not words:
        return None
    first = _clean(words[0])
    if first in _NON_REFERENTIAL:
        return None
    if first in _PRONOUNS:
        return (words[0], offset, offset + len(words[0]), _number(words[0]))
    if first in _DETERMINERS:
        taken = [words[0]]
        for word in words[1:4]:
            if _is_verbish(word):
                break
            taken.append(word)
            if len(taken) >= 3:
                break
        if len(taken) < 2:
            return None
        phrase = " ".join(taken)
        return (phrase, offset, offset + len(phrase), _number(taken[-1]))
    if _is_verbish(words[0]):
        return None
    return (words[0], offset, offset + len(words[0]), _number(words[0]))


# --- subjunctive inversion --------------------------------------------------


def _inversion_opens(window):
    """Does ``window`` open with a subjunctive inversion?

    The shape read is auxiliary + subject + predicate: ``had``/``were``/``should``,
    then a pronoun, a determiner-led noun phrase, or a bare noun, then at least
    one word that can open a predicate. That is the whole test, and it is a
    *positional* one: the same three words are ordinary verbs once a subject
    precedes them, which is why "The team had enough time" and "We were short
    staffed" never qualify — their auxiliary is not the clause's first word.

    Two details the shape has to admit:

    * the complement need not be a past participle. The inverted subjunctive
      also takes a predicative adjective — "Were the checklist unavailable" — so
      the check is that a predicate *can* follow, not that a participle does;
    * a coordinated subject runs through one coordinator ("Were the checklist
      and the binder both missing"), because a determiner after the conjunction
      belongs to the second conjunct, not to the predicate.

    Deliberately shallow, in the same way as ``_subject_span``: the subject is
    read at most two words deep, so an inversion over a long noun phrase is not
    seen.
    """
    head = _INVERSION_OPENING.match(window)
    if head is None:
        return False
    words = _tokens(window[head.end():])
    if len(words) < 2:
        return False
    first = _clean(words[0])
    if first in _DETERMINERS:
        index = 1
        while index < len(words):
            word = _clean(words[index])
            if index == 1 or word in _DETERMINERS or word in ("and", "or"):
                index += 1
                continue
            return word not in _INVERSION_NON_PREDICATE
        return False
    if first in _PRONOUNS:
        return _clean(words[1]) not in _INVERSION_NON_PREDICATE
    if first in _NON_REFERENTIAL or first in _INVERSION_NON_PREDICATE:
        return False
    return _clean(words[1]) not in _INVERSION_NON_PREDICATE


# --- cue phrase shape -------------------------------------------------------


def split_cue(phrase):
    """Split a fixed cue phrase into its subject part and its predicate.

    ``"printed checklist was unavailable"`` -> ``("printed checklist",
    "was unavailable")``. Returns ``None`` when the phrase has no predicate
    boundary the reader can trust (``"not enough time"``), in which case no
    derived occurrence is produced and the lexical reading stands alone.
    """
    words = _tokens(phrase)
    for index, word in enumerate(words):
        if index == 0:
            continue
        if _is_verbish(word):
            return (" ".join(words[:index]), " ".join(words[index:]))
    return None


# --- clause spans -----------------------------------------------------------


@dataclass
class ClauseSpan:
    """One clause of a sentence, with the subject phrase it opens with."""

    text: str
    start: int
    end: int
    sentence_index: int
    reported: bool = False
    subject: str | None = None
    subject_start: int | None = None
    subject_end: int | None = None
    number: str | None = None
    antecedent: str | None = None


@dataclass(frozen=True)
class DerivedMatch:
    """A cue phrase occurrence whose subject was elided to a pronoun.

    ``attributed`` is ``False`` when the clause's predicate matches the cue's
    but the pronoun has no antecedent in the sentence: the clause is then
    withheld rather than dropped, because a dropped clause is what let the
    opposing reading disappear.
    """

    start: int
    end: int
    clause: ClauseSpan
    attributed: bool


def _segments(text):
    """Trimmed ``(start, end, sentence_index)`` spans between separators."""
    out = []
    sentence_index = 0
    cursor = 0
    for match in _SEPARATOR.finditer(text):
        out.append((cursor, match.start(), sentence_index))
        if match.group() in _SENTENCE_TERMINATORS:
            sentence_index += 1
        cursor = match.end()
    out.append((cursor, len(text), sentence_index))
    trimmed = []
    for start, end, index in out:
        while start < end and text[start] in " \t":
            start += 1
        while end > start and text[end - 1] in " \t":
            end -= 1
        if end > start:
            trimmed.append((start, end, index))
    return trimmed


def _report_split(text, start, end):
    """Split a segment at a reporting verb into matrix and reported clause."""
    window = text[start:end]
    match = _REPORTING_VERB.search(window)
    if match is None:
        return [(start, end, False)]
    verb_end = start + match.end()
    rest = text[verb_end:end]
    filler = _COMPLEMENTISER.match(rest)
    complement_start = verb_end + (filler.end() if filler is not None else 0)
    if complement_start >= end:
        return [(start, end, False)]
    if _subject_span(text, complement_start, end) is None:
        return [(start, end, False)]
    if complement_start - verb_end < 1:
        return [(start, end, False)]
    return [(start, verb_end, False), (complement_start, end, True)]


def _build_clauses(text):
    clauses = []
    for start, end, sentence_index in _segments(text):
        for clause_start, clause_end, reported in _report_split(text, start, end):
            span = _subject_span(text, clause_start, clause_end)
            clause = ClauseSpan(
                text=text[clause_start:clause_end],
                start=clause_start,
                end=clause_end,
                sentence_index=sentence_index,
                reported=reported,
            )
            if span is not None:
                clause.subject, clause.subject_start, clause.subject_end, clause.number = span
            clauses.append(clause)
    return clauses


def _resolve_antecedents(clauses):
    """Fill ``antecedent`` on pronoun clauses, nearest matching subject first.

    Resolution stays inside the sentence and matches number. A pronoun whose
    antecedent is itself a pronoun chains through it, so ``others say it`` and
    ``they said it`` reach the same referent; an unresolved pronoun leaves
    ``antecedent`` as ``None``.
    """
    referents = []
    for clause in clauses:
        if clause.subject is None or clause.subject_end is None:
            continue
        if _is_pronoun(clause.subject):
            for prior in reversed(referents):
                if prior[0] != clause.sentence_index:
                    break
                if prior[2] == clause.number:
                    clause.antecedent = prior[1]
                    referents.append((clause.sentence_index, prior[1], clause.number))
                    break
        else:
            referents.append((clause.sentence_index, clause.subject, clause.number))


class SentenceScope:
    """The clause structure of one quote, and the scope reads over it."""

    def __init__(self, text, clauses):
        self.text = text
        self.clauses = tuple(clauses)

    # -- structure -----------------------------------------------------------

    def clause_at(self, offset):
        for clause in self.clauses:
            if clause.start <= offset < clause.end:
                return clause
        for clause in self.clauses:
            if clause.start >= offset:
                return clause
        return self.clauses[-1]

    def _index_of(self, clause):
        for index, candidate in enumerate(self.clauses):
            if candidate is clause:
                return index
        return 0

    def _sentence_prefix(self, clause):
        index = self._index_of(clause)
        return [prior for prior in self.clauses[:index]
                if prior.sentence_index == clause.sentence_index]

    # -- conditional scope ---------------------------------------------------

    def _clause_asks(self, clause):
        """Is this clause terminated by a question mark?

        Inverted word order is also a question's word order: "Should the
        checklist be reviewed before the audit?" has an inversion's shape and
        proposes nothing — it asks. The terminator sits outside the clause span,
        so it is read from the source text, and only spaces and tabs are allowed
        between them (a newline would already be a sentence boundary).
        """
        return self.text[clause.end:].lstrip(" \t").startswith("?")

    def _opens_condition(self, clause):
        """Does this clause *open* a condition — by marker word or by inversion?

        The two are one reading with two spellings: ``if``/``unless``/``provided
        that``, or ``had``/``were``/``should`` with the subject behind it. The
        inversion is refused when the clause is interrogative.
        """
        if _CONDITIONAL_OPENING.match(clause.text):
            return True
        if not _inversion_opens(clause.text):
            return False
        return not self._clause_asks(clause)

    def conditional_scope_at(self, offset, cue_end=None):
        """Is the clause at ``offset`` a conditional's consequent, not asserted?

        Three placements, one reading: the marker opens the cue's own clause
        ("If the cue, …"), the marker follows the cue in its clause ("the cue if
        …"), or the marker opens a preceding clause of the same span ("If …,
        the cue"). The span stops at a contrastive opening, so a "but" clause is
        read as asserted.

        An inverted subjunctive is read at every one of those placements, and
        reaches coordinated clauses after it exactly as ``if`` does, because the
        inversion *is* the marker and only its position differs:

        * "Had the ward been busy, the checklist was unavailable" — the marker
          opens a preceding clause;
        * "Were the checklist unavailable" — the marker opens the cue's own
          clause;
        * "… was unavailable had the ward been busy" — the marker follows the
          cue, alone in its clause.

        Two limits. The layer has no quotation awareness: an inversion inside a
        quote — ``the note said "had the ward been busy, …"`` — sits in the
        middle of the frame's clause instead of opening one, so it is not seen
        and the quoted consequent is left certifying. And the shape requires a
        subject, so an elliptical inversion with none in the text is not seen
        either. Negation inside the predicate ("Had it not been for the binder")
        does not block the read: it is the marker's position that matters.
        """
        clause = self.clause_at(offset)
        if self._opens_condition(clause):
            return True
        if cue_end is not None:
            tail = self.text[cue_end:clause.end]
            if _CONDITIONAL_MARKER.search(tail):
                return True
            if not self._clause_asks(clause):
                for found in _INVERSION_AFTER.finditer(tail):
                    if _inversion_opens(tail[found.start("aux"):]):
                        return True
        if _CONTRAST_OPENING.match(clause.text):
            return False
        for prior in reversed(self._sentence_prefix(clause)):
            if _CONTRAST_OPENING.match(prior.text):
                return False
            if self._opens_condition(prior):
                return True
        return False

    # -- sentence-initial operator span --------------------------------------

    def hedge_scope_at(self, offset):
        """Does a sentence-initial hedge span forward over this clause?

        The operator is read at the start of the sentence's first clause and
        reaches the cue's clause only across *asyndetic* joins — a semicolon or
        a bare comma. A coordinator gives the conjunct its own scope, which is
        what keeps the pinned "Perhaps the ward was busy, and the checklist was
        unavailable" certifying.
        """
        clause = self.clause_at(offset)
        index = self._index_of(clause)
        first = self.clauses[0]
        if first.sentence_index != clause.sentence_index or first is clause:
            return False
        if _HEDGE_LEAD.match(first.text) is None:
            return False
        for intervening in self.clauses[1:index + 1]:
            if intervening.sentence_index != clause.sentence_index:
                return False
            if _SYNDETIC_OPENING.match(intervening.text):
                return False
        return True

    # -- pronominal cue occurrences -----------------------------------------

    def _names_cue_subject(self, clause, subject_part):
        """Can this clause's pronoun refer to the cue's subject?

        Nearest-subject resolution is a proxy, and it fails the way an
        NER-free coreference step always does: an intervening animate subject
        ("…, and the auditor said it was available") takes the pronoun slot even
        when the pronoun is the cue's subject. The only decision that depends on
        this is whether the clause is an occurrence of *this* cue, so the test
        is stated directly — is there a referent in the sentence that names the
        cue's subject with matching number?

        Preferring attachment is the fail-safe direction: a derived occurrence
        either adds an opposing cue, which makes the guard abstain
        (``AMBIGUOUS_CUE_RELATIONS``), or agrees with the lexical match, which
        changes nothing. Missing one commits a direction the sentence
        contradicts.
        """
        if clause.antecedent is not None and _same_referent(clause.antecedent,
                                                          subject_part):
            return True
        # Pronoun resolution crosses a sentence terminator on purpose, while
        # operator scope does not: "The checklist was unavailable. The auditor
        # said it was available." is one quotation asserting both directions,
        # and reading only the second sentence commits SUPPORTS. Attaching the
        # pronoun here can only add an opposing cue, which abstains.
        for prior in reversed(self.clauses[:self._index_of(clause)]):
            if prior.subject is None or _is_pronoun(prior.subject):
                continue
            if prior.number == clause.number and _same_referent(prior.subject,
                                                              subject_part):
                return True
        return False

    def derived_matches(self, phrase):
        """Occurrences of ``phrase`` whose subject was elided to a pronoun.

        A clause with a pronoun subject has a predicate but no named subject, so
        no fixed cue phrase can match it. When the predicate is the cue's
        predicate and the resolved antecedent is the cue's subject, the clause
        is an occurrence of that cue and carries its own scope.
        """
        split = split_cue(phrase)
        if split is None:
            return ()
        subject_part, remainder = split
        remainder = _normalise(remainder)
        if not remainder:
            return ()
        matches = []
        for clause in self.clauses:
            if clause.subject is None or clause.subject_end is None:
                continue
            if not _is_pronoun(clause.subject):
                continue
            predicate = _normalise(self.text[clause.subject_end:clause.end])
            if not predicate.startswith(remainder):
                continue
            if self._names_cue_subject(clause, subject_part):
                attribution = True
            else:
                # No referent in the sentence can be the cue's subject, so this
                # clause is not an occurrence of this cue at all.
                continue
            matches.append(DerivedMatch(
                start=clause.subject_start,
                end=clause.end,
                clause=clause,
                attributed=attribution,
            ))
        return tuple(matches)


def build_scope(text: str) -> SentenceScope:
    """Read the clause structure of ``text`` once, for all cues in it."""
    clauses = _build_clauses(text)
    _resolve_antecedents(clauses)
    return SentenceScope(text, clauses)
