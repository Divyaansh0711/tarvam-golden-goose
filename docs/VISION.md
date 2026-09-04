# Product Vision

What we're building. Kivi sits in an unusual position: it is the interface between a person and
every application on their machine. That gives it more visibility into someone's life than almost
any other product category, and it has so far used that visibility narrowly — to get pronunciation,
spelling, and tone right. As Hey Kivi becomes the primary surface and dictation becomes one feature
inside it, the temptation is to widen that visibility into a general memory of the user — what they
care about, how they feel, who matters to them. We're resisting that. Semantic memory for Kivi
should do for context exactly what phonetic memory already does for speech: reduce the need to
re-explain yourself, and nothing more.

Where the value is. The value isn't Hey Kivi feeling perceptive. It's Hey Kivi getting things right
the first time when it acts across apps — replying to the correct Rahul, continuing yesterday's PRD
instead of starting over, applying the sign-off you always use without being told again. That's a
narrower target than "personalization," and a much more testable one: did the action match what the
user meant, without a second correction. If semantic memory doesn't reduce corrections and
re-specifications during real work, it isn't earning its place regardless of how sophisticated it is
underneath.

What deserves to be remembered. Following the shape phonetic memory already set: entities and their
roles, established the same way a corrected name is established — the user states or confirms them,
not Kivi inferring them from scanning messages; standing instructions given in plain language, an
extension of Styles beyond tone into behavior ("always CC my manager on client emails"); and the
live state of work in progress, so "finish the PRD" or "keep editing this" carries forward within a
task's natural lifetime. Each of these has a clear origin: something the user said, on purpose, that
Kivi can point back to. Nothing enters memory by inference from the content Kivi happens to see
passing through dictation.

What Kivi must never assume. Kivi must never treat proximity to everything on someone's screen as
permission to remember everything. It must never infer emotional state, relationship quality,
opinions, or sensitive personal facts from what's dictated and carry them forward as if the user had
stated them. It must never let a persona or tone set for one app or context quietly apply in another
the user has kept separate — the same boundary Styles already respects for tone should hold for
every kind of memory Kivi adds. And it must never store the content of what passes through it as a
general-purpose life log; the failure mode to design against explicitly is Recall-style total
capture, which looked technically impressive and became the reason people stopped trusting the
product that shipped it.

Why someone keeps trusting it. Because the model is already proven: users correct Kivi once — a
name, a phrase, a tone — and the correction visibly sticks, in the very next sentence, without being
told what else was inferred from it. Semantic memory should extend that same loop to entities and
instructions: visible, per-context, and as easy to undo as fixing a mispronunciation. The moment Hey
Kivi surfaces something it "knows" that the user didn't consciously give it, or lets context leak
between the parts of their life they keep separate, it breaks the exact contract that made dictation
trustworthy in the first place — and trust, once broken there, doesn't come back just because the
feature works well otherwise.
