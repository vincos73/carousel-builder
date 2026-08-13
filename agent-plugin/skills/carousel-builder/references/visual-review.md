# Revisione editoriale visuale

Il modello `/api/session` espone `visual_proofs` come oggetto calcolato dal server con `selected_style_system`, identità condivisa e tre opzioni. Non persistere questo oggetto nel manifest: inviare la scelta come `visual_style_system` e applicarla con `scripts/apply_review.py`.

Usare questa modalità soltanto quando Python 3.10 o successivo e un browser locale sono già disponibili. Non installare dipendenze. Il browser non deve scrivere direttamente nel manifest: deve inviare un batch strutturato che l'agente applica e controlla.

## Preparazione

1. Salvare il manifest in una cartella accessibile. Collegare gli asset di copertina prima della prima sessione locale: in `bozza` restano nascosti. Non mutarli dopo un checkpoint.
2. Scegliere una cartella di sessione dedicata, esterna alla cartella della skill.
3. Avviare il server con percorsi assoluti:

```text
python3 <skill>/scripts/review_server.py <manifest.json> --session-dir <session-dir>
```

4. Leggere dalla prima riga JSON l'indirizzo locale e aprirlo immediatamente nel browser disponibile: quando le capacità locali esistono, l'apertura dell'editor è obbligatoria e non va sostituita da una domanda o da un'anteprima conversazionale. Prima di consegnarlo all'utente, controllare copertina e tutte le card in ciascuno dei tre sistemi visivi, anche alla larghezza di 480 px. Se la bozza iniziale mostra un avviso di soglia o overflow, correggere il copy nel manifest, aggiornare la revisione se necessario e ripetere il controllo finché tutte le prove sono pulite.
5. Mantenere attivo il processo mentre l'utente revisiona e restare in ascolto del suo output in ogni checkpoint dell'editor: correzione o approvazione di profilo e testi, prova visuale e nuova prova dopo una modifica. Non concludere il turno subito dopo aver aperto l'editor e non chiedere all'utente di tornare in chat per scrivere «fatto».
6. Attendere l'evento del server con il meccanismo di ripresa del processo disponibile nella sessione. Usare attese non superiori a 50 secondi per volta, così da poter inviare un aggiornamento conciso almeno ogni 60 secondi. Dopo ogni attesa senza output, leggere `<session-dir>/session-state.json`: se `last_feedback_id` è valorizzato e diverso da `applied_feedback_id`, usare `last_action` e `last_feedback_path` come segnale durevole del batch anche quando la notifica sul canale del processo non è stata propagata. Per uno stato legacy privo del percorso usare `<session-dir>/feedback.json`. Ripetere l'attesa e il controllo finché arriva un batch, l'utente interrompe il lavoro o il task non può più restare attivo.
7. Considerare l'output del processo una notifica immediata e `session-state.json` la fonte durevole per il recupero. Se la sessione non consente un'attesa attiva sufficientemente lunga né la lettura dello stato, dichiarare il limite prima di consegnare l'editor e usare come fallback la ripresa manuale in chat.

Il server deve restare vincolato a `127.0.0.1`, usare un token casuale e servire soltanto gli asset inclusi e il modello editoriale ricavato dal manifest.

`/api/session` espone anche `render_fingerprint` e lo stato durevole del feedback (`last_feedback_id`, `applied_feedback_id`, `feedback_pending`), letti sotto gli stessi lock della transazione. Il fingerprint è calcolato sullo snapshot visuale, sul checkpoint grossolano di approvazione, sul contratto di produzione/output, sul bundle HTML/JavaScript/CSS del renderer e sui byte effettivi di cover, loghi e font. Per un'azione `approve` il browser invia questo valore e `base_workflow_state` come eco della base mostrata; il server deriva `approval_stage` dallo stato corrente, calcola il fingerprint candidato dopo le modifiche e lo salva nel batch. Il client non decide autonomamente lo stage. Il passaggio da `bozza` a `testi_approvati` cambia il checkpoint e invalida un click rimasto aperto, mentre gli stati successivi alla prova visuale condividono lo stesso checkpoint. `/api/status` espone stato e checkpoint anche quando la revisione numerica non cambia, così l'editor può ricaricare una base pulita o preservare una bozza locale prima di bloccarla.

Nel checkpoint visuale il server espone anche il campione canonico `proof.required_slide_ids`: copertina, card interna più densa e chiusura quando presente. L'editor lega lo stato “visto” a revisione, checkpoint, fingerprint e sistema visivo, richiede che tutte le card del campione siano state osservate e invia `proof_slide_ids`, `style_system_verified: true` e la major Chromium effettiva. Se testi, ordine, sistema o logo sono stati modificati localmente, inviare prima le correzioni e riaprire la prova: non approvare nello stesso batch una composizione diversa da quella attestata. La prova visuale destinata all'export locale va quindi aperta in Chromium; altri motori restano utilizzabili per la revisione dei testi ma non possono firmare il proof esportabile.

La modalità `?render=production` è riservata all'export dopo l'approvazione visuale. Ignora le bozze del browser, carica l'ultimo manifest approvato, nasconde soltanto l'interfaccia di revisione e pubblica il contratto `approved-preview-dom-v2`. L'esportatore deve acquisire direttamente ogni `.slide-preview` e rifiutare il PDF se la geometria normalizzata non coincide con quella della normale anteprima aperta in una sessione pulita.

