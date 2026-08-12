# Capacità e controllo della produzione

## Preflight

Prima dell'onboarding determinare, senza installare nulla, se la sessione può:

- leggere integralmente la fonte;
- generare, ricevere o sostituire con una composizione tipografica il visuale di copertina;
- impaginare testo con controllo affidabile di font, misure e ritorni a capo;
- esportare PNG e PDF;
- rendere disponibili gli artefatti finali.

Risolvere le capacità nell'ordine seguente, prima di generare la copertina o promettere gli output:

1. interrogare l'ambiente per runtime, librerie e percorsi bundled o già configurati;
2. provare per primo il runtime dichiarato dall'ambiente e soltanto dopo gli interpreti generici presenti nel sistema;
3. verificare gli import necessari e, quando utile, un rendering minimo in memoria o in una cartella temporanea;
4. considerare il fallimento di un singolo candidato un dettaglio interno se un altro runtime disponibile supera la verifica;
5. informare l'utente soltanto quando il limite cambia davvero gli artefatti producibili, richiede un'autorizzazione oppure nessun runtime disponibile consente il rendering.

Non annunciare un fallback `layout` mentre resta da verificare un runtime configurato dalla sessione. Se il secondo tentativo riesce senza cambiare il risultato promesso, proseguire senza interrompere il flusso con un avviso tecnico.

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
4. dichiarare in `production.supported_style_systems` i sistemi visivi realmente implementati e includere quello selezionato nel manifest;
5. produrre prima la prova visuale e soltanto dopo il batch completo, usando strutture HTML/CSS/SVG deterministiche e trattando l'immagine come asset opzionale di copertina;
6. restituire errori e output verificabili, senza sostituire asset, font o firma strutturale in modo invisibile.

Nel percorso `local-editor`, anteprima approvata e produzione devono usare lo stesso albero `.slide-preview`, gli stessi asset e lo stesso foglio di stile. La modalità di produzione può nascondere soltanto i controlli dell'editor e riposizionare la sequenza per la cattura; non può ridefinire copy, tipografia, safe area o geometria del sistema visivo. Prima di creare il PDF, richiedere `proof.approved: true`, un `proof.render_fingerprint` uguale al fingerprint corrente e uno stato compreso fra `prova_visuale_approvata`, `rendering`, `qa` e `consegnato`; i soli alias legacy accettati per lavori preesistenti sono `approvato`, `approved`, `pubblicato` e `published`. Confrontare automaticamente revisione, fingerprint, sistema visivo, snapshot canonico del contenuto, ordine, rapporto 4:5, geometria normalizzata e pixel catturati dell'anteprima e della produzione. Ripetere il confronto dopo la cattura e subito prima della sostituzione atomica del file. Qualsiasi differenza è bloccante.

Per questo percorso impostare `production.producer: approved-preview-dom-v2`. Il renderer locale rifiuta identificatori generici o appartenenti a un altro adapter: una prova prodotta altrove deve restare legata al proprio contratto e al proprio export.

Se un renderer o adapter non soddisfa questi requisiti, usare `layout` come fallback dichiarato.

### Invocazione local-editor

Dalla directory della skill, usare il runtime Node già verificato nel preflight e passare sempre l'URL completo dell'editor con token, un percorso PDF assoluto e la directory `node_modules` esistente che espone Playwright, Sharp e pdf-lib:

```bash
<node> scripts/export_review_pdf.cjs \
  --url "<http://127.0.0.1:porta/?token=token-sessione>" \
  --output "<percorso-assoluto/carousel.pdf>" \
  --node-modules "<percorso-assoluto/node_modules>"
```

Se il browser non viene risolto automaticamente ma esiste già un eseguibile verificato, aggiungere `--chrome "<percorso-assoluto-browser>"`. Non installare dipendenze o browser per completare l'export. Considerare riuscita la produzione soltanto quando il comando termina con stato `ok` e dichiara `preview_production_parity: "exact"`, `live_session_verified: true` e `approval_verified: true`.

Per ottenere nello stesso passaggio anche le singole card PNG a 1440×1800 e la contact sheet, aggiungere:

```bash
  --png-dir "<directory-assoluta-dedicata/png>" \
  --contact-sheet "<percorso-assoluto/contact-sheet.png>"
```

