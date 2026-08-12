---
name: carousel-builder
description: Trasforma URL, articoli, newsletter, note e testi in caroselli editoriali verticali 4:5 per Instagram, LinkedIn e altri canali social. Configura o riutilizza un'identità visiva, guida l'approvazione editoriale, usa un editor HTML locale quando la sessione supporta Python, browser locale e ricezione degli eventi, e passa automaticamente alla revisione conversazionale negli altri ambienti.
---

# Carousel Builder

Versione: **2.8.12**

Creare caroselli separando fonte, identità, testi, prova visuale, produzione e QA. Richiedere due approvazioni distinte prima del rendering completo: prima profilo e testi, poi la prova visuale. Una richiesta iniziale di creare un carosello autorizza la proposta editoriale, non la produzione grafica.

Non ricavare identità, logo, URL, firma o attribuzioni dalla fonte, dalla memoria o dal profilo personale. Usare solo ciò che l'utente fornisce o approva esplicitamente.

Usare soltanto strumenti già disponibili. Non installare pacchetti e non scaricare browser, font o dipendenze. Nel percorso locale eseguire esclusivamente gli script inclusi e verificati dalla skill: `scripts/review_server.py`, `scripts/apply_review.py`, `scripts/advance_workflow.py` e `scripts/export_review_pdf.cjs`. Recuperare risorse esterne soltanto da una fonte fornita o approvata dall'utente.

Il workflow canonico è `bozza` → `testi_approvati` → `prova_visuale_approvata` → `rendering` → `qa` → `consegnato`. Nel percorso `local-editor` avanzare soltanto con `advance_workflow.py`, usando sessione, revisione attesa ed evidenza richiesta: non modificare `workflow_state` o le ricevute a mano e non auto-approvare. `apply_review.py` non avanza mai; quando arriva una correzione dopo un checkpoint, riapre atomicamente l'ultimo checkpoint ancora valido. Nei percorsi `adapter` e `layout` applicare gli stessi checkpoint con il contratto del produttore disponibile, senza invocare o simulare le attestazioni del renderer locale.

## Routing delle istruzioni

Caricare solo ciò che serve alla fase corrente:

- leggere sempre [runtime-preflight.md](references/runtime-preflight.md) all'inizio;
- leggere [brand-onboarding.md](references/brand-onboarding.md) solo se manca un'identità sufficiente e [brand-profile.md](references/brand-profile.md) quando si costruisce o valida un profilo;
- leggere [editorial-workflow.md](references/editorial-workflow.md) e [semantic-emphasis.md](references/semantic-emphasis.md) prima di preparare i testi;
- leggere [visual-systems.md](references/visual-systems.md) prima di proporre il sistema grafico;
- leggere [visual-review.md](references/visual-review.md) soltanto nel percorso `local-editor`; le capacità dettagliate e il recovery si caricano solo nei casi indicati da quella reference;
- leggere [workflow-state.md](references/workflow-state.md) nel percorso `local-editor` prima della prima transizione e conservarlo come contratto fino alla consegna;
- leggere [cover-visual.md](references/cover-visual.md) e [carousel-schema.md](references/carousel-schema.md) dopo l'approvazione dei testi;
- leggere [production-qa.md](references/production-qa.md) prima della prova visuale e mantenerlo come contratto fino alla consegna.

## Percorso di revisione

Usare `local-editor` solo se è possibile eseguire Python 3.10 o successivo, aprire `127.0.0.1` nel browser dell'utente e ricevere gli eventi del server. Quando tutte e tre le capacità esistono, `local-editor` è obbligatorio: aprirlo nello stesso turno appena manifest e preflight sono pronti, senza chiedere se l'utente lo desidera. Non dichiararlo disponibile finché non è visibile.

Usare `conversation` quando almeno una capacità è realmente assente o fallisce. Mostrare sezioni Markdown normali e modificabili, mai HTML stampato, code fence o blocchi monospazio. Dichiarare il fallback e mantenere gli stessi checkpoint.

## Fase 0: preflight

