# Workflow editoriale

## Regole comuni

- Formulare un `cover_title` breve, fedele e comprensibile autonomamente.
- Aggiungere `cover_subtitle` soltanto se l'utente lo fornisce o lo approva esplicitamente. È sempre subordinato al titolo e renderizzato nel ruolo `emphasis_italic` risolto dal profilo.
- Nei testi, inserire un ritorno a capo dopo ogni punto che conclude una frase, senza righe vuote. Non spezzare decimali e versioni (`1.2`) né abbreviazioni comuni (`es.`, `ecc.`).
- Mantenere la promessa della copertina lungo tutta la sequenza.
- Nel rendering trasformare ciascuna frase in un blocco distinto e applicare `sentence_gap_em: 0.6` fra blocchi consecutivi, oltre alla normale interlinea interna.
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
- Nel fallback conversazionale mostrare tra asterischi soltanto le eventuali frasi proposte nel ruolo corsivo approvato; nell'editor locale usare i comandi di enfasi senza inserire asterischi nel testo.
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
- Per il copy generato, trattare le soglie come limiti rigidi: massimo 320 caratteri nelle card senza titolo e massimo 180 caratteri nei riassunti con titolo. Non consegnare né aprire nell'editor una bozza generata che li superi.
- Per testo `verbatim` o scritto dall'utente, mostrare il superamento senza riscriverlo automaticamente e proporre una divisione. Anche sotto soglia, la decisione finale dipende dal fit reale sul master 1080×1350 e dalla prova a 480 px.
- Prima di invitare l'utente nell'editor locale, verificare l'intera bozza nel sistema visivo consigliato. Se compare un avviso di soglia o il testo non entra dopo l'adattamento massimo dell'8%, riscrivere o dividere la slide e ripetere il controllo: l'utente deve ricevere una prima proposta già impaginabile, non un errore da risolvere. Verificare un'alternativa soltanto se verrà realmente mostrata.
- Nel fallback conversazionale verificare gli asterischi bilanciati. Nel manifest e nell'editor proporre un grassetto nelle card interne con corpo, senza renderlo obbligatorio; consentire più trattamenti su parole o locuzioni distinte e impedire stili multipli sulla stessa unità o selezioni sovrapposte.
- Trattare nomi propri composti come unità indivisibili.
- Verificare che nessuna riga contenga due frasi compiute.
