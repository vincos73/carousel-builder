---
name: carousel-builder
description: Trasforma URL, articoli e testi in caroselli editoriali 4:5, guidando identità visiva e approvazione in editor locale o conversazione.
---

# Carousel Builder

Versione: **2.11.4**

Separare fonte, identità, testi, prova visuale, produzione e QA. Il consenso combinato vale solo per una preview tipografica definitiva conforme a [visual-review.md](references/visual-review.md); altrimenti servono due approvazioni e due ricevute durevoli prima del rendering. La richiesta iniziale autorizza solo la proposta editoriale.

Identità, logo, URL, firma e attribuzioni devono essere forniti o approvati dall'utente; non ricavarli da fonte, memoria o profilo personale.

Usare solo strumenti disponibili, senza installare pacchetti né scaricare browser, font o dipendenze. Nel percorso locale eseguire esclusivamente `scripts/review_server.py`, `scripts/process_review.py`, `scripts/attach_cover_asset.py`, `scripts/carousel_status.py`, `scripts/advance_workflow.py`, `scripts/finalize_delivery.py`, `scripts/apply_review.py` e `scripts/export_review_pdf.cjs`. Risorse esterne solo da fonti approvate.

Il workflow è `bozza` → `testi_approvati` → `prova_visuale_approvata` → `rendering` → `qa` → `consegnato`. In `local-editor` non modificare stato o ricevute. `process_review.py` applica i checkpoint coperti; `apply_review.py` è di recovery, `advance_workflow.py` entra in `rendering` e `finalize_delivery.py` chiude i gate. `adapter` e `layout` rispettano gli stessi checkpoint senza simulare attestazioni locali.

Prima del passo successivo o dopo recovery, eseguire `carousel_status.py` con manifest e sessione. `next_action` diagnostica senza modificare file.

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

Usare `local-editor` solo se è possibile eseguire Python 3.10 o successivo, aprire `127.0.0.1` nel browser dell'utente e ricevere gli eventi del server. `local-editor` è obbligatorio quando le capacità esistono: aprirlo subito una sola volta nella superficie già assegnata, senza chiedere conferma. Non dichiararlo disponibile finché non è visibile.

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
3. Selezionare e mostrare un solo sistema consigliato secondo [visual-systems.md](references/visual-systems.md). Offrire un'alternativa soltanto su richiesta o quando la classificazione è incerta; mantenere `editorial-halftone` come opzione avanzata. Salvare la scelta in `visual_style_system`; un nome, una palette o un font senza firma strutturale non costituiscono una prova valida.
4. Registrare `typographic` per default, oppure `generated`/`provided` se l'utente sceglie un visuale; non generare ancora l'immagine. Nel percorso locale creare uno schema 1.4 `bozza` con `workflow_receipts: []`. Controllare tutte le card nel sistema selezionato anche a 480 px: nessuna slide iniziale deve mostrare avvisi di densità o overflow. Il copy generato ha massimo 180 caratteri con titolo e 320 senza. Correggere o dividere senza scendere sotto il 92% della scala.
5. Avviare e aprire l'editor come descritto in [visual-review.md](references/visual-review.md). Restare in ascolto dell'evento: non terminare il turno e non chiedere all'utente di scrivere «fatto».
   Subito dopo l'apertura entrare nel ciclo di ricezione del processo già avviato, con attese di massimo 50 secondi. Finché l'editor mostra `Ora tocca a te`, non inviare una risposta finale e non lasciare il server senza una chiamata di attesa attiva. Quando arriva un evento `feedback`, inviare immediatamente un aggiornamento in chat che confermi ID, azione e prossimo passo; soltanto dopo eseguire `process_review.py`.
6. Alla ricezione, confermare subito in chat il batch e l'azione successiva. Elaborare il batch append-only con `process_review.py`; esaminare commenti, warning, alt text e trascrizione stale. Conservare il testo scritto dall'utente salvo incompatibilità dichiarata con fonte, modalità `verbatim` o produzione.
7. Dopo ogni batch ripetere i controlli e lasciare che l'editor ricarichi il manifest. Quando [visual-review.md](references/visual-review.md) abilita `Approva e produci`, `process_review.py` registra in sequenza `testi_approvati` e `prova_visuale_approvata`; altrimenti avanza solo il primo checkpoint. Se resta un blocco, mantiene `bozza` e lo espone nell'output.
8. Nel percorso conversazionale mostrare prima le slide cambiate e poi l'intera sequenza. Offrire `Approva profilo e testi`, `Modifica il profilo` o `Modifica i testi`.

## Fase 2: prova visuale

1. Saltare questa fase se il percorso combinato ha già portato il manifest a `prova_visuale_approvata`. Altrimenti, se `cover_mode` richiede un visuale, estrarre 2-3 concetti e tradurli in una sola metafora secondo [cover-visual.md](references/cover-visual.md), quindi generare o acquisire l'immagine soltanto ora. Nel percorso locale collegarla attraverso `attach_cover_asset.py`, mai modificando il manifest a mano. Se la modalità è `typographic` o l'immagine non è producibile, mantenere una copertina tipografica completa.
2. Applicare la firma del sistema selezionato alle card interne e alla chiusura, mai alla copertina. Convertire le enfasi approvate in campi espliciti e rimuovere gli asterischi.
3. Preparare il manifest conforme a [carousel-schema.md](references/carousel-schema.md), con produzione, accessibilità e prova canonica: copertina, card interna più densa e chiusura se presente.
4. Verificare il campione a 480×600 e a risoluzione leggibile secondo [production-qa.md](references/production-qa.md). Controllare font reali, fit, contrasto, crop e firma strutturale.
5. Mostrare la prova e offrire approvazione, cambio grafico o ritorno ai testi. La cover visuale usa titolo a sinistra e immagine verticale a destra, senza overlay o trasparenza. Nel percorso locale restare in attesa attiva a ogni prova. Avvisi editoriali, enfasi non applicabili, contrasto consigliato e slide campione non ancora viste restano informativi: l'approvazione esplicita dell'utente li accetta. Restano bloccanti soltanto errori che impediscono una produzione coerente, come rendering non pronto, overflow, struttura minima assente, modifiche non salvate, asset richiesto mancante o sessione non valida.
6. Elaborare il batch visuale con `process_review.py`: avanza a `prova_visuale_approvata` soltanto quando fingerprint, campione, stile, browser Chromium e produttore superano i gate. Dopo una modifica grafica mostrare una nuova prova; non riaprire i testi se il copy è identico.