1. Determinare gli output realmente producibili: copertina, card tipografiche, PNG, PDF o solo layout. Comunicarli in una frase semplice.
2. Leggere tutta la fonte. Un URL autorizza la lettura di quell'URL, non di risorse estranee. Se non è leggibile, chiedere testo o documento; non colmare i vuoti.
3. Classificare la fonte come `newsletter`, `article`, `notes` o `verbatim`; accettare `rework` e `social` come alias legacy. Scegliere separatamente `narrative` per una progressione dipendente o `sectional` per sezioni autonome.
4. Validare il profilo fornito, costruirne uno con l'utente o usare quello neutro soltanto dopo una scelta esplicita.
5. Selezionare il percorso di revisione in base alle capacità osservate.

## Fase 1: profilo e testi

1. Costruire copertina e sequenza secondo [editorial-workflow.md](references/editorial-workflow.md). Nel percorso rapido mostrare nella stessa revisione prima `Anteprima profilo brand` e poi `Anteprima testi`; nel guidato approvare prima il profilo.
2. Indicare profilo, fonte, `sequence_mode`, master 1080×1350, export previsto, numero di slide e testi esatti. Ogni frase compiuta inizia su una nuova riga. Mostrare solo contenuti destinati alle slide e le minime informazioni di revisione, non manifest o note tecniche.
3. Proporre i tre sistemi di [visual-systems.md](references/visual-systems.md) sullo stesso contenuto e identità. Salvare la scelta in `visual_style_system`; un nome, una palette o un font senza firma strutturale non costituiscono una prova valida.
4. Nel percorso locale creare uno schema 1.4 in stato `bozza`, con `workflow_receipts: []`. Prima di aprire l'editor, controllare tutte le card nei tre sistemi, anche a 480 px: nessuna slide iniziale deve mostrare avvisi di densità o overflow. Il copy generato con titolo è lungo al massimo 180 caratteri, quello senza titolo al massimo 320 caratteri. Correggere o dividere finché il fit è pulito senza scendere sotto il 92% della scala.
5. Avviare e aprire l'editor come descritto in [visual-review.md](references/visual-review.md). Restare in ascolto dell'evento: non terminare il turno e non chiedere all'utente di scrivere «fatto».
6. Alla ricezione, confermare subito che il batch è in lavorazione. Applicare il percorso append-only con `apply_review.py`; esaminare commenti, warning, alt text e trascrizione stale. Conservare il testo scritto dall'utente salvo incompatibilità dichiarata con fonte, modalità `verbatim` o produzione.
7. Dopo ogni batch ripetere i controlli e lasciare che l'editor ricarichi il manifest. Una richiesta `approve` è esplicita ma non sufficiente: avanzare a `testi_approvati` soltanto con i gate descritti in [workflow-state.md](references/workflow-state.md). Se resta un blocco, mantenere `bozza` e mostrarlo.
8. Nel percorso conversazionale mostrare prima le slide cambiate e poi l'intera sequenza. Offrire `Approva profilo e testi`, `Modifica il profilo` o `Modifica i testi`.

## Fase 2: prova visuale

1. Estrarre 2-3 concetti e tradurli in una sola metafora secondo [cover-visual.md](references/cover-visual.md). Usare un'immagine solo per la copertina e solo se generatore o asset fornito sono disponibili; altrimenti creare una copertina tipografica completa.
2. Applicare la firma del sistema selezionato alle card interne e alla chiusura, mai alla copertina. Convertire le enfasi approvate in campi espliciti e rimuovere gli asterischi.
3. Preparare il manifest conforme a [carousel-schema.md](references/carousel-schema.md), con produzione, accessibilità e prova canonica: copertina, card interna più densa e chiusura se presente.
4. Verificare il campione a 480×600 e a risoluzione leggibile secondo [production-qa.md](references/production-qa.md). Controllare font reali, fit, contrasto, crop e firma strutturale.
5. Mostrare la prova e offrire `Approva la prova visuale`, `Cambia la direzione grafica` o `Torna ai testi`. Nel percorso locale restare in attesa attiva anche in questo checkpoint e in ogni prova successiva.
6. Applicare il batch visuale e avanzare a `prova_visuale_approvata` soltanto quando fingerprint, campione, stile, browser Chromium e produttore superano i gate. Dopo una modifica grafica mostrare una nuova prova; non riaprire i testi se il copy è identico.

## Fase 3: produzione, QA e consegna

