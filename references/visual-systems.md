# Sistemi visuali

Usare un sistema visivo stabile per l'intera sequenza. Il sistema decide composizione, trattamento delle superfici e ritmo; il profilo dell'utente decide font, palette, logo, firma e sito. Salvare la preferenza riutilizzabile in `brand.visual_signature.style_system`; il manifest può selezionare `visual_style_system` per il singolo carosello. Risolvere: manifest, profilo, `editorial-frame`. Non trattare i sistemi come template da riempire né generare la struttura card per card.

## Sistemi disponibili

| ID | Funzione | Regole distintive |
| --- | --- | --- |
| `editorial-frame` | Analisi, opinioni e tesi | **Editoriale**: cornice netta, ampio spazio tipografico e accento sobrio. |
| `editorial-halftone` | Creatività, cultura e contenuti espressivi | **Geometrico**: costellazione laterale di cinque corpi circolari a scale diverse, con posizione verticale alternata e superfici chiare e scure. L’ID storico resta invariato per compatibilità. |
| `corporate-modular` | Metodo, risultati, processi e dati | **Istituzionale**: indice modulare compatto, guida orizzontale sottile e gerarchia funzionale senza bande laterali o griglie estese. |

Usare `editorial-frame` quando il contenuto sviluppa un ragionamento, `corporate-modular` per studi, dati, risultati, processi e confronti, `editorial-halftone` quando un contenuto creativo o culturale beneficia davvero di colore, energia e personalità. Nel sistema Geometrico confinare sempre i corpi alla fascia laterale, lasciare almeno il 70% della larghezza al testo e alternare la composizione in verticale tra slide consecutive.

Il percorso normale espone e valida un solo sistema consigliato. Se l'utente chiede un confronto o la classificazione resta incerta, mostrare una sola alternativa standard sullo stesso contenuto e con la stessa identità. Rendere Geometrico disponibile come opzione avanzata, non come terza prova obbligatoria. Conservare comunque tutti e tre i renderer e i relativi test di regressione: la semplificazione riguarda la scelta per il singolo carosello, non la compatibilità del prodotto. Nel fallback conversazionale descrivere soltanto il sistema consigliato e, se richiesto, l'alternativa, senza fingere un rendering.

## Firma strutturale obbligatoria

Il valore `visual_style_system` è un contratto di composizione, non un'etichetta. Ogni sistema deve lasciare sulle card interne e sulla chiusura un segno riconoscibile anche senza leggere il nome del tema. La copertina è un template distinto e non riceve questi elementi strutturali:

- `editorial-frame`: una cornice rettangolare perimetrale completa, continua e visibile sui quattro lati delle card interne e della chiusura, collocata dentro la safe area con spessore e distanza dal bordo coerenti. Non sostituirla con una sola linea superiore, una sottolineatura del logo o un bordo parziale. Non applicarla alla copertina.
- `editorial-halftone`: la costellazione laterale di cinque corpi circolari a scale diverse deve essere visibile sulle card interne e sulla chiusura, confinata alla fascia laterale e alternata verticalmente tra slide consecutive. Non applicarla alla copertina. Una singola forma, una texture generica o il solo colore d'accento non identificano il sistema.
- `corporate-modular`: l'indice modulare compatto e la guida orizzontale sottile devono comparire sulle card interne e sulla chiusura con posizione, proporzioni e ritmo coerenti. Non applicarli alla copertina. Una semplice griglia o una linea isolata non è sufficiente.

La prova composta da copertina, card più densa e chiusura è accettabile soltanto se la copertina è libera dagli elementi strutturali e card interna e chiusura mostrano la firma obbligatoria, anche nell'anteprima a 480 px. Il batch finale deve usare la stessa geometria approvata. Se un renderer o adapter non rispetta entrambe le condizioni, non è compatibile con il sistema selezionato: cambiare produttore oppure usare il fallback `layout`, senza presentare una composizione generica come rendering finale.

## Invarianti

- Costruire tutte le card con HTML/CSS/SVG deterministici; usare SVG per forme, pattern, linee e segni vettoriali, non per simulare un'immagine generativa.
- Riutilizzare per ogni sistema la stessa identità approvata: font display per copertina e titoli, font body per testi e metadati, ruolo corsivo opzionale, palette, logo, firma, sito e regole di contrasto. Il sistema non può sostituire i ruoli tipografici del profilo.
- Renderizzare il numero progressivo in alto a destra, dentro la safe area, su copertina, card interne e chiusura. Usare un formato coerente, per esempio `01 / 07`.
- Non usare il nome del sistema, il layout o altre etichette tecniche come testo visibile.
- Mantenere leggibilità, gerarchia e ordine di lettura anche quando il sistema cambia.
- Allineare i blocchi testuali a sinistra in ogni sistema; la variazione nasce da superfici, struttura ed enfasi, non da testo centrato.
- Sulle card interne sfruttare una misura orizzontale ampia, indicativamente tra 20 e 22 caratteri alla scala dell'anteprima, preservando safe area, campiture e tagli geometrici. Prima di ridurre il corpo, ampliare la colonna per evitare che il testo si avvicini al bordo inferiore.
- Rendere ogni frase completa come un blocco distinto. Usare `body_line_height` soltanto fra le righe avvolte della stessa frase e aggiungere `sentence_gap_em: 0.6` fra frasi consecutive. Conservare l’eccezione per decimali, versioni, abbreviazioni, domini e URL.
- Applicare le enfasi `*_bold`, `*_italic` e `*_accent` indipendentemente dal sistema scelto, così il ritmo tipografico resta parte dell’identità condivisa. Accettare `*_serif` soltanto come alias legacy.

## Varianti e crescita

Usare palette chiara/scura, intensità e copertura delle campiture, inclinazione dei tagli geometrici e layout di contenuto come varianti controllate del sistema. Non creare un nuovo preset per un semplice cambio di colore, font o atmosfera.

Aggiungere un nuovo sistema soltanto se copre un caso ricorrente che i tre sistemi non risolvono, è riconoscibile senza testi e colori, accetta l'identità dell'utente e funziona lungo un'intera sequenza senza dipendere da immagini generate. Registrarlo come nuovo ID e conservarne invarianti e varianti in questo documento.

## Copertina e capacità immagini

La struttura di ogni card, inclusa la copertina, resta deterministica. Un'immagine è un asset opzionale della sola copertina e la sua intenzione può essere scelta nella prima revisione senza generarla subito:

- `generated`: usarla solo se nella sessione esiste un generatore immagini;
- `provided`: usare un'immagine fornita dall'utente;
- `typographic`: costruire una copertina tipografica completa usando gerarchia, palette, font, logo e firma approvati, senza cornice, costellazione o indice modulare.

Usare `typographic` come default quando l'utente non esprime una preferenza. Se sceglie `generated` o `provided`, produrre o collegare l'asset dopo l'approvazione dei testi. La copertina usa allora una griglia split deterministica: area testuale a sinistra e immagine verticale nella colonna destra di circa il 45%, senza testo sovrapposto, trasparenza o gradiente compensativo. In assenza di generazione immagini, scegliere `provided` se è disponibile un asset adatto; altrimenti tornare esplicitamente a `typographic`. Non degradare le slide interne e non descrivere un segnaposto come immagine prodotta.
