"""Author inspirations expressed as broad, editable craft traits."""
STYLE_PRESETS = [
    ('James Baldwin','author','Moral inquiry, historically grounded social criticism, intimate rhetorical address, and varied, lyrical sentence rhythms. Build arguments through tensions and precise observation.'),
    ('Virginia Woolf','author','Attention to perception, interiority, shifting perspective, temporal movement, and fluid sentence rhythms. Keep the scholarly argument legible.'),
    ('George Orwell','author','Plain language, concrete examples, direct syntax, scrutiny of euphemism, and lucid political analysis.'),
    ('Joan Didion','author','Restrained observation, precise details, controlled juxtaposition, reflective distance, and attention to contradictions in public narratives.'),
    ('Gore Vidal','author','Historically informed argument, skeptical examination of power, polished exposition, and occasional dry wit.'),
    ('Susan Sontag','author','Conceptual precision, interdisciplinary connections, close attention to cultural forms, and sustained interrogation of received categories.'),
    ('John McPhee — structured literary nonfiction','author','Use clear structural organization, patient exposition, concrete descriptive detail, and accessible explanation of specialist subjects. These are general literary-nonfiction traits, not an imitation of a living author’s distinctive voice.'),
    ('David Foster Wallace','author','Reflective self-questioning, attention to ordinary experience, varied sentence lengths, and purposeful analytical digressions. Keep qualifications readable and subordinate to the argument.'),
    ('Existentialist','approach','Explore freedom, responsibility, ambiguity, alienation, and lived experience through precise, concrete argument. Avoid unearned universal claims.'),
    ('Postmodernist','approach','Examine unstable categories, competing narratives, reflexivity, and the relation between language and power. Preserve clarity and evidence despite theoretical complexity.'),
    ('Gonzo journalism','approach','Use energetic, openly situated analysis, vivid concrete description, and a strong critical perspective. Never invent firsthand participation, scenes, dialogue, or reporting.'),
    ('Analytic and direct','approach','Use explicit distinctions, economical sentences, transparent inference, and measured claims supported by evidence.'),
    ('Literary nonfiction','approach','Combine evidence-led exposition with concrete detail, deliberate structure, and restrained narrative movement. Invent no scenes or quotations.'),
]

def catalog():
    return [{'name':name,'category':category,'guidance':guidance} for name,category,guidance in STYLE_PRESETS]
