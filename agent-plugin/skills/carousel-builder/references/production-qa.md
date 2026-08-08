# Capacità e controllo della produzione

## Preflight

Prima dell'onboarding determinare, senza installare nulla, se la sessione può:

- leggere integralmente la fonte;
- generare o recuperare il visuale di copertina;
- impaginare testo con controllo affidabile di font, misure e ritorni a capo;
- esportare PNG e PDF;
- rendere disponibili gli artefatti finali.

Classificare la capacità disponibile:

- `renderer`: un renderer verificato può produrre prova, PNG e PDF in modo ripetibile;
- `adapter`: strumenti disponibili possono produrre gli stessi artefatti rispettando manifest, profilo e controlli di questa skill;
- `layout`: non esiste un controllo tipografico affidabile; produrre il visuale di copertina quando disponibile e un layout dettagliato, senza presentarlo come rendering finale.

Comunicare in una frase il risultato previsto, per esempio:

> In questa sessione posso produrre le card PNG e il PDF finale.

Oppure:

> In questa sessione posso preparare testi e layout dettagliato, ma non renderizzare card con tipografia affidabile.

Non promettere formati che non possono essere prodotti. Non esporre nomi tecnici degli strumenti.

## Contratto di produzione ibrido

Qualunque modalità diversa da `layout` deve:

1. usare l'ultimo manifest approvato senza riscrivere silenziosamente i testi;
2. dichiarare prima della produzione quali artefatti può creare;
3. rispettare dimensioni, profilo, ordine delle slide, font e campi di enfasi;
4. produrre prima la prova visuale e soltanto dopo il batch completo;
5. restituire errori e output verificabili, senza sostituire asset o font in modo invisibile.

Se un renderer o adapter non soddisfa questi requisiti, usare `layout` come fallback dichiarato.

## Master, esportazione e scala tipografica

Progettare sempre sul master 4:5 da 1080×1350. Produrre l'export ad alta definizione a 1440×1800 scalando ogni misura per 4/3, senza reflow, ricomposizioni o cambi di densità. Le due dimensioni hanno lo stesso rapporto e non implicano una diversa grandezza fisica nel feed.

Usare il master per gli output 4:5. Quando un canale, placement organico o formato pubblicitario richiede un rapporto diverso, verificare le specifiche correnti e creare una variante separata. Conservare gerarchia e contenuti, proteggere la safe area e richiedere una nuova approvazione visuale. Non presentare il master 4:5 come compatibilità universale.

Usare sul canvas 1080×1350 questa scala nominale:

- copertina: 112 px, peso 800;
- titoli sezionali: 72 px, peso 800;
- testo principale e statement: 64 px, peso 620;
- etichette e metadati: 26 px;
- interlinea del corpo: 1.12;
- tracking del corpo: -0.025 em.

Adattare le dimensioni alle metriche reali del font mantenendo gerarchia e rapporti. Consentire una riduzione automatica massima dell'8%, quindi non scendere sotto il 92% della dimensione scelta. Se il contenuto continua a non entrare, restituire un errore di fit e richiedere una revisione del copy. Non ridurre ancora il carattere.

Un profilo può proporre una scala diversa soltanto con approvazione esplicita. Restano obbligatori la prova a 480 px e il limite di riduzione dell'8%.

## Controllo della prova visuale

Dopo l'approvazione dei testi creare una prova con:

1. copertina;
2. card con maggiore densità testuale;
3. chiusura, quando prevista.

Controllare obbligatoriamente la prova anche a 480×600, ottenuta dal master senza reflow, per simulare una visualizzazione desktop ridotta. Verificare inoltre la prova a risoluzione leggibile. Controllare gerarchia, densità, crop, famiglia e peso effettivi del font, ritorni a capo, contrasto e coerenza con il profilo. Mostrare la prova all'utente e attendere l'approvazione prima di produrre le altre card. Ripetere la prova per ogni variante con rapporto diverso dal master.

## Controllo testuale

Confrontare ogni card con l'ultima anteprima approvata e verificare:

- testo esatto, punteggiatura e accenti;
- assenza degli asterischi temporanei;
- ritorni a capo coerenti;
- nomi propri, numeri, cautele e attribuzioni;
- chiusura specifica della fonte corrente;
- corrispondenza esatta di titolo e dell'eventuale sottotitolo approvato in copertina;
- gerarchia subordinata del sottotitolo e Playfair Display sempre in corsivo, anche nelle enfasi serif;
- ritorno a capo dopo ogni punto di frase, senza spezzare decimali, versioni o abbreviazioni;
- in modalità `narrative`, titoli interni vuoti e assenza di etichette tecniche;

## Controllo visivo

Generare una contact sheet dell'intera sequenza quando possibile.

Per caroselli fino a 10 slide:

1. ispezionare tutte le card nella contact sheet;
2. ispezionare ogni card a dimensione leggibile;
3. controllare in particolare copertina, una card densa e chiusura alla risoluzione originale.

Per sequenze più lunghe, ispezionare comunque l'intera contact sheet e aprire alla risoluzione originale copertina, chiusura, card più densa e almeno una card ogni tre.

Verificare:

- testi tagliati, sovrapposti o troppo vicini ai bordi;
- contrasto tra testo e sfondo;
- logo corretto per il fondo oppure firma testuale prevista;
- numerazione progressiva delle pagine nell'angolo superiore destro di ogni card, inclusi copertina e chiusura, dentro la safe area e senza interferire con testo, logo o visuale;
- coerenza dell'alternanza cromatica;
- enfasi serif e accenti cromatici approvati;
- illustrazioni che non interferiscano con la lettura;
- dimensioni e rapporto d'aspetto richiesti;
- sfondo esteso esattamente da `x=0`, `y=0` fino a 1080×1350, senza strisce o margini introdotti dal renderer;
- assenza di SVG, filtri o elementi nascosti che occupino spazio nel flusso del documento;
- in modalità `narrative`, slide interne pulite e prive di visuali decorativi non approvati;
- coerenza della tecnica visiva tra tutte le card che contengono immagini.

## Accessibilità

Verificare inoltre:

- contrasto di almeno 4.5:1 per testo normale e 3:1 per testo grande;
- leggibilità del testo alla dimensione effettiva del feed, non soltanto alla risoluzione originale;
- leggibilità di titoli, corpo, etichette e metadati nella prova a 480 px di larghezza;
- assenza di significati affidati esclusivamente a colore, serif, corsivo o posizione;
- ordine di lettura coerente tra copertina, contenuti e chiusura;
- presenza nel manifest di alt text per ogni slide oppure di una trascrizione completa e ordinata del carosello;
- descrizione del visuale quando aggiunge informazione non presente nei testi.

Se una palette identificativa non supera il contrasto minimo, segnalarlo e chiedere una scelta. Non alterarla silenziosamente.

Correggere e renderizzare di nuovo gli artefatti interessati. Ripetere il controllo dopo ogni correzione.

## Controllo degli artefatti

Prima della consegna verificare:

- validità del JSON e corrispondenza con il numero di slide previsto;
- numero, ordine, nomi, dimensioni e apertura effettiva dei PNG;
- numero, ordine, formato uniforme e apertura delle pagine PDF;
- corrispondenza proporzionale tra master 1080×1350 ed export 1440×1800;
- caricamento dei font previsti e assenza di fallback inattesi;
- corrispondenza tra font richiesto, font approvato e famiglia effettivamente renderizzata;
- corrispondenza tra testi approvati, manifest e artefatti;
- assenza di file incompleti o duplicati presentati come finali.

Se un controllo fallisce, conservare gli output validi, mantenere lo stato precedente e offrire ripetizione o fallback. Non avanzare a `consegnato`.

## Consegna

Indicare numero di slide, dimensioni, formati e modalità usata: `renderer`, `adapter` o `layout`. Consegnare PNG, PDF, JSON o layout soltanto se effettivamente prodotti e verificati. Includere alt text o trascrizione quando previsti dal manifest.

Non creare ZIP, brand pack o copie aggiuntive senza richiesta esplicita.
