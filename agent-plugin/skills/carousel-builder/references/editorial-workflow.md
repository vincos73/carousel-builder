# Workflow editoriale

## Regole comuni

- Formulare un `cover_title` breve, fedele e comprensibile autonomamente.
- Non aggiungere un sottotitolo alla copertina.
- Mantenere la promessa della copertina lungo tutta la sequenza.
- Inserire un ritorno a capo dopo ogni frase compiuta.
- Conservare cautele, attribuzioni e condizioni che cambiano il significato.
- Non aggiungere ordinamenti, nessi causali o conclusioni che la fonte non formula.

## Modalità della sequenza

Scegliere e registrare `sequence_mode` prima di scrivere le slide.

### Narrativa

Usarla quando le slide sviluppano un'unica tesi e dipendono dall'ordine di lettura. È la scelta normale per articoli argomentativi e note che descrivono un processo.

- Lasciare vuoto `items[].title`.
- Scrivere ogni corpo come passaggio della stessa progressione, evitando ripartenze e ripetizioni.
- Non inserire nelle card titoli interni, eyebrow, numeri, etichette tecniche o nomi del layout.
- Usare soltanto il visuale di copertina; mantenere le card interne pulite e tipografiche.
- La firma o il sito possono restare come elemento discreto soltanto se fanno parte del profilo approvato.

### Sezionale

Usarla quando ogni slide rappresenta una notizia, categoria o sezione autonoma. È la scelta normale per newsletter con più notizie.

- Usare un titolo breve quando rende la slide comprensibile anche isolata.
- Lasciare il titolo vuoto soltanto se il corpo funziona già come statement autosufficiente.
- Non inserire etichette tecniche, numeri o nomi del layout nel contenuto renderizzato.

Se la distinzione è incerta e cambia sensibilmente il risultato, proporre la modalità più probabile e dichiarare l'ipotesi nell'anteprima.

## Newsletter

- Estrarre 3-6 notizie principali.
- Usare un titolo breve e un riassunto autosufficiente di massimo 30 parole per slide.
- Non fondere notizie diverse.
- Usare come copertina il tema dominante o la notizia principale.

## Articolo

- Formulare la copertina dalla tesi o dalla tensione centrale.
- Costruire una sequenza logica di massimo sei passaggi.
- Preferire progressioni causa-effetto, problema-risposta o tesi-prova-conseguenza soltanto quando sostenute dalla fonte.
- Usare normalmente `sequence_mode: narrative`; scegliere `sectional` soltanto se le parti sono realmente autonome.

## Note

- Ricavare 3-6 passaggi in sequenza, adattandoli alla densità della fonte.
- Non aggiungere slide per raggiungere un numero prefissato.
- Non creare una slide riepilogativa se ripete soltanto elementi sviluppati nelle card successive.
- Lasciare vuoto il titolo quando il testo funziona come affermazione autonoma.
- Limitare il testo a circa 20-30 parole per slide.

## Testo esatto

- Dividere soltanto sui doppi a capo.
- Copiare ogni paragrafo senza riscriverlo.
- Formulare la copertina senza alterare le card.
- Se un paragrafo non entra dopo la riduzione massima dell'8%, fermarsi. In modalità `verbatim`, chiedere se dividerlo su più card o cambiare formato senza riscriverlo; nelle altre modalità richiedere una revisione del copy. Non ridurre ulteriormente il font.

## Chiusura

- Se `outro.copy_mode` è `generate_from_source`, generare titolo e corpo dalla fonte corrente e dall'obiettivo approvato. Generare l'eyebrow soltanto se il profilo lo richiede esplicitamente.
- Non aggiungere siti, offerte o firme non presenti nel profilo.
- Inserire il testo esatto della chiusura nel manifest del carosello, non nel profilo riutilizzabile.

## Anteprima

- Mostrare sempre l'intera sequenza prima della produzione.
- Numerare la copertina come slide 1.
- Dichiarare profilo, fonte, formato e numero totale di slide.
- Mostrare tra asterischi soltanto le eventuali frasi proposte nel secondo carattere approvato.
- Non mostrare campi tecnici o prompt visuali.
- Mostrare e contare la chiusura per `newsletter` e `article`, salvo esclusione.
- Nel percorso rapido, anteporre l'anteprima del profilo e offrire `Approva profilo e testi`, `Modifica il profilo` e `Modifica i testi`.
- Nel percorso guidato, mostrare i testi dopo l'approvazione del profilo.
- Le diciture usate nell'anteprima conversazionale per identificare le slide non devono diventare etichette nel rendering.
- Dopo ogni modifica, mostrare prima le slide cambiate e poi l'intera sequenza aggiornata. Attendere un nuovo via libera.
- Dopo l'approvazione editoriale, passare alla prova visuale prevista in `SKILL.md`; non produrre l'intero batch prima che anche quella prova sia approvata.

## Controllo editoriale

- In modalità `sectional`, preferire titoli entro 10 parole. In modalità `narrative`, verificare che i titoli interni siano vuoti.
- Evitare che il corpo ripeta letteralmente il titolo senza aggiungere informazione.
- Segnalare card senza titolo oltre 320 caratteri e riassunti con titolo oltre 180 caratteri.
- Trattare le soglie in caratteri come avvisi preliminari; la decisione finale dipende dal fit reale sul master 1080×1350 e dalla prova a 480 px.
- Verificare asterischi bilanciati e massimo due segmenti per card.
- Trattare nomi propri composti come unità indivisibili.
- Verificare che nessuna riga contenga due frasi compiute.