## Interazioni dell'editor

L'interfaccia rende disponibili modifica, riordino, commenti, enfasi tipografiche, scelta del sistema visivo e modalità del logo. Nel percorso normale affidarsi ai controlli e ai messaggi dell'editor. Leggere [editor-capabilities.md](editor-capabilities.md) soltanto se l'utente chiede istruzioni su questi comandi o se occorre diagnosticare un blocco dell'interfaccia.

## Ricezione e applicazione

Quando il server segnala un batch, riprendere automaticamente il lavoro e leggere `archive_path`, oppure `last_feedback_path` dallo stato quando la notifica non è arrivata. Usare `<session-dir>/feedback.json` soltanto come alias compatibile con le sessioni precedenti. Prima di applicarlo controllare che:

- `session-state.json` associ la cartella di sessione allo stesso manifest richiesto;
- `base_revision` corrisponda alla revisione corrente del manifest;
- tutti gli ID delle slide appartengano al manifest corrente;
- resti almeno una slide interna;
- il batch non superi i limiti dichiarati dal server.

Applicare le modifiche dirette con:

```text
python3 <skill>/scripts/apply_review.py <manifest.json> <feedback-path> --session-dir <session-dir>
```

Lo script deve accettare soltanto l'alias `feedback.json` o un batch archiviato in `feedback-batches/` appartenente alla cartella di sessione e al manifest associato. Quando esiste il batch append-only, l'alias deve coincidere esattamente. Lo script aggiorna soltanto i campi consentiti, preserva un backup atomico nella cartella di sessione e incrementa `revision` quando cambia contenuto, prova o composizione. Non avanza mai il workflow; se un feedback modifica copy/ordine/profilo o contiene una richiesta non classificabile dopo un checkpoint, riapre atomicamente `bozza` e azzera le ricevute. Se cambia soltanto sistema visivo, logo o enfasi tipografica, riapre `testi_approvati` conservando la ricevuta editoriale. Per `approval_stage: visual_proof` ricontrolla il fingerprint dopo l'applicazione e lega atomicamente `proof.approved` al render finale; per `profile_text` lascia la proof non approvata.

Lo script riallinea inoltre i riferimenti derivati dai testi:

- rimuove dai campi `*_bold`, `*_italic`, `*_serif` legacy, `*_underline` e `*_accent` le locuzioni che non compaiono più nel testo aggiornato e le elenca in `emphasis_dropped`;
- ricostruisce `accessibility.reading_order` secondo la sequenza risultante;
- ricostruisce `proof.slide_ids` come copertina, card più densa e chiusura opzionale, elencando in `proof_slide_ids_pruned` gli ID non più inclusi.

Leggere sempre `warnings`, `stale_alt_text` e `stale_transcript` nell'output. Lo script non riscrive i testi descrittivi: gli `alt_text` delle slide modificate e la trascrizione di accessibilità restano invariati e vanno rigenerati dall'agente prima della produzione. Se un batch di correzione cambia contenuto, ordine, sistema visivo o modalità del logo, lo script invalida atomicamente `proof.approved` e `proof.style_system_verified`, rimuove il binding del browser e segnala che serve una nuova prova. Un batch visuale `approve` non può includere modifiche editoriali; un feedback vuoto non può riaprire un checkpoint già approvato.

L'editor carica separatamente `display` per copertina e titoli e `body` per testi e metadati. Nei profili legacy usa `sans` per entrambi. Risolve `emphasis_italic` secondo [brand-profile.md](brand-profile.md), ne mostra il nome nell'interfaccia e non sintetizza un corsivo mancante. Espone inoltre `cover_subtitle` come campo opzionale e lo rende nello stesso ruolo corsivo.

Per l'anteprima dei logo servire soltanto asset raster autorizzati. Quando il master dichiarato è SVG e nella stessa cartella esiste un PNG omonimo, usare il PNG come derivato di anteprima e indicarlo nel pannello Brand. Non servire SVG non sanitizzati e non sostituire il master usato nella produzione finale.

Esaminare poi `comments` e `overall_note`. I commenti sono richieste da interpretare, non modifiche già effettuate. Applicare le correzioni necessarie al manifest, ripetere i controlli editoriali e aggiornare la revisione se occorre.

Se `action` è `approve`, trattarla come richiesta esplicita, non come avanzamento. Risolti i commenti e superati i controlli, eseguire `carousel_status.py`, quindi passare la revisione corrente a `scripts/advance_workflow.py` con la stessa `--session-dir`, secondo [workflow-state.md](workflow-state.md). Non modificare stato o ricevute a mano; se un gate fallisce mantenere il checkpoint.

## Ripresa e chiusura

Dopo l'applicazione il server registra l'esito in `session-state.json` e l'editor ricarica la base aggiornata senza refresh manuale. Chiudere il server quando la revisione termina o l'utente interrompe il lavoro. Se una risposta si perde, il processo si interrompe o compare un conflitto fra basi o schede, leggere [review-recovery.md](review-recovery.md) prima di agire.
