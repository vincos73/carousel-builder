# Sistemi visuali

Usare un sistema visivo stabile per l'intera sequenza. Il sistema decide composizione, trattamento delle superfici e ritmo; il profilo dell'utente decide font, palette, logo, firma e sito. Salvare la preferenza riutilizzabile in `brand.visual_signature.style_system`; il manifest può selezionare `visual_style_system` per il singolo carosello. Risolvere: manifest, profilo, `editorial-frame`. Non trattare i sistemi come template da riempire né generare la struttura card per card.

## Sistemi disponibili

| ID | Funzione | Regole distintive |
| --- | --- | --- |
| `editorial-frame` | Analisi, opinioni e tesi | **Editoriale**: cornice netta, ampio spazio tipografico e accento sobrio. |
| `editorial-halftone` | Creatività, cultura e contenuti espressivi | **Geometrico**: costellazione laterale di cinque corpi circolari a scale diverse, con posizione verticale alternata e superfici chiare e scure. L’ID storico resta invariato per compatibilità. |
| `corporate-modular` | Metodo, risultati, processi e dati | **Istituzionale**: indice modulare compatto, guida orizzontale sottile e gerarchia funzionale senza bande laterali o griglie estese. |

Usare `editorial-frame` quando il contenuto sviluppa un ragionamento, `editorial-halftone` quando il tono beneficia di colore, energia e personalità, `corporate-modular` per processi, confronti o dati. Nel sistema Geometrico confinare sempre i corpi alla fascia laterale, lasciare almeno il 70% della larghezza al testo e alternare la composizione in verticale tra slide consecutive. Mostrare le tre prove con lo stesso contenuto rappresentativo e la stessa identità, preselezionare il sistema risolto e consentire all'utente di confrontarle prima dell'approvazione. Nel fallback conversazionale descrivere le tre strutture senza fingere un rendering.

## Invarianti

- Costruire tutte le card con HTML/CSS/SVG deterministici; usare SVG per forme, pattern, linee e segni vettoriali, non per simulare un'immagine generativa.
- Riutilizzare per ogni sistema la stessa identità approvata: font display per copertina e titoli, font body per testi e metadati, secondo carattere opzionale, palette, logo, firma, sito e regole di contrasto. Il sistema non può sostituire i ruoli tipografici del profilo.
- Renderizzare il numero progressivo in alto a destra, dentro la safe area, su copertina, card interne e chiusura. Usare un formato coerente, per esempio `01 / 07`.
- Non usare il nome del sistema, il layout o altre etichette tecniche come testo visibile.
- Mantenere leggibilità, gerarchia e ordine di lettura anche quando il sistema cambia.
- Allineare i blocchi testuali a sinistra in tutti e tre i sistemi; la variazione nasce da superfici, struttura ed enfasi, non da testo centrato.
- Sulle card interne sfruttare una misura orizzontale ampia, indicativamente tra 20 e 22 caratteri alla scala dell'anteprima, preservando safe area, campiture e tagli geometrici. Prima di ridurre il corpo, ampliare la colonna per evitare che il testo si avvicini al bordo inferiore.
- Rendere ogni frase completa come un blocco distinto con uno spazio verticale coerente. Conservare l’eccezione per decimali, versioni, abbreviazioni, domini e URL.
- Applicare le enfasi `*_bold`, `*_serif` e `*_accent` indipendentemente dal sistema scelto, così il ritmo tipografico resta parte dell’identità condivisa.

## Varianti e crescita

Usare palette chiara/scura, intensità e copertura delle campiture, inclinazione dei tagli geometrici e layout di contenuto come varianti controllate del sistema. Non creare un nuovo preset per un semplice cambio di colore, font o atmosfera.

Aggiungere un nuovo sistema soltanto se copre un caso ricorrente che i tre sistemi non risolvono, è riconoscibile senza testi e colori, accetta l'identità dell'utente e funziona lungo un'intera sequenza senza dipendere da immagini generate. Registrarlo come nuovo ID e conservarne invarianti e varianti in questo documento.

## Copertina e capacità immagini

La struttura di ogni card, inclusa la copertina, resta deterministica. Un'immagine è un asset opzionale della sola copertina:

- `generative`: usarla solo se nella sessione esiste un generatore immagini;
- `provided`: usare un'immagine fornita dall'utente;
- `typographic`: costruire una copertina tipografica completa con il sistema scelto.

In assenza di generazione immagini, scegliere `provided` se è disponibile un asset adatto; altrimenti usare `typographic`. Non degradare le slide interne e non descrivere un segnaposto come immagine prodotta.