1. Leggere integralmente [production-qa.md](references/production-qa.md). Nel percorso locale seguire anche [workflow-state.md](references/workflow-state.md) e avanzare a `rendering` soltanto con proof corrente e output attesi dichiarati.
2. Nel percorso locale esportare dallo stesso DOM `.slide-preview` e dallo stesso CSS approvati, con l'invocazione documentata in [production-qa.md](references/production-qa.md#invocazione-local-editor). Non creare un secondo template. Richiedere parità esatta di contenuto, revisione, fingerprint, geometria e pixel prima e dopo la cattura.
3. Se manca un controllo tipografico affidabile o il produttore non implementa il sistema selezionato, non generare card complete: consegnare un layout dettagliato dichiarando il limite.
4. Per sequenze fino a 10 slide ispezionare contact sheet e ogni card a dimensione leggibile; per sequenze più lunghe seguire il campionamento del QA. Se emerge un difetto, applicare la correzione, lasciare che il workflow riapra il checkpoint ancora valido e ripetere proof e transizioni richieste prima di tornare a `rendering`: non riesportare direttamente dagli stati `qa` o `consegnato`.
5. Avanzare `rendering` → `qa` soltanto con il risultato verificato dell'export. Avanzare `qa` → `consegnato` soltanto con report QA positivo, revisione e fingerprint correnti e digest degli artefatti verificati. Non presentare output parziali come finali.
6. Consegnare solo artefatti realmente prodotti e aperti, indicando quantità, dimensioni, formato e modalità. Creare uno ZIP soltanto su richiesta esplicita.

## Contratto editoriale essenziale

- Usare solo informazioni della fonte, salvo richiesta esplicita di ricerca. Conservare numeri, nomi, cautele, condizioni e attribuzioni; non inventare causalità o certezza. Non usare em dash nei testi italiani.
- Mantenere normalmente 5-6 slide di contenuto. In `verbatim` non riscrivere senza autorizzazione. In `narrative` lasciare vuoti i titoli interni; in `sectional` usarli solo quando aiutano l'autonomia.
- Includere sempre la copertina e, per `newsletter` e `article`, la chiusura salvo scelta diversa. Il sottotitolo è opzionale e mai inventato. Generare la CTA dalla fonte corrente, non dal profilo riutilizzabile.
- Separare le frasi con `\n`, senza righe vuote; non spezzare abbreviazioni, iniziali, decimali, domini o URL. Nel render ogni frase è un blocco con `sentence_gap_em: 0.6` oltre a `body_line_height`.
- Usare i font approvati nei ruoli `display`, `body` ed eventuale `emphasis_italic`; non sintetizzare il corsivo. `*_bold`, `*_italic`, `*_underline` e `*_accent` contengono locuzioni esatte, distinte e non sovrapposte. Il grassetto suggerito resta rimovibile e non blocca l'approvazione.
- Usare HTML/CSS/SVG deterministici. Le slide interne restano tipografiche salvo richiesta esplicita; gli SVG strutturali del sistema sono ammessi. Numerare ogni pagina in alto a destra dentro la safe area.
- Il master è 1080×1350 in 4:5, l'export 1440×1800 e la prova 480×600, senza reflow. Per rapporti diversi creare una variante separata e una nuova approvazione. L'adattamento automatico non supera l'8%; altrimenti si rivede il copy.
- Verificare accessibilità, ordine di lettura, trascrizione o alt text, contrasto e leggibilità a dimensione feed. Non affidare significati soltanto a colore, peso, corsivo, famiglia o posizione.

## Profili, modifiche e recovery

Un profilo riutilizzabile contiene regole, non testi della singola fonte. Logo e font proprietari restano asset separati. Dopo l'approvazione offrire una sola volta il salvataggio come `<nome-brand>-carousel-brand.json`; non modificare la skill né incorporarvi asset personali.

Per modifiche testuali mostrare le slide cambiate e poi la sequenza aggiornata. Per modifiche solo grafiche non riaprire i testi, ma richiedere una nuova prova. Riutilizzare la cover soltanto se tesi, metafora e composizione restano invariate.

In caso di errore non avanzare lo stato e preservare gli artefatti validi. Nel percorso locale seguire [review-recovery.md](references/review-recovery.md) soltanto dopo un'interruzione o conflitto; altrimenti spiegare il risultato disponibile e offrire ripetizione, fallback o interruzione. Gli avanzamenti locali sono solo in avanti; una correzione applicata dopo un checkpoint riapre atomicamente `bozza` se cambia copy, ordine o profilo, oppure `testi_approvati` se cambia soltanto stile/logo. Ripetere i checkpoint richiesti e non modificare mai stato o ricevute a mano.