## Fase 3: produzione, QA e consegna

1. Leggere integralmente [production-qa.md](references/production-qa.md). Nel percorso locale seguire anche [workflow-state.md](references/workflow-state.md) e avanzare a `rendering` soltanto con proof corrente e output attesi dichiarati.
2. Nel percorso locale esportare dallo stesso DOM `.slide-preview` e dallo stesso CSS approvati, con l'invocazione documentata in [production-qa.md](references/production-qa.md#invocazione-local-editor). Non creare un secondo template. Richiedere parità esatta di contenuto, revisione, fingerprint, geometria e pixel prima e dopo la cattura.
3. Se manca un controllo tipografico affidabile o il produttore non implementa il sistema selezionato, non generare card complete: consegnare un layout dettagliato dichiarando il limite.
4. Controllare automaticamente tutte le slide. Umanamente ispezionare la contact sheet e aprire copertina, card più densa, chiusura e anomalie; ampliare solo se emerge un difetto. Dopo correzioni ripetere proof e transizioni prima di `rendering`; non riesportare da `qa` o `consegnato`.
5. Dopo export e ispezione, usare `finalize_delivery.py` con risultato di render e report QA. Lo script avanza `rendering` → `qa` e poi `qa` → `consegnato` soltanto con revisione, fingerprint, campione umano e digest validi; se il secondo gate fallisce conserva lo stato `qa`. Non presentare output parziali come finali.
6. Consegnare solo artefatti realmente prodotti e aperti, indicando quantità, dimensioni, formato e modalità. Creare uno ZIP soltanto su richiesta esplicita.

## Contratto editoriale essenziale

- Usare solo informazioni della fonte, salvo richiesta esplicita di ricerca. Conservare numeri, nomi, cautele, condizioni e attribuzioni; non inventare causalità o certezza. Non usare em dash nei testi italiani.
- Mantenere normalmente 5-6 slide di contenuto. In `verbatim` non riscrivere senza autorizzazione. In `narrative` lasciare vuoti i titoli interni; in `sectional` usarli solo quando aiutano l'autonomia.
- Includere sempre la copertina e, per `newsletter` e `article`, la chiusura salvo scelta diversa. Il sottotitolo è opzionale e mai inventato. Generare la CTA dalla fonte corrente, non dal profilo riutilizzabile.
- Separare le frasi con `\n`, senza righe vuote; non spezzare abbreviazioni, iniziali, decimali, domini o URL. Nel render ogni frase è un blocco con `sentence_gap_em: 0.6` oltre a `body_line_height`.
- Usare i font approvati nei ruoli `display`, `body` ed eventuale `emphasis_italic`; non sintetizzare il corsivo. `*_bold`, `*_italic`, `*_underline` e `*_accent` contengono locuzioni esatte, distinte e non sovrapposte. Il grassetto suggerito resta rimovibile e non blocca l'approvazione.
- Usare HTML/CSS/SVG deterministici. Le slide interne restano tipografiche salvo richiesta esplicita; gli SVG strutturali del sistema sono ammessi. Numerare ogni pagina in alto a destra dentro la safe area; nella cover split il numero resta in alto a destra nella colonna testuale e non invade l'immagine.
- Il master è 1080×1350 in 4:5, l'export 1440×1800 e la prova 480×600, senza reflow. Per rapporti diversi creare una variante separata e una nuova approvazione. L'adattamento automatico non supera l'8%; altrimenti si rivede il copy.
- Verificare accessibilità, ordine di lettura, trascrizione o alt text, contrasto e leggibilità a dimensione feed. Non affidare significati soltanto a colore, peso, corsivo, famiglia o posizione.

## Profili, modifiche e recovery

Un profilo riutilizzabile contiene regole, non testi della singola fonte. Logo e font proprietari restano asset separati. Dopo l'approvazione offrire una sola volta il salvataggio come `<nome-brand>-carousel-brand.json`; non modificare la skill né incorporarvi asset personali.

Per modifiche testuali mostrare le slide cambiate e poi la sequenza aggiornata. Per modifiche solo grafiche non riaprire i testi, ma richiedere una nuova prova. Riutilizzare la cover soltanto se tesi, metafora e composizione restano invariate.

In caso di errore non avanzare lo stato e preservare gli artefatti validi. Nel percorso locale seguire [review-recovery.md](references/review-recovery.md) soltanto dopo un'interruzione o conflitto. Un errore di soli metadati tecnici può rielaborare lo stesso batch senza nuovo consenso. Le correzioni riaprono atomicamente `bozza` se cambiano copy, ordine o profilo, oppure `testi_approvati` se cambiano solo stile, logo o enfasi. Ripetere solo i checkpoint invalidati e non modificare stato o ricevute a mano.