`--png-dir` deve indicare una directory dedicata: non usare la home, la directory di lavoro o una cartella condivisa con altri file. Il PDF, i PNG e l'eventuale contact sheet vengono preparati prima del gate finale e pubblicati come gruppo coordinato soltanto se revisione, fingerprint, contratto live e ricontrollo pixel restano validi; un errore ordinario durante la pubblicazione attiva il rollback degli output già sostituiti. Ogni singolo target usa sostituzioni durevoli e, su POSIX, sincronizza anche le directory. Un arresto forzato esattamente tra due sostituzioni non equivale però a una transazione filesystem indivisibile tra più percorsi: verificare sempre l'intero set prima della consegna. I PNG incorporati nel PDF vengono riusati senza una nuova codifica. Il ricontrollo finale cattura di nuovo soltanto la pagina di produzione e confronta ogni digest RGBA con la parità anteprima/produzione già dimostrata nella prima passata.

## Master, esportazione e scala tipografica

Progettare sempre sul master 4:5 da 1080×1350. Produrre l'export ad alta definizione a 1440×1800 scalando ogni misura per 4/3, senza reflow, ricomposizioni o cambi di densità. Le due dimensioni hanno lo stesso rapporto e non implicano una diversa grandezza fisica nel feed.

Usare il master per gli output 4:5. Quando un canale, placement organico o formato pubblicitario richiede un rapporto diverso, verificare le specifiche correnti e creare una variante separata. Conservare gerarchia e contenuti, proteggere la safe area e richiedere una nuova approvazione visuale. Non presentare il master 4:5 come compatibilità universale.

Usare sul canvas 1080×1350 questa scala nominale:

- copertina: 112 px, peso 800;
- titoli sezionali: 72 px, peso 800;
- testo principale e statement: 64 px, peso 620;
- etichette e metadati: 26 px;
- interlinea del corpo: 1.12;
- spazio aggiuntivo dopo ogni frase: 0.6 em;
- tracking del corpo: -0.025 em.

Adattare le dimensioni alle metriche reali del font mantenendo gerarchia e rapporti. Consentire una riduzione automatica massima dell'8%, quindi non scendere sotto il 92% della dimensione scelta. Se il contenuto continua a non entrare, restituire un errore di fit e richiedere una revisione del copy. Non ridurre ancora il carattere.

Un profilo può proporre una scala diversa soltanto con approvazione esplicita. Restano obbligatori la prova a 480 px e il limite di riduzione dell'8%.

## Controllo della prova visuale

Dopo l'approvazione dei testi creare una prova con:

1. copertina;
2. card con maggiore densità testuale;
3. chiusura, quando prevista.

Controllare obbligatoriamente la prova anche a 480×600, ottenuta dal master senza reflow, per simulare una visualizzazione desktop ridotta. Verificare inoltre la prova a risoluzione leggibile. Controllare gerarchia, densità, crop, famiglia e peso effettivi del font, ritorni a capo, contrasto e coerenza con il profilo. Verificare che la copertina sia priva di cornice, costellazione e indice modulare; sulla card densa e sulla chiusura verificare invece la firma strutturale obbligatoria descritta in [visual-systems.md](visual-systems.md). Impostare `proof.style_system_verified: true` soltanto dopo entrambi i controlli. Mostrare la prova all'utente e attendere l'approvazione prima di produrre le altre card. Ripetere la prova per ogni variante con rapporto diverso dal master.

## Controllo testuale

Confrontare ogni card con l'ultima anteprima approvata e verificare:

- testo esatto, punteggiatura e accenti;
- assenza degli asterischi temporanei;
- ritorni a capo coerenti;
- nomi propri, numeri, cautele e attribuzioni;
- chiusura specifica della fonte corrente;
- corrispondenza esatta di titolo e dell'eventuale sottotitolo approvato in copertina;
- font display effettivo su copertina e titoli e font body effettivo su testi, CTA e metadati;
- gerarchia subordinata del sottotitolo e ruolo `emphasis_italic` effettivamente risolto; se è Playfair Display, verificarne sempre la variante corsiva;
- ritorno a capo dopo ogni punto di frase, senza spezzare decimali, versioni o abbreviazioni;
- presenza di un blocco distinto per ogni frase e di uno spazio `sentence_gap_em` dopo ogni frase tranne l'ultima, aggiuntivo rispetto a `body_line_height`;
- `summary_bold` proposta di default nelle card interne con corpo, ma facoltativa e liberamente rimovibile; più trattamenti ammessi su parole o locuzioni distinte, senza stili multipli sulla stessa unità né selezioni sovrapposte;
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
- logo corretto per il fondo quando `logo_mode` è `auto`, oppure sua assenza intenzionale quando è `hidden`; verificare separatamente le varianti per fondo chiaro e scuro e segnalare quelle mancanti;
- numerazione progressiva delle pagine nell'angolo superiore destro di ogni card, inclusi copertina e chiusura, dentro la safe area e senza interferire con testo, logo o visuale;
- coerenza dell'alternanza cromatica;
- grassetti, corsivi, sottolineature ed evidenziatori approvati, senza corsivi sintetici o sovrapposizioni;
- evidenziatore adattato separatamente a ogni fondo: accento originale quando leggibile, variante derivata scura con testo chiaro oppure chiara con testo scuro, sempre con contrasto del testo almeno 4.5:1;
- sistema visivo risolto, varianti controllate e struttura HTML/CSS/SVG coerenti;
- firma strutturale obbligatoria presente sulle card interne e sulla chiusura e geometricamente coerente con la prova approvata: cornice completa per `editorial-frame`, costellazione di cinque corpi per `editorial-halftone`, indice modulare e guida orizzontale per `corporate-modular`;
- copertina priva degli elementi strutturali dei tre sistemi, così immagine, titolo, numerazione e firma non entrano in conflitto;
- eventuale immagine di copertina che non interferisca con la lettura;
- dimensioni e rapporto d'aspetto richiesti;
- sfondo esteso esattamente da `x=0`, `y=0` fino a 1080×1350, senza strisce o margini introdotti dal renderer;
- assenza di SVG, filtri o elementi nascosti che occupino spazio nel flusso del documento;
- in modalità `narrative`, slide interne pulite e prive di visuali decorativi non approvati;
- distanza fra frasi visibilmente maggiore dell'interlinea fra righe avvolte della stessa frase, anche nella prova a 480 px;
- coerenza della tecnica visiva tra tutte le card che contengono immagini.

## Accessibilità

Verificare inoltre:

- contrasto di almeno 4.5:1 per testo normale e 3:1 per testo grande;
- leggibilità del testo alla dimensione effettiva del feed, non soltanto alla risoluzione originale;
- leggibilità di titoli, corpo, etichette e metadati nella prova a 480 px di larghezza;
- assenza di significati affidati esclusivamente a colore, peso, corsivo, famiglia o posizione;
- ordine di lettura coerente tra copertina, contenuti e chiusura;
- presenza nel manifest di alt text per ogni slide oppure di una trascrizione completa e ordinata del carosello;
- descrizione del visuale quando aggiunge informazione non presente nei testi.

Se uno dei cinque colori richiesti (`background_light`, `background_dark`, `text_on_light`, `text_on_dark`, `accent`) non è dichiarato esplicitamente o non usa `#RRGGBB`, non approvare il fallback mostrato dall'anteprima. Se una palette identificativa dichiarata non supera il contrasto minimo, segnalarlo e chiedere una scelta. Non alterarla silenziosamente.

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
- in modalità `renderer` o `adapter`, presenza di `production.supported_style_systems` con il sistema selezionato e di `proof.style_system_verified: true`;
- nel percorso `local-editor`, esito positivo del contratto `approved-preview-dom-v2`, prova visuale ancora approvata e legata agli asset correnti, e parità esatta di revisione, contenuto, geometria e pixel tra anteprima e produzione prima e dopo la cattura;
- assenza di file incompleti o duplicati presentati come finali.

Se un controllo fallisce, conservare gli output validi, mantenere lo stato precedente e offrire ripetizione o fallback. Non avanzare a `consegnato`.

## Consegna

Indicare numero di slide, dimensioni, formati e modalità usata: `renderer`, `adapter` o `layout`. Consegnare PNG, PDF, JSON o layout soltanto se effettivamente prodotti e verificati. Includere alt text o trascrizione quando previsti dal manifest.

Non creare ZIP, brand pack o copie aggiuntive senza richiesta esplicita.
